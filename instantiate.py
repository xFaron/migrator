"""
Usage:
    python3 validate_instantiate.py [generated_db.json] [queries.json]
"""

import json
import os
import sys

import psycopg
from dotenv import load_dotenv

if len(sys.argv) != 3:
  print("Usage: python3 validate_instantiate.py [generated_db.json] [queries.json]")

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
SCHEMA_NAME = "query_migr_generated"
GENERATED_DB_PATH = sys.argv[1]
QUERIES_PATH = sys.argv[2]

if not DB_URL:
  raise RuntimeError("Missing required environment variable: DATABASE_URL")

def split_statements(sql: str) -> list[str]:
  return [s.strip() for s in sql.split(";") if s.strip()]

def main() -> None:
  generated_db = json.load(open(GENERATED_DB_PATH))
  queries = json.load(open(QUERIES_PATH))

  with psycopg.connect(DB_URL) as conn:
    conn.autocommit = False
    try:
      with conn.cursor() as cur:
        print(f"Resetting schema {SCHEMA_NAME!r}...")
        cur.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE;")
        cur.execute(f"CREATE SCHEMA {SCHEMA_NAME};")
        cur.execute(f"SET search_path TO {SCHEMA_NAME};")

        print("Creating tables...")
        for stmt in split_statements(generated_db["target_database_schema"]):
          cur.execute(stmt)

        print("Populating tables...")
        for entry in generated_db["table_generation_queries"]:
          print(f"  -> {entry['target_table']}")
          cur.execute(f"INSERT INTO {entry['target_table']} {entry['query']}")

        print("Running validation queries...")
        for q in queries["queries"]:
          cur.execute(q["query"])
          cur.fetchall()

      conn.commit()
      print(f"Success. Committed as schema {SCHEMA_NAME!r}.")
    except Exception as e:
      conn.rollback()
      print(f"FAILED: {e}")
      print("Rolled back -- nothing was saved.")
      sys.exit(1)


if __name__ == "__main__":
  main()