import argparse
import json
import os

import psycopg
from dotenv import load_dotenv
from tqdm import tqdm

from db_tools import (
  O_LST,
  clear_os_page_cache,
  fetch_schema_ddl,
  get_query_plan,
  start_db,
  stop_db,
)
from db_tools.correctness import Equivalence, rate_equivalence

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
SOURCE_SCHEMA = os.getenv("SOURCE_SCHEMA", "public")
N = 5  # number of runs per query: 1 cold (post cache-clear) + (N - 1) hot, hot runtime is their average

if not DB_URL:
  raise RuntimeError("Missing required environment variable: DATABASE_URL")


def measure(query: str, search_path: str) -> tuple[float, float, float]:
  """Clears the OS page cache and restarts postgres, then measures one cold run
  followed by (N - 1) hot runs of `query`. Returns (cost, cold_runtime, hot_runtime)."""
  stop_db()
  clear_os_page_cache()
  start_db()

  with psycopg.connect(DB_URL, autocommit=True) as conn:
    with conn.cursor() as cur:
      cur.execute("SET statement_timeout = '120s';")
      cur.execute(f"SET search_path TO {search_path};")

      cold_plan = get_query_plan(cur, query)
      cost = cold_plan["Plan"]["Total Cost"]
      cold_runtime = cold_plan["Execution Time"]

      hot_runtimes = [get_query_plan(cur, query)["Execution Time"] for _ in range(N - 1)]
      hot_runtime = sum(hot_runtimes) / len(hot_runtimes) if hot_runtimes else cold_runtime

  return cost, cold_runtime, hot_runtime


def main() -> None:
  if os.geteuid() != 0:
    print("Usage requires sudo privileges for cold cache measurement")
    return

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

  print("Beginning eval...")
  for q in tqdm(q_data["queries"]):
    qid = q.get("id", "?")

    if baseline not in q:
      print(f"[{qid}] Skipping: no {baseline}")
      continue

    try:
      baseline_cost, baseline_cold_runtime, baseline_hot_runtime = measure(q[baseline], SOURCE_SCHEMA)
    except Exception as e:
      print(f"[{qid}] Failed to measure {baseline}: {e}")
      q["error"] = f"Failed to measure {baseline}: {e}"
      continue

    analysis = {
      baseline: {
        "cost": baseline_cost,
        "cold_runtime": baseline_cold_runtime,
        "hot_runtime": baseline_hot_runtime,
        "relative_cost": 1.0,
        "relative_cold_runtime": 1.0,
        "relative_hot_runtime": 1.0,
        "equivalence": Equivalence.EQ.name,
      },
    }

    for method in methods:
      if method not in q:
        continue

      failed = False
      cost = cold_runtime = hot_runtime = float("inf")
      equivalence = Equivalence.INV

      try:
        cost, cold_runtime, hot_runtime = measure(q[method], SOURCE_SCHEMA)
      except Exception as e:
        print(f"[{qid}] Failed to measure {method}: {e}")
        failed = True

      if not failed:
        try:
          with psycopg.connect(DB_URL, autocommit=True) as conn:
            with conn.cursor() as cur:
              cur.execute(f"SET search_path TO {SOURCE_SCHEMA};")
              equivalence = rate_equivalence(cur, q[method], q[baseline], target_ddl)
        except Exception as e:
          print(f"[{qid}] Equivalence check failed for {method}, marking INV: {e}")
          equivalence = Equivalence.INV

      analysis[method] = {
        "cost": cost,
        "cold_runtime": cold_runtime,
        "hot_runtime": hot_runtime,
        "relative_cost": (cost / baseline_cost) if baseline_cost else None,
        "relative_cold_runtime": (cold_runtime / baseline_cold_runtime) if baseline_cold_runtime else None,
        "relative_hot_runtime": (hot_runtime / baseline_hot_runtime) if baseline_hot_runtime else None,
        "equivalence": equivalence.name,
      }

    q["analysis"] = analysis
    print(f"[{qid}] JSON: \n{json.dumps(analysis, indent=2)}")

  with open(queries_path, "w") as f:
    json.dump(q_data, f, indent=2)

  print("Done.")


if __name__ == "__main__":
  main()
