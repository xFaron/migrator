import json
import re
import subprocess
import sqlglot as exp
# import warnings

# warnings.filterwarnings("ignore", module="exp")

O_LST = 1 # Output list
O_STR = 0 # Output str

def fetch_schema_ddl(db_url: str, schema_name: str, tables: list[str] | None = None, flags: int = O_STR) -> str:
  """Dump a Postgres schema's DDL (CREATE TABLE/constraint/index statements) via
  `pg_dump --schema-only`, optionally restricted to a subset of tables.

  This is the canonical way to describe a schema to an LLM prompt: it reflects
  exactly what Postgres will create, with none of the drift or omissions a
  hand-rolled information_schema/pg_catalog query can introduce.
  """
  cmd = [
    "pg_dump", db_url,
    "--schema-only",
    "--no-owner",
    "--no-privileges",
    "--no-comments",
    "--no-tablespaces",
    "-n", schema_name,
  ]
  for table in tables or []:
    cmd += ["-t", f"{schema_name}.{table}"]

  result = subprocess.run(cmd, capture_output=True, text=True)
  if result.returncode != 0:
    raise RuntimeError(f"pg_dump failed for schema {schema_name!r}: {result.stderr.strip()}")

  output = _clean_pg_dump_output(result.stdout)
  if flags == O_LST:
    return output
  elif flags == O_STR:
    return "\n\n".join(output)


def _clean_pg_dump_output(dump: str) -> list:
  dump = re.sub(r"^\\restrict.*$", "", dump, flags=re.MULTILINE)
  dump = re.sub(r"^\\unrestrict.*$", "", dump, flags=re.MULTILINE)
  
  sql_expr = exp.transpile(dump, read="postgres", write="postgres", comments=False)
  new_sql_expr = []
  for expr in sql_expr:
    try:
      expr = exp.parse_one(expr)
      if isinstance(expr, exp.expressions.ddl.Alter):
        new_sql_expr.append(expr.sql() + ";")
      elif (isinstance(expr, exp.expressions.ddl.Create) and expr.kind == "TABLE"):
        new_sql_expr.append(expr.sql() + ";")
    except exp.errors.ParseError:
      continue

  return new_sql_expr
  


def get_table_schema(db_url: str, schema_name: str, tables: list[str]) -> str:
  """Describe the given tables (columns, types, constraints, indexes) as DDL,
  via a selective `pg_dump --schema-only`."""
  return fetch_schema_ddl(db_url, schema_name, tables)


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


# Runs EXPLAIN (ANALYZE, FORMAT JSON): executes the query once and returns the
# plan dict, which carries both the planner's cost estimate ("Total Cost") and
# the measured actual runtime ("Execution Time").
def get_query_plan_analyze(conn_or_cur, query: str) -> dict:
  if hasattr(conn_or_cur, "cursor"):
    with conn_or_cur.cursor() as cur:
      return _query_plan_analyze_from_cursor(cur, query)
  return _query_plan_analyze_from_cursor(conn_or_cur, query)

def _query_plan_analyze_from_cursor(cur, query: str) -> dict:
  cur.execute(f"EXPLAIN (ANALYZE, FORMAT JSON) {query}")
  return cur.fetchone()[0][0]


# Runs query
def run_query(conn_or_cur, query: str) -> str:
  if hasattr(conn_or_cur, "cursor"):
    with conn_or_cur.cursor() as cur:
      return _run_query_from_cursor(cur, query)
  return _run_query_from_cursor(conn_or_cur, query)

def run_query(cur, query: str):
  cur.execute(query)
  return cur.fetchall()
