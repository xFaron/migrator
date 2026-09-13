import argparse
import json
import os

import psycopg
import sqlglot
from dotenv import load_dotenv
from sqlglot import exp
from tqdm import tqdm

from db_tools.correctness import simple_equivalence

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
SOURCE_SCHEMA = os.getenv("SOURCE_SCHEMA", "public")
GENERATED_SCHEMA = os.getenv("GENERATED_SCHEMA", "query_migr_generated")

if not DB_URL:
  raise RuntimeError("Missing required environment variable: DATABASE_URL")


def extract_table_columns(schema_ddl: str) -> dict[str, list[str]]:
  """Map target table name -> its column names in DDL order, by parsing the
  target database's CREATE TABLE statements."""
  columns_by_table = {}
  for stmt in sqlglot.transpile(schema_ddl, read="postgres"):
    try:
      parsed = sqlglot.parse_one(stmt, dialect="postgres")
    except Exception:
      continue
    if isinstance(parsed, exp.Create) and parsed.kind == "TABLE":
      table_name = parsed.this.this.name
      schema = parsed.this
      columns_by_table[table_name] = [
        col.this.name for col in schema.expressions if isinstance(col, exp.ColumnDef)
      ]
  return columns_by_table


def split_statements(sql: str) -> list[str]:
  return [s.strip() for s in sql.split(";") if s.strip()]


def build_raw_query(query: str, generation_query_by_table: dict, columns_by_table: dict) -> str:
  expr = sqlglot.parse_one(query, dialect="postgres")
  with_clause = expr.args.get("with_")

  tables = {
    node.name for node in expr.walk()
    if isinstance(node, exp.Table) and node.name in generation_query_by_table
  }

  for i, table in enumerate(tables):
    alias = f"{table}({', '.join(columns_by_table[table])})" if table in columns_by_table else table
    expr = expr.with_(alias, as_=generation_query_by_table[table], append=(i != 0), dialect="postgres")

  if with_clause:
    for cte in with_clause.expressions:
      expr = expr.with_(cte.alias, as_=cte.this, dialect="postgres")

  for node in expr.walk():
    if isinstance(node, exp.Table) and node.name in tables:
      node.set("db", None)
      node.set("catalog", None)

  return expr.sql(dialect="postgres")


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--db", type=int, default=1, metavar="N")
  args = parser.parse_args()

  db_dir = os.path.join("test_dbs", f"db{args.db}")
  db_path = os.path.join(db_dir, "db.json")
  queries_path = os.path.join(db_dir, "queries.json")

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
  columns_by_table = extract_table_columns(db_data["target_database_schema"])

  # Instantiate D in a transaction that's rolled back at the end: this script
  # only needs D to exist long enough to verify each raw query against its
  # source, and must not disturb (or depend on) a separately instantiated
  # GENERATED_SCHEMA.
  with psycopg.connect(DB_URL) as conn:
    conn.autocommit = False
    try:
      with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {GENERATED_SCHEMA} CASCADE;")
        cur.execute(f"CREATE SCHEMA {GENERATED_SCHEMA};")
        cur.execute(f"SET search_path TO {GENERATED_SCHEMA}, {SOURCE_SCHEMA};")

        for stmt in split_statements(db_data["target_database_schema"]):
          cur.execute(stmt)

        print("Populating tables...")
        for entry in tqdm(db_data["table_generation_queries"]):
          cur.execute(f"INSERT INTO {entry['target_table']} {entry['query']}")

        # LLM-generated queries can be pathologically expensive; cap runtime so
        # one bad query can't hang this indefinitely (same policy as instantiate.py).
        cur.execute("SET statement_timeout = '600s';")

        print("Checking result equivalence...")
        for q in tqdm(q_data["queries"]):
          qid = q.get("id", "?")

          if "error" in q:
            # print(f"[{qid}] Skipping (already has error): {q['error']}")
            continue

          try:
            q["raw_query"] = build_raw_query(q["query"], generation_query_by_table, columns_by_table)
          except Exception as e:
            # print(f"[{qid}] Failed to transform query: {e}")
            q["error"] = f"Failed to transform query: {e}"
            continue

          cur.execute("SAVEPOINT raw_query_check")
          try:
            if not simple_equivalence(cur, q["query"], q["raw_query"]):
              q["error"] = "Raw query result does not match source query"
            cur.execute("RELEASE SAVEPOINT raw_query_check")
          except Exception as e:
            cur.execute("ROLLBACK TO SAVEPOINT raw_query_check")
            # print(f"[{qid}] Failed to verify raw query: {e}")
            q["error"] = f"Failed to verify raw query: {e}"
    finally:
      conn.rollback()

  with open(queries_path, "w") as f:
    json.dump(q_data, f, indent=2)

  print("Done.")


if __name__ == "__main__":
  main()
