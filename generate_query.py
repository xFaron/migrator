import argparse
import json
import os
import re

import psycopg
import sqlglot as exp
from dotenv import load_dotenv
from llm_tools import *
from db_tools import check_env, strip_schema_qualifiers

import query_store

load_dotenv()
check_env()

DB_URL = os.getenv("DATABASE_URL")
PROMPT_QUERY_GEN = os.getenv("QUERY_PROMPT_PATH", "generate_query_prompt.md")
DEFAULT_K = int(os.getenv("DEFAULT_K", "5"))
SOURCE_PG_SCHEMA = os.getenv("SOURCE_PG_SCHEMA", "query_migr_generated")
TARGET_PG_SCHEMA = os.getenv("TARGET_PG_SCHEMA", "public")


def build_prompt(template_path: str, db_schema: str, k: int) -> str:
  with open(template_path) as f:
    template = f.read()
  return template.replace("{SSRC}", db_schema).replace("{K}", str(k))

def extract_json(content: str) -> dict:
  fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
  raw = fenced[-1] if fenced else content
  return json.loads(raw, strict=False)

# Checks syntactic validity of the generated queries against D, instantiated in
# SOURCE_PG_SCHEMA, by EXPLAINing each one (no rows are read/written).
def validate_generated_queries(queries: dict, db_data: dict) -> dict:
  new_queries = {}
  new_queries["queries"] = []

  with psycopg.connect(DB_URL) as conn:
    conn.autocommit = False
    try:
      with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {SOURCE_PG_SCHEMA} CASCADE;")
        cur.execute(f"CREATE SCHEMA {SOURCE_PG_SCHEMA};")
        cur.execute(f"SET search_path TO {SOURCE_PG_SCHEMA}, {TARGET_PG_SCHEMA};")

        # Checking if CREATE/ALTER stmt are valid
        for stmt in exp.transpile(db_data["source_schema"], read="postgres"):
          cur.execute(stmt)

        for q in queries["queries"]:
          q["query"] = strip_schema_qualifiers(q["query"])
          try:
            stmt = exp.transpile(q["query"], read="postgres")[0]
            cur.execute(f"EXPLAIN {stmt}")
            new_queries["queries"].append(q)
          except Exception as e:
            print(f"qid = {q.get('id', '?')} is syntactically invalid: {e}")
            new_queries["queries"].append({**q, "error": f"Syntactically invalid: {e}"})
    finally:
      conn.rollback()

  return new_queries

def main() -> None:
  parser = argparse.ArgumentParser(
    description="Generate K queries against D's schema (db.json's `source_schema`)."
  )
  parser.add_argument("--db", type=int, default=1, metavar="N")
  parser.add_argument("--k", type=int, default=DEFAULT_K, metavar="K")
  args = parser.parse_args()

  if not DB_URL:
    raise SystemExit("Missing required environment variable: DATABASE_URL")

  db_data = query_store.load_db(args.db)
  prompt = build_prompt(PROMPT_QUERY_GEN, db_data["source_schema"], args.k)

  print("Calling LLM...")
  print(prompt)
  message = query_model(prompt)
  content = message.get("content") or ""

  fallback_path = os.path.join(query_store.db_dir(args.db), "queries.raw.txt")
  error = None
  try:
    queries = extract_json(content)

    print("Filtering valid ones...")
    queries = validate_generated_queries(queries, db_data)
  except json.JSONDecodeError as e:
    error = e
    raise RuntimeError(
      f"Model did not return valid JSON. Raw response saved to {fallback_path!r} for inspection."
    )
  except Exception as e:
    error = e
    raise RuntimeError(
      f"Filtering error: {e}.Raw response saved to {fallback_path!r} for inspection."
    )
  finally:
    with open(fallback_path, "w") as f:
      f.write(content)
      f.write(f"\n\n\nERROR: {error}")

  query_store.save_queries(args.db, queries)

  print("Done.")


if __name__ == "__main__":
  main()
