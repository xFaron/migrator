import json
import os
import sys

import psycopg
from dotenv import load_dotenv

if len(sys.argv) != 3:
  sys.exit("Usage: python3 instantiate.py <db.json> <queries.json>")

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
SCHEMA_NAME = os.getenv("GENERATED_SCHEMA", "query_migr_generated")
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
        cur.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE;")
        cur.execute(f"CREATE SCHEMA {SCHEMA_NAME};")
        cur.execute(f"SET search_path TO {SCHEMA_NAME}, public;")

        for stmt in split_statements(generated_db["target_database_schema"]):
          cur.execute(stmt)

        print("Populating tables...")
        for entry in generated_db["table_generation_queries"]:
          cur.execute(f"INSERT INTO {entry['target_table']} {entry['query']}")
        print("Populated all tables... Verifying queries")

        # LLM-generated queries can be pathologically expensive (e.g. uncorrelated
        # nested subqueries with no supporting index); cap runtime so one bad query
        # can't hang the pipeline indefinitely. Such queries are ignored.
        cur.execute("SET statement_timeout = '60s'")

        total = len(queries["queries"])
        kept = []
        for q in queries["queries"]:
          try:
            cur.execute(q["query"])  
            rows = cur.fetchall()
            if rows:
              kept.append(q)
            else:
              print(f"Omitting query id={q.get('id', '?')} (zero rows)")
          except psycopg.errors.QueryCanceled as e:
            pass

      conn.commit()
      print("Done.")
    except Exception as e:
      conn.rollback()
      print(f"FAILED: {e}")
      sys.exit(1)

  queries["queries"] = kept
  with open(QUERIES_PATH, "w") as f:
    json.dump(queries, f, indent=2)
  print(f"Kept {len(kept)}/{total} queries.")


if __name__ == "__main__":
  main()