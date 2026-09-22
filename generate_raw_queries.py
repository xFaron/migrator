import argparse
import os

import psycopg
import sqlglot
from dotenv import load_dotenv
from sqlglot import exp
from tqdm import tqdm

from db_tools import check_env
from db_tools.correctness import simple_equivalence

import query_store

load_dotenv()
check_env()

DB_URL = os.getenv("DATABASE_URL")
TARGET_PG_SCHEMA = os.getenv("TARGET_PG_SCHEMA", "public")
SOURCE_PG_SCHEMA = os.getenv("SOURCE_PG_SCHEMA", "query_migr_generated")
# VIRTUAL_TABLES = False


def extract_table_columns(schema_ddl: str) -> dict[str, list[tuple[str, str]]]:
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
        (col.this.name, col.args["kind"].sql(dialect="postgres"))
        for col in schema.expressions if isinstance(col, exp.ColumnDef)
      ]
  return columns_by_table


def cast_generation_query(query: str, columns: list[tuple[str, str]]) -> str:
  select = sqlglot.parse_one(query, dialect="postgres")
  if len(select.expressions) != len(columns):
    return select.sql(dialect="postgres")

  new_expressions = []
  for proj, (col_name, col_type) in zip(select.expressions, columns):
    inner = proj.this if isinstance(proj, exp.Alias) else proj
    casted = exp.Cast(this=inner.copy(), to=exp.DataType.build(col_type, dialect="postgres"))
    new_expressions.append(exp.alias_(casted, col_name))
  select.set("expressions", new_expressions)

  return select.sql(dialect="postgres")


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
    column_names = [name for name, _ in columns_by_table[table]] if table in columns_by_table else []
    alias = f"{table}({', '.join(column_names)})" if column_names else table
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

  if not DB_URL:
    raise SystemExit("Missing required environment variable: DATABASE_URL")

  hint = "Run generate_db.py and generate_query.py first."
  db_data = query_store.load_db(args.db, hint)
  q_data = query_store.load_queries(args.db, hint)

  columns_by_table = extract_table_columns(db_data["source_schema"])

  # Map: source table name → SELECT that generates it from D', with each
  # projected column cast to its source column's declared type (see
  # cast_generation_query) so the raw query's values match what
  # instantiate.py actually stored in D.
  generation_query_by_table = {
    tg["source_table"]: cast_generation_query(
      sqlglot.transpile(tg["query"], read="postgres")[0], columns_by_table.get(tg["source_table"], [])
    )
    for tg in db_data["table_generation_queries"]
  }

  # Instantiate D in a transaction that's rolled back at the end: this script
  # only needs D to exist long enough to verify each raw query against its
  # source, and must not disturb (or depend on) a separately instantiated
  # SOURCE_PG_SCHEMA.
  with psycopg.connect(DB_URL) as conn:
    conn.autocommit = False
    try:
      with conn.cursor() as cur:
        cur.execute(f"SET search_path TO {SOURCE_PG_SCHEMA}, {TARGET_PG_SCHEMA};")

        cur.execute(f"SELECT table_name FROM information_schema.tables WHERE table_schema = '{SOURCE_PG_SCHEMA}';")
        present_tables = set(map(lambda x: x[0], cur.fetchall()));
        required_tables = set(map(lambda x: x["source_table"], db_data["table_generation_queries"]))
        if (len(required_tables - present_tables) != 0):
          cur.execute(f"DROP SCHEMA IF EXISTS {SOURCE_PG_SCHEMA} CASCADE;")
          cur.execute(f"CREATE SCHEMA {SOURCE_PG_SCHEMA};")
  
          for stmt in split_statements(db_data["source_schema"]):
            cur.execute(stmt)
  
          print("Populating tables (temp)...")
          for entry in tqdm(db_data["table_generation_queries"]):
            cur.execute(f"INSERT INTO {entry['source_table']} {entry['query']}")

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

  query_store.save_queries(args.db, q_data)

  print("Done.")


if __name__ == "__main__":
  main()
