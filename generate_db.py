import argparse
import json
import os
import re
import sqlglot as exp

import psycopg
from dotenv import load_dotenv
from db_tools import fetch_schema_ddl
from llm_tools import *

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
PROMPT_TEMPLATE_PATH = os.getenv("DB_PROMPT_PATH", "generate_db_prompt.md")
SCHEMA_NAME = os.getenv("GENERATED_SCHEMA", "query_migr_generated")
SOURCE_SCHEMA = os.getenv("SOURCE_SCHEMA", "public")

if not DB_URL:
  raise RuntimeError("Missing required environment variable: DATABASE_URL")

def build_prompt(template_path: str, schema: str) -> str:
  with open(template_path) as f:
    template = f.read()
  return template.replace("{DB_SCHEMA}", schema)

def extract_json(content: str) -> dict:
  fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.DOTALL)
  raw = fenced.group(1) if fenced else content
  return json.loads(raw, strict=False)

# Checks syntactic validity of statements.
def validate_generated_db(generated_db: dict) -> dict:
  with psycopg.connect(DB_URL) as conn:
    conn.autocommit = False
    try:
      with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE;")
        cur.execute(f"CREATE SCHEMA {SCHEMA_NAME};")
        cur.execute(f"SET search_path TO {SCHEMA_NAME}, public;")

        # Checking if CREATE/ALTER stmt are valid
        for stmt in exp.transpile(generated_db["target_database_schema"], read="postgres"):
          cur.execute(stmt)

        # Checking if insertion select queries are valid
        for table in generated_db["table_generation_queries"]:
          cur.execute(
            f"EXPLAIN INSERT INTO {table["target_table"]} {exp.transpile(table["query"], read="postgres")[0]}"
          )

      # Commit so the schema is visible to `pg_dump`, which runs as a
      # separate connection/process and cannot see uncommitted changes.
      conn.commit()
      try:
        # Getting the validated schema's real DDL for the next step
        generated_db["target_database_schema"] = fetch_schema_ddl(DB_URL, SCHEMA_NAME)
      finally:
        with conn.cursor() as cur:
          cur.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE;")
        conn.commit()
    except Exception:
      conn.rollback()
      raise

    return generated_db


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--db", type=int, default=1, metavar="N")
  args = parser.parse_args()

  output_dir = os.path.join("test_dbs", f"db{args.db}")
  output_path = os.path.join(output_dir, "db.json")

  os.makedirs(output_dir, exist_ok=True)

  schema = fetch_schema_ddl(DB_URL, SOURCE_SCHEMA)
  prompt = build_prompt(PROMPT_TEMPLATE_PATH, schema)

  print("Calling LLM...")
  message = query_model(prompt)

  content = message.get("content") or ""

  fallback_path = os.path.join(output_dir, "db.raw.txt")
  error = None
  try:
    generated_db = extract_json(content)
    generated_db["source_database_schema"] = schema

    print("Validating...")
    generated_db = validate_generated_db(generated_db)
  except json.JSONDecodeError as e:
    error = e
    raise RuntimeError(
      f"Model did not return valid JSON. Raw response saved to {fallback_path!r} for inspection."
    )
  except Exception as e:
    error = e
    raise RuntimeError(
      f"Validation error: Raw response saved to {fallback_path!r} for inspection"
    )
  finally:
    with open(fallback_path, "w") as f:
      f.write(content)
      f.write(f"\n\n\nERROR: {error}")
      
  with open(output_path, "w") as f:
    json.dump(generated_db, f, indent=2)

  print("Done.")

if __name__ == "__main__":
  main()
