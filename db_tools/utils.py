import json as _json
import re
import subprocess
import sqlglot as exp
import logging

logging.getLogger("sqlglot").setLevel(logging.ERROR)

O_LST = 1 # Output list
O_STR = 0 # Output str

def fetch_schema_ddl(db_url: str, schema_name: str, tables: list[str] | None = None, flags: int = O_STR) -> str:
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
  

def extract_tables(query: str) -> list[str]:
  try:
    parsed = sqlglot.parse_one(query, dialect="postgres")
    cte_names = {cte.alias for cte in parsed.find_all(exp.CTE)}
    return list({
      node.name for node in parsed.walk()
      if isinstance(node, exp.Table) and node.name and node.name not in cte_names
    })
  except Exception:
    return []


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


def get_query_plan(conn_or_cur, query: str, analyze: bool = True, json: bool = True) -> dict | str:
  if hasattr(conn_or_cur, "cursor"):
    with conn_or_cur.cursor() as cur:
      return _query_plan_from_cursor(cur, query, analyze, json)
  return _query_plan_from_cursor(conn_or_cur, query, analyze, json)

def _query_plan_from_cursor(cur, query: str, analyze: bool = True, json: bool = True) -> dict | str:
  options = "ANALYZE, FORMAT JSON" if analyze and json else "FORMAT JSON" if json else "ANALYZE" if analyze else ""
  if not json:
    cur.execute(f"EXPLAIN ({options}) {query}" if options else f"EXPLAIN {query}")
    return "\n".join(row[0] for row in cur.fetchall())
  cur.execute(f"EXPLAIN ({options}) {query}")
  plan = cur.fetchone()[0]
  return plan[0] if analyze else _json.dumps(plan, indent=2)


# Runs query
def run_query(conn_or_cur, query: str):
  if hasattr(conn_or_cur, "cursor"):
    with conn_or_cur.cursor() as cur:
      return _run_query_from_cursor(cur, query)
  return _run_query_from_cursor(conn_or_cur, query)

def _run_query_from_cursor(cur, query: str):
  cur.execute(query)
  return cur.fetchall()
