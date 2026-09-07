import json
import os

import psycopg

SCHEMA_QUERY_PATH = os.path.join(os.path.dirname(__file__), "schema_query.sql")

def _load_schema_query() -> str:
  with open(SCHEMA_QUERY_PATH) as f:
    return f.read().replace("$1", "%(schema)s")


def fetch_schema_json_cur(cur, schema_name: str) -> dict:
  """Introspect a Postgres schema using an already-open cursor and return its
  tables/columns/constraints as JSON. Useful for introspecting a schema that
  only exists inside an uncommitted transaction on that same cursor."""
  query = _load_schema_query()
  cur.execute(query, {"schema": schema_name})
  (schema,) = cur.fetchone()
  return schema


def fetch_schema_json(db_url: str, schema_name: str) -> dict:
  """Introspect a Postgres schema and return its tables/columns/constraints as JSON."""
  with psycopg.connect(db_url) as conn:
    with conn.cursor() as cur:
      return fetch_schema_json_cur(cur, schema_name)


def get_table_schema(conn, tables: list[str]) -> dict:
  """Describe each table (name, columns, types, nullability, primary keys) as JSON."""
  result = []
  with conn.cursor() as cur:
    for table in tables:
      cur.execute("""
        SELECT
          c.column_name,
          c.data_type,
          c.is_nullable,
          pk.column_name IS NOT NULL AS primary_key
        FROM information_schema.columns c
        LEFT JOIN (
          SELECT ku.column_name
          FROM information_schema.table_constraints tc
          JOIN information_schema.key_column_usage ku
            ON tc.constraint_name = ku.constraint_name
           AND tc.table_schema = ku.table_schema
          WHERE tc.constraint_type = 'PRIMARY KEY'
            AND tc.table_name = %s
            AND tc.table_schema = 'public'
        ) pk ON c.column_name = pk.column_name
        WHERE c.table_name = %s AND c.table_schema = 'public'
        ORDER BY c.ordinal_position
      """, (table, table))
      cols = cur.fetchall()
      if not cols:
        continue
      result.append({
        "name": table,
        "columns": [
          {
            "name": col_name,
            "type": data_type,
            "nullable": nullable == "YES",
            "primary_key": primary_key,
          }
          for col_name, data_type, nullable, primary_key in cols
        ],
      })
  return {"tables": result}


def get_table_samples(conn, tables: list[str]) -> dict:
  """Fetch the top 5 rows of each table, as JSON."""
  result = []
  with conn.cursor() as cur:
    for table in tables:
      try:
        cur.execute(f"SELECT * FROM {table} LIMIT 5")
        rows = cur.fetchall()
        col_names = [desc[0] for desc in cur.description]
        result.append({
          "name": table,
          "rows": [dict(zip(col_names, row)) for row in rows],
        })
      except Exception:
        pass
  return {"tables": result}


# Runs EXPLAIN (FORMAT JSON)
def get_query_plan(conn_or_cur, query: str) -> str:
  if hasattr(conn_or_cur, "cursor"):
    with conn_or_cur.cursor() as cur:
      return _query_plan_from_cursor(cur, query)
  return _query_plan_from_cursor(conn_or_cur, query)

def _query_plan_from_cursor(cur, query: str) -> str:
  cur.execute(f"EXPLAIN (FORMAT JSON) {query}")
  plan = cur.fetchone()[0]
  return json.dumps(plan, indent=2)


# Runs query
def run_query(conn_or_cur, query: str) -> str:
  if hasattr(conn_or_cur, "cursor"):
    with conn_or_cur.cursor() as cur:
      return _run_query_from_cursor(cur, query)
  return _run_query_from_cursor(conn_or_cur, query)

def run_query(cur, query: str):
  cur.execute(query)
  return cur.fetchall()
