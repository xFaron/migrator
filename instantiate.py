import argparse
import os
import sys

import psycopg
from tqdm import tqdm
from dotenv import load_dotenv

import query_store
from db_tools import check_env

load_dotenv()
check_env()

DB_URL = os.getenv("DATABASE_URL")
SOURCE_PG_SCHEMA = os.getenv("SOURCE_PG_SCHEMA", "query_migr_generated")
TARGET_PG_SCHEMA = os.getenv("TARGET_PG_SCHEMA", "public")


def split_statements(sql: str) -> list[str]:
  return [s.strip() for s in sql.split(";") if s.strip()]

def main() -> None:
  parser = argparse.ArgumentParser(
    description="Instantiate D in SOURCE_PG_SCHEMA and drop queries that return no rows."
  )
  parser.add_argument("--db", type=int, default=1, metavar="N")
  args = parser.parse_args()

  if not DB_URL:
    raise SystemExit("Missing required environment variable: DATABASE_URL")

  db_data = query_store.load_db(args.db)
  queries = query_store.load_queries(args.db)

  with psycopg.connect(DB_URL) as conn:
    conn.autocommit = False
    try:
      with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {SOURCE_PG_SCHEMA} CASCADE;")
        cur.execute(f"CREATE SCHEMA {SOURCE_PG_SCHEMA};")
        cur.execute(f"SET search_path TO {SOURCE_PG_SCHEMA}, {TARGET_PG_SCHEMA};")

        for stmt in split_statements(db_data["source_schema"]):
          cur.execute(stmt)

        print("Populating tables...")
        for entry in tqdm(db_data["table_generation_queries"]):
          cur.execute(f"INSERT INTO {entry['source_table']} {entry['query']}")
        print("Populated all tables... Verifying queries")

        # LLM-generated queries can be pathologically expensive (e.g. uncorrelated
        # nested subqueries with no supporting index); cap runtime so one bad query
        # can't hang the pipeline indefinitely. Such queries are ignored.
        cur.execute("SET statement_timeout = '60s'")

        total = len(queries["queries"])
        kept = []
        for q in queries["queries"]:
          if "error" in q:
            print(f"Skipping query id={q.get('id', '?')} (already has error): {q['error']}")
            kept.append(q)
            continue

          # A savepoint lets us recover from a per-query failure (e.g. a
          # statement_timeout cancellation) without poisoning the whole
          # transaction, since Postgres otherwise aborts it entirely until
          # a ROLLBACK is issued.
          cur.execute("SAVEPOINT query_check")
          try:
            cur.execute(q["query"])
            rows = cur.fetchall()
            if rows:
              kept.append(q)
            else:
              print(f"Omitting query id={q.get('id', '?')} (zero rows)")
            cur.execute("RELEASE SAVEPOINT query_check")
          except psycopg.errors.QueryCanceled:
            print(f"Omitting query id={q.get('id', '?')} (timed out)")
            cur.execute("ROLLBACK TO SAVEPOINT query_check")

      conn.commit()
      print("Done.")
    except Exception as e:
      conn.rollback()
      print(f"FAILED: {e}")
      sys.exit(1)

  queries["queries"] = kept
  query_store.save_queries(args.db, queries)
  print(f"Kept {len(kept)}/{total} queries.")


if __name__ == "__main__":
  main()
