import argparse
import json
import os
import re

import psycopg
import sqlglot
from dotenv import load_dotenv
from sqlglot import exp

from db_tools import get_table_samples, get_query_plan, extract_tables
from llm_tools import query_model

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
OPTIM_PROMPT_PATH = os.getenv("OPTIM_PROMPT_PATH", "prompts/optim_query_prompt.md")


def extract_json(content: str) -> dict:
  fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.DOTALL)
  raw = fenced.group(1) if fenced else content
  return json.loads(raw, strict=False)

# Gets ddl of all input tables from schema_ddl ddl
def filter_table_schema(schema_ddl: str, tables: list[str]) -> str:
  table_set = set(tables)
  statements = []
  for stmt in sqlglot.transpile(schema_ddl, read="postgres"):
    try:
      parsed = sqlglot.parse_one(stmt, dialect="postgres")
    except Exception:
      continue
    if {t.name for t in parsed.find_all(exp.Table)} & table_set:
      statements.append(stmt)
  return "\n\n".join(statements)


def build_prompt(query: str, query_plan: str, table_schema: str, table_samples: dict) -> str:
  with open(OPTIM_PROMPT_PATH) as f:
    template = f.read()
  return (template
    .replace("{QUERY}", query)
    .replace("{QUERY_PLAN}", query_plan)
    .replace("{TABLE_SCHEMAS}", table_schema)
    .replace("{TABLE_SAMPLES}", json.dumps(table_samples, indent=2, default=str)))


def main() -> None:
  if not DB_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")

  parser = argparse.ArgumentParser()
  parser.add_argument("--db", type=int, default=1, metavar="N")
  args = parser.parse_args()

  db_dir = os.path.join("test_dbs", f"db{args.db}")
  db_path = os.path.join(db_dir, "db.json")
  queries_path = os.path.join(db_dir, "queries.json")

  if not os.path.exists(db_path) or not os.path.exists(queries_path):
    raise FileNotFoundError(
      f"Could not find {db_path!r} or {queries_path!r}. Run generate_db.py and generate_raw_queries.py first."
    )

  with open(db_path) as f:
    db_data = json.load(f)
  with open(queries_path) as f:
    q_data = json.load(f)

  source_schema_ddl = db_data["source_database_schema"]

  total = len(q_data["queries"])
  succeeded = 0

  with psycopg.connect(DB_URL, autocommit=True) as conn:
    for q in q_data["queries"]:
      qid = q.get("id", "?")

      if "error" in q or "raw_query_error" in q or "raw_query" not in q:
        print(f"[{qid}] Skipping (no raw query to optimize)")
        continue

      query = q["raw_query"]
      print(f"[{qid}] Optimizing...")

      # Gather context
      tables = extract_tables(query)
      try:
        table_schema = filter_table_schema(source_schema_ddl, tables)
        table_samples = get_table_samples(conn, tables)
      except Exception as e:
        print(f"[{qid}] Could not gather table context: {e}")
        q["optim_error"] = f"Could not gather table context: {e}"
        continue

      try:
        query_plan = get_query_plan(conn, query, analyze=False, json=False)
      except Exception as e:
        print(f"[{qid}] Could not get query plan: {e}")
        q["optim_error"] = f"Could not get query plan: {e}"
        continue

      # Query LLM
      prompt = build_prompt(query, query_plan, table_schema, table_samples)
      # print(prompt)
      try:
        message = query_model(prompt)
        content = message.get("content") or ""
        optim_query = extract_json(content)["query"]
      except Exception as e:
        print(f"[{qid}] LLM failed: {e}")
        q["optim_error"] = f"LLM failed: {e}"
        continue

      print(f"[{qid}] OK")
      q["optim_query"] = optim_query
      succeeded += 1

  with open(queries_path, "w") as f:
    json.dump(q_data, f, indent=2)

  print(f"Done. {succeeded}/{total} queries optimized.")


if __name__ == "__main__":
  main()
