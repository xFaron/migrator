import os
import subprocess
import tempfile
from enum import Enum
from typing import List

import psycopg
import sqlglot

from db_tools.utils import *

class Equivalence(Enum):
  INV = 0       # Invalid Queries
  NEQ = 1       # Not equivalent
  ST_EQ = 2     # Statistically equivalent
  DB_EQ = 3     # Equivalent on the whole database
  EQ = 4        # Logically equivalent
  UNK = 5       # Unknown

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
SQL_SOLVER_LIB_PATH = os.path.join(_MODULE_DIR, "sqlsolver")
SQL_SOLVER_BIN_PATH = os.path.join(_MODULE_DIR, "sqlsolver", "sqlsolver-v1.1.0.jar")

def simple_equivalence(curr, query_a: str, query_b: str) -> bool:
  query_a = query_a.strip().rstrip(";")
  query_b = query_b.strip().rstrip(";")
  eqv_query = f"""
  (
    ({query_a}) EXCEPT ALL ({query_b})
  )
  UNION ALL
  (
    ({query_b}) EXCEPT ALL ({query_a})
  )
  LIMIT 1;
  """
  result = run_query(curr, eqv_query)
  return len(result) == 0

def sqlsolver_schema_modifier(schema: List[str]) -> List[str]:
  creates = {}
  order = []
  alters = []

  for stmt in schema:
    parsed = sqlglot.parse_one(stmt, read="postgres")
    if isinstance(parsed, sqlglot.exp.Create) and parsed.kind == "TABLE":
      table_name = parsed.this.this.name
      creates[table_name] = parsed
      order.append(table_name)
    elif isinstance(parsed, sqlglot.exp.Alter):
      alters.append(parsed)

  for alter in alters:
    table_name = alter.this.this.name
    create = creates.get(table_name)
    if create is None:
      raise ValueError(f"ALTER references unknown table {table_name!r}")

    schema_node = create.this
    for action in alter.args.get("actions", []):
      if isinstance(action, sqlglot.exp.AddConstraint):
        for constraint_expr in action.expressions:
          schema_node.append("expressions", constraint_expr)

  new_schema = []
  for table_name in order:
    stmt = creates[table_name].sql(dialect="postgres") + ";"
    # Check if valid: the merged CREATE must still parse cleanly.
    sqlglot.parse_one(stmt, read="postgres")
    new_schema.append(stmt)

  return new_schema

def sqlsolver_logical_equivalence(query_list_a: List[str], query_list_b: List[str], schema: List[str]) -> List[Equivalence]:
  merged_schema = sqlsolver_schema_modifier(schema)

  with tempfile.TemporaryDirectory() as tmp_dir:
    sql1_path = os.path.join(tmp_dir, "sql1.sql")
    sql2_path = os.path.join(tmp_dir, "sql2.sql")
    sch_path = os.path.join(tmp_dir, "sch.sql")
    out_path = os.path.join(tmp_dir, "a.out")

    with open(sql1_path, "w") as f:
      f.write("\n".join(query_list_a))
    with open(sql2_path, "w") as f:
      f.write("\n".join(query_list_b))
    with open(sch_path, "w") as f:
      f.write("\n".join(merged_schema))

    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = f"{SQL_SOLVER_LIB_PATH}:{env.get('LD_LIBRARY_PATH', '')}"

    cmd = [
      "java", "-jar",
      SQL_SOLVER_BIN_PATH,
      "-sql1", sql1_path,
      "-sql2", sql2_path,
      "-schema", sch_path,
      "-output", out_path,
    ]
    subprocess.run(cmd, env=env, check=True, capture_output=True, text=True, timeout=60)

    with open(out_path) as f:
      verdicts = [line.strip() for line in f if line.strip()]

  results = [Equivalence[v] if v in Equivalence.__members__ else Equivalence.UNK for v in verdicts]
  if len(results) == 0:
    return [Equivalence.UNK]
  return results


# Input curr -> Should be able to run both queries properly (expecting schema to exist in curr)
def rate_equivalence(curr, query_a: str, query_b: str, schema: List[str]) -> Equivalence:
  curr_eqv = Equivalence.NEQ
  try:
    # Checking Syntactical correctness
    try:
      get_query_plan(curr, query_a, analyze=False)
      get_query_plan(curr, query_b, analyze=False)
    except psycopg.errors.QueryCanceled:
      curr_eqv = Equivalence.INV
      raise AssertionError

    # Checking logical equivalence
    try:
      curr_eqv = sqlsolver_logical_equivalence([query_a], [query_b], schema)[0]
    except Exception as e:
      # sqlsolver crashing/timing out isn't a verdict on the queries
      # themselves - fall back to a direct result comparison instead of
      # letting the exception propagate and get mistaken for invalidity.
      print(f"sqlsolver failed ({e}); falling back to simple_equivalence")
      curr_eqv = Equivalence.UNK
    if curr_eqv == Equivalence.UNK:
      # Checking query result match equivalence
      if simple_equivalence(curr, query_a, query_b):
        curr_eqv = Equivalence.DB_EQ
      else:
        curr_eqv = Equivalence.NEQ

  except AssertionError:
    pass

  return curr_eqv
