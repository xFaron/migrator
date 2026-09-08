import argparse
import json
import os

import sqlglot
from dotenv import load_dotenv
from sqlglot import exp

load_dotenv()


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


def build_raw_query(query: str, generation_query_by_table: dict, columns_by_table: dict) -> str:
  expr = sqlglot.parse_one(query, dialect="postgres")

  with_clause = expr.args.get("with_")

  # Table nodes may be schema-qualified (e.g. query_migr_generated.foo), since
  # generate_query.py prompts the LLM with schema-qualified pg_dump DDL.
  # Match on the unqualified name so those are still recognized.
  tables = {
    node.name for node in expr.walk()
    if isinstance(node, exp.Table) and node.name in generation_query_by_table
  }

  for i, table in enumerate(tables):
    # table_generation_queries' SELECTs are unaliased (they're only ever run
    # as `INSERT INTO target_table SELECT ...`, matched positionally), so
    # inlining them as a CTE without an explicit column list would leave
    # Postgres-invented names (?column?, sum, max, ...) instead of the real
    # target table's column names that the rest of the query references.
    alias = f"{table}({', '.join(columns_by_table[table])})" if table in columns_by_table else table
    expr = expr.with_(alias, as_=generation_query_by_table[table], append=(i != 0))

  if with_clause:
    for cte in with_clause.expressions:
      expr = expr.with_(cte.alias, as_=cte.this)

  # expr.with_() copies the tree by default, so any node mutation must happen
  # on the final tree, after ALL with_() calls (including restoring the
  # original CTEs above, whose bodies may themselves reference a qualified
  # target table). Strip schema qualifiers from matching Table nodes so they
  # resolve to the unqualified CTEs just added, instead of the real,
  # schema-qualified target table.
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
  columns_by_table = extract_table_columns(db_data["target_database_schema"])

  raw_queries = []

  for q in q_data["queries"]:
    qid = q.get("id", "?")

    if "error" in q:
      print(f"[{qid}] Skipping (already has error): {q['error']}")
      raw_queries.append(q)
      continue

    try:
      raw_query = build_raw_query(q["query"], generation_query_by_table, columns_by_table)
    except Exception as e:
      print(f"[{qid}] Failed to transform query: {e}")
      raw_queries.append({**q, "error": f"Failed to transform query: {e}"})
      continue

    print(f"[{qid}] OK")
    raw_queries.append({**q, "query": raw_query})

  with open(output_path, "w") as f:
    json.dump({"queries": raw_queries}, f, indent=2)

  print("Done.")


if __name__ == "__main__":
  main()
