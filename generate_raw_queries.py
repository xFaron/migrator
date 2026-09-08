import argparse
import json
import os

import sqlglot
from dotenv import load_dotenv
from sqlglot import exp

load_dotenv()


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

  raw_queries = []

  for q in q_data["queries"]:
    qid = q.get("id", "?")

    if "error" in q:
      print(f"[{qid}] Skipping (already has error): {q['error']}")
      raw_queries.append(q)
      continue

    try:
      raw_query = build_raw_query(q["query"], generation_query_by_table)
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
