import json as _json
import os
import re
import subprocess
import sqlglot as exp
import logging
from tenacity import retry, stop_after_attempt, wait_exponential
import time
from collections import deque
from functools import wraps

logging.getLogger("sqlglot").setLevel(logging.ERROR)

O_LST = 1 # Output list
O_STR = 0 # Output str

# Variables renamed by the source/target naming refactor. A .env that still sets
# one of these would otherwise silently fall back to the new variable's default
# and point the pipeline at the wrong Postgres schema, so every entrypoint calls
# check_env() after load_dotenv() to fail loudly instead.
RENAMED_ENV_VARS = {
  "SOURCE_SCHEMA": "TARGET_PG_SCHEMA",
  "GENERATED_SCHEMA": "SOURCE_PG_SCHEMA",
  "BASELINE1_PROMPT_PATH": "METHOD1_PROMPT_PATH",
  "BASELINE2_PROMPT_PATH": "METHOD2_PROMPT_PATH",
  "OPTIM_PROMPT_PATH": None,
}


def check_env() -> None:
  problems = []
  for old, new in RENAMED_ENV_VARS.items():
    if os.getenv(old) is None:
      continue
    problems.append(
      f"  {old} was removed; use {new} instead." if new
      else f"  {old} was removed (the optim method no longer exists); delete it."
    )
  if problems:
    raise RuntimeError(
      "Your environment still uses pre-refactor variable names:\n"
      + "\n".join(problems)
      + "\nUpdate .env (see .env.example)."
    )

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
      expr = exp.parse_one(expr, dialect="postgres")
      if isinstance(expr, exp.expressions.ddl.Alter):
        new_sql_expr.append(expr.sql(dialect="postgres") + ";")
      elif (isinstance(expr, exp.expressions.ddl.Create) and expr.kind == "TABLE"):
        new_sql_expr.append(expr.sql(dialect="postgres") + ";")
    except exp.errors.ParseError:
      continue

  return new_sql_expr
  

def strip_schema_qualifiers(query: str, dialect: str = "postgres") -> str:
  """Remove schema/catalog qualifiers from table references (e.g. `public.lineitem` -> `lineitem`)."""
  parsed = exp.parse_one(query, dialect=dialect)
  for table in parsed.find_all(exp.exp.Table):
    table.set("db", None)
    table.set("catalog", None)
  return parsed.sql(dialect=dialect)


def extract_tables(query: str) -> list[str]:
  try:
    parsed = exp.parse_one(query, dialect="postgres")
    cte_names = {cte.alias for cte in parsed.find_all(exp.exp.CTE)}
    return list({
      node.name for node in parsed.walk()
      if isinstance(node, exp.exp.Table) and node.name and node.name not in cte_names
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


# Cache drop methods
def rate_limit(count: int, interval: float):
  calls = deque()
  buffer = 0.01

  def decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
      now = time.monotonic()
      
      while calls and now - calls[0] >= interval:
        calls.popleft()

      if len(calls) >= count:
        wait = now - calls[0] + buffer
        time.sleep(wait)

        while calls and now - calls[0] >= interval:
          calls.popleft()

      calls.append(time.monotonic())
      return func(*args, **kwargs)

    return wrapper

  return decorator
      

def clear_os_page_cache():
  # Asks linux to drop page caches and inode caches. Requires root while running the eval script.
  try:
    with open("/proc/sys/vm/drop_caches", "w") as f:
      f.write("3\n")
  except OSError as e:
    raise RuntimeError(f"Unable to clear os page cache: {e}")

@retry(stop=stop_after_attempt(20), wait=wait_exponential(multiplier=1, min=2, max=30))
@rate_limit(count=5, interval=10)
def stop_db():
  cmd = ["systemctl", "stop", "postgresql"]
  result = subprocess.run(cmd, capture_output=True, text=True)
  if (result.returncode != 0):
    raise RuntimeError(f"Unable to stop postgres: {result.stdout}")

@retry(stop=stop_after_attempt(20), wait=wait_exponential(multiplier=1, min=2, max=30))
@rate_limit(count=5, interval=10)
def start_db():
  cmd = ["systemctl", "start", "postgresql"]
  result = subprocess.run(cmd, capture_output=True, text=True)
  if (result.returncode != 0):
    raise RuntimeError(f"Unable to start postgres: {result.stdout}")

  # `systemctl start` can return before the postmaster is actually accepting
  # connections, so callers that connect right after this returns can race it.
  for _ in range(30):
    if subprocess.run(["pg_isready"], capture_output=True).returncode == 0:
      return
    time.sleep(1)
  raise RuntimeError("postgres did not become ready to accept connections after start")
