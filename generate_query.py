import argparse
import json
import os
import re

import psycopg
import sqlglot as exp
from dotenv import load_dotenv
from llm_tools import *
from db_tools import strip_schema_qualifiers

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
PROMPT_QUERY_GEN = os.getenv("QUERY_PROMPT_PATH", "generate_query_prompt.md")
DEFAULT_K = int(os.getenv("DEFAULT_K", "5"))
GENERATED_SCHEMA = os.getenv("GENERATED_SCHEMA", "query_migr_generated")

if not DB_URL:
  raise RuntimeError("Missing required environment variable: DATABASE_URL")

def load_generated_db(generated_db_path: str) -> str:
  if not os.path.exists(generated_db_path):
    raise FileNotFoundError(
      f"Could not find {generated_db_path!r}. Run generate_db.py first to produce it."
    )

  with open(generated_db_path) as f:
    generated_db = json.load(f)

  return generated_db

def build_prompt(template_path: str, db_schema: str, k: int) -> str:
  with open(template_path) as f:
    template = f.read()
  return template.replace("{DB_SCHEMA}", db_schema).replace("{K}", str(k))

def extract_json(content: str) -> dict:
  fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
  raw = fenced[-1] if fenced else content
  return json.loads(raw, strict=False)

# Checks syntactic validity of the generated queries against the instantiated
# target schema by EXPLAINing each one (no rows are read/written).
def validate_generated_queries(queries: dict, generated_db: dict) -> dict:
  new_queries = {}
  new_queries["queries"] = []
  
  with psycopg.connect(DB_URL) as conn:
    conn.autocommit = False
    try:
      with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {GENERATED_SCHEMA} CASCADE;")
        cur.execute(f"CREATE SCHEMA {GENERATED_SCHEMA};")
        cur.execute(f"SET search_path TO {GENERATED_SCHEMA}, public;")

        # Checking if CREATE/ALTER stmt are valid
        for stmt in exp.transpile(generated_db["target_database_schema"], read="postgres"):
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
  parser = argparse.ArgumentParser()
  parser.add_argument("--db", type=int, default=1, metavar="N")
  parser.add_argument("--k", type=int, default=DEFAULT_K, metavar="K")
  args = parser.parse_args()

  output_dir = os.path.join("test_dbs", f"db{args.db}")
  db_path = os.path.join(output_dir, "db.json")
  queries_path = os.path.join(output_dir, "queries.json")

  generated_db = load_generated_db(db_path)
  db_schema = generated_db["target_database_schema"]
  prompt = build_prompt(PROMPT_QUERY_GEN, db_schema, args.k)

  print("Calling LLM...")
  message = query_model(prompt)
  content = message.get("content") or ""

  fallback_path = os.path.join(output_dir, "queries.raw.txt")
  error = None
  try:
    queries = extract_json(content)

    print("Filtering valid ones...")
    queries = validate_generated_queries(queries, generated_db)
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

  with open(queries_path, "w") as f:
    json.dump(queries, f, indent=2)

  print("Done.")


if __name__ == "__main__":
  main()
