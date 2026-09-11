import argparse
import json
import os

import psycopg
from dotenv import load_dotenv

from db_tools import O_LST, fetch_schema_ddl, get_query_plan
from db_tools.correctness import Equivalence, rate_equivalence

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
SOURCE_SCHEMA = os.getenv("SOURCE_SCHEMA", "public")

if not DB_URL:
  raise RuntimeError("Missing required environment variable: DATABASE_URL")

def measure(cur, query: str, search_path: str) -> tuple[float, float]:
  cur.execute(f"SET search_path TO {search_path};")
  plan = get_query_plan(cur, query)
  return plan["Plan"]["Total Cost"], plan["Execution Time"]


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--db", type=int, default=1, metavar="N")
  args = parser.parse_args()

  db_dir = os.path.join("test_dbs", f"db{args.db}")
  queries_path = os.path.join(db_dir, "queries.json")

  if not os.path.exists(queries_path):
    raise FileNotFoundError(
      f"Could not find {queries_path!r}. Run generate_query.py, instantiate.py "
      "and generate_raw_queries.py first."
    )

  with open(queries_path) as f:
    q_data = json.load(f)

  target_ddl = fetch_schema_ddl(DB_URL, SOURCE_SCHEMA, flags=O_LST)
  baseline = "raw_query"
  methods = ["baseline_1_query", "baseline_2_query", "optim_query"]
  all_methods = [baseline] + methods

  with psycopg.connect(DB_URL, autocommit=True) as conn:
    with conn.cursor() as cur:
      cur.execute("SET statement_timeout = '60s';")

      for q in q_data["queries"]:
        qid = q.get("id", "?")

        if baseline not in q:
          print(f"[{qid}] Skipping: no {baseline}")
          continue

        try:
          baseline_cost, baseline_runtime = measure(cur, q[baseline], SOURCE_SCHEMA)
        except Exception as e:
          print(f"[{qid}] Failed to measure {baseline}: {e}")
          q["eval_error"] = f"Failed to measure {baseline}: {e}"
          continue

        analysis = {
          baseline: {"relative_cost": 1.0, "relative_runtime": 1.0, "equivalence": Equivalence.EQ.name},
        }

        for method in methods:
          if method not in q:
            continue

          try:
            cost, runtime = measure(cur, q[method], SOURCE_SCHEMA)
          except Exception as e:
            print(f"[{qid}] Failed to measure {method}: {e}")
            continue

          try:
            equivalence = rate_equivalence(cur, q[method], q[baseline], target_ddl)
          except Exception as e:
            print(f"[{qid}] Equivalence check failed for {method}, marking UNK: {e}")
            equivalence = Equivalence.UNK

          analysis[method] = {
            "relative_cost": (cost / baseline_cost) if baseline_cost else None,
            "relative_runtime": (runtime / baseline_runtime) if baseline_runtime else None,
            "equivalence": equivalence.name,
          }

        q["analysis"] = analysis
        print(f"[{qid}] {analysis}")

  with open(queries_path, "w") as f:
    json.dump(q_data, f, indent=2)

  print("Done.")


if __name__ == "__main__":
  main()
