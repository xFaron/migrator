import argparse
import json
import os

import psycopg
import sqlglot
from dotenv import load_dotenv
from psycopg import sql
from sqlglot import exp

from db_tools import run_query

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
# Schema where the generated D tables live (created by instantiate.py)
GENERATED_SCHEMA = os.getenv("GENERATED_SCHEMA", "query_migr_generated")


def build_raw_query(query: str, generation_query_by_table: dict) -> str:
  expr = sqlglot.parse_one(query, dialect="postgres")

  tables = set()
  with_clause = expr.args.get("with_")
  
  for node in expr.walk():
    table = node.name
    if isinstance(node, exp.Table) and table in generation_query_by_table and table not in tables:
      expr = expr.with_(table, as_=generation_query_by_table[table], append=(len(tables) != 0))
      tables.add(node.name)

  if with_clause:
    for cte in with_clause.expressions:
      expr = expr.with_(cte.alias, as_=cte.this)  

  return expr.sql(dialect="postgres")


def normalize_rows(rows):
  """Order-independent, type-safe comparison of two result sets."""
  return sorted(tuple((v is None, str(v)) for v in row) for row in rows)


def main() -> None:
  if not DB_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")

  parser = argparse.ArgumentParser()
  parser.add_argument("--db", type=int, default=1, metavar="N")
  args = parser.parse_args()

  db_dir = os.path.join("test_dbs", f"db{args.db}")
  db_path = os.path.join(db_dir, "db.json")
  queries_path = os.path.join(db_dir, "queries.json")
  output_path = os.path.join(db_dir, "raw_queries.json")

  for path in (db_path, queries_path):
    if not os.path.exists(path):
      raise FileNotFoundError(
        f"Could not find {path!r}. "
        "Run generate_db.py and generate_query.py first."
      )

  with open(db_path) as f:
    db_data = json.load(f)
  with open(queries_path) as f:
    q_data = json.load(f)

  # Map: target table name → SELECT that generates it from D'
  generation_query_by_table = {
    tg["target_table"]: sqlglot.transpile(tg["query"])[0]
    for tg in db_data["table_generation_queries"]
  }

  raw_queries = []

  with psycopg.connect(DB_URL, autocommit=True) as conn:
    with conn.cursor() as cur:
      cur.execute("SET statement_timeout = '60s'")

    for q in q_data["queries"]:
      qid = q.get("id", "?")

      if "error" in q:
        print(f"[{qid}] Skipping (already has error): {q['error']}")
        raw_queries.append(q)
        continue

      # Step 1: deterministic transformation
      # print(f"[{qid}] Building raw query")
      try:
        raw_query = build_raw_query(q["query"], generation_query_by_table)
      except Exception as e:
        print(f"[{qid}] Failed to transform query: {e}")
        raw_queries.append({**q, "error": f"Failed to transform query: {e}"})
        continue

      # Step 2: run original query on D (generated schema)
      # print(f"[{qid}] Running original_query(D)")
      try:
        with conn.cursor() as cur:
          cur.execute(
            sql.SQL("SET search_path TO {}").format(
              sql.Identifier(GENERATED_SCHEMA)
            )
          )
        # print(q["query"])
        original_rows = run_query(conn, q["query"])
      except Exception as e:
        print(f"[{qid}] Original query failed to execute on D: {e}")
        raw_queries.append({**q, "query": raw_query, "error": f"Original query failed to execute on D: {e}"})
        continue

      # Step 3: run raw query on D' (public schema)
      # print(f"[{qid}] Running new_query(D')")
      try:
        with conn.cursor() as cur:
          cur.execute("SET search_path TO public")
        # print(raw_query)
        raw_rows = run_query(conn, raw_query)
      except Exception as e:
        print(f"[{qid}] Raw query failed to execute on D': {e}")
        raw_queries.append({**q, "query": raw_query, "error": f"Raw query failed to execute on D': {e}"})
        continue

      # Step 4: compare results
      if normalize_rows(original_rows) != normalize_rows(raw_rows):
        error = (
          f"Result mismatch. Original rows: {len(original_rows)}, Raw rows: {len(raw_rows)}"
        )
        print(f"[{qid}] {error}")
        raw_queries.append({**q, "query": raw_query, "error": error})
        continue

      print(f"[{qid}] OK")
      raw_queries.append({**q, "query": raw_query})

  with open(output_path, "w") as f:
    json.dump({"queries": raw_queries}, f, indent=2)

  print("Done.")


if __name__ == "__main__":
  main()
