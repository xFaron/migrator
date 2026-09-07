import argparse
import json
import os
import re

import psycopg
import sqlglot as exp
from dotenv import load_dotenv
from llm_tools import *

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
PROMPT_QUERY_GEN = os.getenv("QUERY_PROMPT_PATH", "generate_query_prompt.md")
DEFAULT_K = int(os.getenv("DEFAULT_K", "5"))
GENERATED_SCHEMA = os.getenv("GENERATED_SCHEMA", "query_migr_generated")

if not DB_URL:
  raise RuntimeError("Missing required environment variable: DATABASE_URL")

def load_target_schema(generated_db_path: str) -> dict:
  if not os.path.exists(generated_db_path):
    raise FileNotFoundError(
      f"Could not find {generated_db_path!r}. Run generate_db.py first to produce it."
    )

  with open(generated_db_path) as f:
    generated_db = json.load(f)

  schema = generated_db.get("target_database_schema_json")
  if not schema or not schema.get("tables"):
    raise RuntimeError(
      f"No 'target_database_schema_json' found in {generated_db_path!r}. "
      "Re-run generate_db.py to produce it."
    )
  return schema

def build_prompt(template_path: str, db_schema: dict, k: int) -> str:
  with open(template_path) as f:
    template = f.read()
  return template.replace("{DB_SCHEMA}", json.dumps(db_schema, indent=2)).replace("{K}", str(k))

def extract_json(content: str) -> dict:
  fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.DOTALL)
  raw = fenced.group(1) if fenced else content
  return json.loads(raw, strict=False)

# Checks syntactic validity of the generated queries against the instantiated
# target schema by EXPLAINing each one (no rows are read/written).
def validate_generated_queries(queries: dict, generate_db: dict) -> dict:
  new_queries = {}
  new_queries["queries"] = []
  
  with psycopg.connect(DB_URL) as conn:
    conn.autocommit = False
    try:
      with conn.cursor() as cur:        
        cur.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE;")
        cur.execute(f"CREATE SCHEMA {SCHEMA_NAME};")
        cur.execute(f"SET search_path TO {SCHEMA_NAME}, public;")

        # Checking if CREATE/ALTER stmt are valid
        for stmt in exp.transpile(generated_db["target_database_schema"]):
          cur.execute(stmt)

        for q in queries["queries"]:
          try:
            stmt = exp.transpile(q["query"], read="postgres")[0]
            cur.execute(f"EXPLAIN {stmt}")
            new_queries.append(q)
          except Exception as e:
            printf(f"qid = {q["id"]} is syntactically invalid: {e}")
    finally:
      conn.rollback()

  return new_queries

def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--db", type=int, default=1, metavar="N")
  parser.add_argument("--k", type=int, default=DEFAULT_K, metavar="K")
  args = parser.parse_args()

  output_dir = os.path.join("test_dbs", f"db{args.db}")
  db_path = os.path.join(output_dir, "db.json")
  queries_path = os.path.join(output_dir, "queries.json")

  db_schema = load_target_schema(db_path)
  prompt = build_prompt(PROMPT_QUERY_GEN, db_schema, args.k)

  print("Calling LLM...")
  message = query_model(prompt)
  content = message.get("content") or ""

  fallback_path = os.path.join(output_dir, "queries.raw.txt")
  error = None
  try:
    queries = extract_json(content)

    print("Filtering valid ones...")
    queries = validate_generated_queries(queries)
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
      f.write(f"\n\n\nERROR: {e}")

  with open(queries_path, "w") as f:
    json.dump(queries, f, indent=2)

  print("Done.")


if __name__ == "__main__":
  main()
