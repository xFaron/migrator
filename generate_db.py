import argparse
import json
import os
import re
import sqlglot as exp

import psycopg
from dotenv import load_dotenv
from db_tools import check_env, fetch_schema_ddl, strip_schema_qualifiers, O_LST
from llm_tools import *
import query_store

load_dotenv()
check_env()

DB_URL = os.getenv("DATABASE_URL")
PROMPT_TEMPLATE_PATH = os.getenv("DB_PROMPT_PATH", "generate_db_prompt.md")
# D (the source database being designed) is instantiated in SOURCE_PG_SCHEMA;
# D' (the real target database) is read from TARGET_PG_SCHEMA.
SOURCE_PG_SCHEMA = os.getenv("SOURCE_PG_SCHEMA", "query_migr_generated")
TARGET_PG_SCHEMA = os.getenv("TARGET_PG_SCHEMA", "public")


def build_prompt(template_path: str, target_schema: str) -> str:
  with open(template_path) as f:
    template = f.read()
  return template.replace("{STGT}", target_schema)

def extract_json(content: str) -> dict:
  fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
  raw = fenced[-1] if fenced else content
  return json.loads(raw, strict=False)

# Checks syntactic validity of statements.
def validate_generated_db(generated_db: dict) -> dict:
  for key in ("source_schema", "table_generation_queries"):
    if key not in generated_db:
      raise KeyError(f"Model response is missing required key {key!r}.")

  with psycopg.connect(DB_URL) as conn:
    conn.autocommit = False
    try:
      with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {SOURCE_PG_SCHEMA} CASCADE;")
        cur.execute(f"CREATE SCHEMA {SOURCE_PG_SCHEMA};")
        cur.execute(f"SET search_path TO {SOURCE_PG_SCHEMA}, {TARGET_PG_SCHEMA};")

        # Checking if CREATE/ALTER stmt are valid
        for stmt in exp.transpile(generated_db["source_schema"], read="postgres"):
          cur.execute(stmt)

        # Checking if insertion select queries are valid
        for table in generated_db["table_generation_queries"]:
          cur.execute(
            f"EXPLAIN INSERT INTO {table["source_table"]} {exp.transpile(table["query"], read="postgres")[0]}"
          )

      # Commit so the schema is visible to `pg_dump`, which runs as a
      # separate connection/process and cannot see uncommitted changes.
      conn.commit()
      try:
        # Getting the validated schema's real DDL for the next step
        stmts = fetch_schema_ddl(DB_URL, SOURCE_PG_SCHEMA, flags=O_LST)
        stmts = list(map(lambda stmt: strip_schema_qualifiers(stmt) + ";", stmts))
        generated_db["source_schema"] = "\n\n".join(stmts)

      finally:
        with conn.cursor() as cur:
          cur.execute(f"DROP SCHEMA IF EXISTS {SOURCE_PG_SCHEMA} CASCADE;")
        conn.commit()
    except Exception:
      conn.rollback()
      raise

    return generated_db


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--db", type=int, default=1, metavar="N")
  args = parser.parse_args()

  if not DB_URL:
    raise SystemExit("Missing required environment variable: DATABASE_URL")

  output_dir = query_store.db_dir(args.db)
  os.makedirs(output_dir, exist_ok=True)

  target_schema = fetch_schema_ddl(DB_URL, TARGET_PG_SCHEMA)
  prompt = build_prompt(PROMPT_TEMPLATE_PATH, target_schema)

  print("Calling LLM...")
  print(prompt)
  message = query_model(prompt)

  content = message.get("content") or ""

  fallback_path = os.path.join(output_dir, "db.raw.txt")
  error = None
  try:
    generated_db = extract_json(content)
    generated_db["target_schema"] = target_schema

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

  # Catch a model that echoed pre-refactor key names now, rather than leaving a
  # file on disk that every later stage refuses to load.
  query_store.validate_db(generated_db, query_store.db_path(args.db))
  query_store.save_db(args.db, generated_db)

  print("Done.")

if __name__ == "__main__":
  main()
