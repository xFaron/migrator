import argparse
import json
import os

import psycopg
from dotenv import load_dotenv
from tqdm import tqdm

import query_store
from db_tools import (
  O_LST,
  check_env,
  clear_os_page_cache,
  fetch_schema_ddl,
  get_query_plan,
  start_db,
  stop_db,
)
from db_tools.correctness import Equivalence, rate_equivalence

load_dotenv()
check_env()

DB_URL = os.getenv("DATABASE_URL")
TARGET_PG_SCHEMA = os.getenv("TARGET_PG_SCHEMA", "public")
SOURCE_PG_SCHEMA = os.getenv("SOURCE_PG_SCHEMA", "query_migr_generated")
MEASURE_FAILED = "Failed to measure raw_query"

# `query` (Qsrc) runs on D, whose tables are physically instantiated in
# SOURCE_PG_SCHEMA; everything else runs on D' alone.
SOURCE_SEARCH_PATH = f"{SOURCE_PG_SCHEMA}, {TARGET_PG_SCHEMA}"

# Superseded by the prefixed names below. Written by pre-`source_query_*` runs,
# when `cost` and friends could only have meant raw_query's.
LEGACY_METRIC_KEYS = ("cost", "cold_runtime", "hot_runtime", "equivalence")
N = 5  # number of runs per query: 1 cold (post cache-clear) + (N - 1) hot, hot runtime is their average


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


def check_equivalence(query: str, baseline_query: str, target_ddl: list[str]) -> Equivalence:
  with psycopg.connect(DB_URL, autocommit=True) as conn:
    with conn.cursor() as cur:
      cur.execute(f"SET search_path TO {TARGET_PG_SCHEMA};")
      return rate_equivalence(cur, query, baseline_query, target_ddl)


def relative(value: float, baseline_value: float) -> float | None:
  return (value / baseline_value) if baseline_value else None


def source_db_instantiated() -> bool:
  """True if D is actually present in SOURCE_PG_SCHEMA. Checked once: every
  `measure` call restarts Postgres, so letting each source query fail in turn
  would cost a full restart cycle per query to learn the same thing."""
  with psycopg.connect(DB_URL, autocommit=True) as conn:
    with conn.cursor() as cur:
      cur.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = %s",
        (SOURCE_PG_SCHEMA,),
      )
      return cur.fetchone()[0] > 0


def summarize(q: dict) -> dict:
  """Just what was measured, keyed by method - the SQL itself is dropped so the
  per-query progress line stays readable."""
  metrics = ("cost", "cold_runtime", "hot_runtime", "relative_cost",
             "relative_cold_runtime", "relative_hot_runtime", "equivalence", "error")
  summary = {}
  for prefix in ("source_query", "raw_query"):
    row = {k: q[f"{prefix}_{k}"] for k in metrics if f"{prefix}_{k}" in q}
    if row:
      summary[prefix] = row
  for entry in q.get("method_gen", []):
    summary[entry.get("method_id", "?")] = {k: v for k, v in entry.items()
                                            if k in metrics}
  return summary


def main() -> None:
  parser = argparse.ArgumentParser(
    description="Measure cost/runtime and rate equivalence for every generated method against `raw_query`."
  )
  parser.add_argument("--db", type=int, default=1, metavar="N")
  parser.add_argument("--id", type=int, default=None, metavar="QID",
                       help="Only evaluate the query with this id, to redo one that failed.")
  args = parser.parse_args()

  if os.geteuid() != 0:
    raise SystemExit("Usage requires sudo privileges for cold cache measurement")
  if not DB_URL:
    raise SystemExit("Missing required environment variable: DATABASE_URL")

  q_data = query_store.load_queries(
    args.db,
    hint="Run generate_query.py, instantiate.py and generate_raw_queries.py first.",
  )

  target_ddl = fetch_schema_ddl(DB_URL, TARGET_PG_SCHEMA, flags=O_LST)

  stale = [k for q in q_data["queries"] for k in LEGACY_METRIC_KEYS if k in q]
  if stale:
    for q in q_data["queries"]:
      for key in LEGACY_METRIC_KEYS:
        q.pop(key, None)
    print(f"Dropped {len(stale)} unprefixed measurement field(s) from an earlier run; "
          "they are replaced by the raw_query_* fields below.")

  queries_to_eval = q_data["queries"]
  if args.id is not None:
    queries_to_eval = [q for q in queries_to_eval if q.get("id") == args.id]
    if not queries_to_eval:
      raise SystemExit(f"No query with id {args.id} in test_dbs/db{args.db}/queries.json")

  measure_source = source_db_instantiated()
  if not measure_source:
    print(f"D is not instantiated in {SOURCE_PG_SCHEMA!r}; skipping every source-query "
          "measurement. Run instantiate.py first to measure `query` as well.")

  print("Beginning eval...")
  for q in tqdm(queries_to_eval):
    qid = q.get("id", "?")

    if "raw_query" not in q:
      print(f"[{qid}] Skipping: no raw_query")
      continue
    if "error" in q and not q["error"].startswith(MEASURE_FAILED):
      print(f"[{qid}] Skipping (already has error): {q['error']}")
      continue

    # `raw_query` (Qgt) is the baseline every method is compared against; its own
    # numbers live on the query itself, not in a method entry.
    try:
      baseline_cost, baseline_cold_runtime, baseline_hot_runtime = measure(q["raw_query"], TARGET_PG_SCHEMA)
    except Exception as e:
      print(f"[{qid}] {MEASURE_FAILED}: {e}")
      q["error"] = f"{MEASURE_FAILED}: {e}"
      query_store.save_queries(args.db, q_data)
      continue

    if q.get("error", "").startswith(MEASURE_FAILED):
      del q["error"]  # a previous run's measurement failure, superseded by this one

    q["raw_query_cost"] = baseline_cost
    q["raw_query_cold_runtime"] = baseline_cold_runtime
    q["raw_query_hot_runtime"] = baseline_hot_runtime
    q["raw_query_equivalence"] = Equivalence.EQ.name

    # `query` (Qsrc) on D. Measured for reference only: it is not a migration
    # candidate, so it gets no ratio against the baseline and no equivalence
    # rating - the two run on different databases, and generate_raw_queries.py
    # already verified they return the same rows.
    # Cleared first, so the source_query_* fields are always exactly what this run
    # measured - never a leftover from a run made while D was still instantiated.
    for key in [k for k in q if k.startswith("source_query_")]:
      del q[key]

    if measure_source:
      try:
        source_cost, source_cold_runtime, source_hot_runtime = measure(q["query"], SOURCE_SEARCH_PATH)
      except Exception as e:
        print(f"[{qid}] Failed to measure query: {e}")
        q["source_query_error"] = f"Failed to measure: {e}"
      else:
        q["source_query_cost"] = source_cost
        q["source_query_cold_runtime"] = source_cold_runtime
        q["source_query_hot_runtime"] = source_hot_runtime

    # Iterated generically: whichever methods generate_llm_queries.py produced get
    # measured, with no knowledge here of what any of them mean.
    for entry in list(q.get("method_gen", [])):
      method_id = entry.get("method_id", "?")

      # No `query` means generation failed (the entry holds only an `error`);
      # an entry that has both was measured and failed here, so it is retried.
      if "query" not in entry:
        if "error" in entry:
          print(f"[{qid}] Skipping {method_id}: generation failed earlier")
        continue

      try:
        cost, cold_runtime, hot_runtime = measure(entry["query"], TARGET_PG_SCHEMA)
      except Exception as e:
        print(f"[{qid}] Failed to measure {method_id}: {e}")
        query_store.set_method_entry(q, method_id, {
          "query": entry["query"],
          "error": f"Failed to measure: {e}",
          "equivalence": Equivalence.INV.name,
        })
        continue

      try:
        equivalence = check_equivalence(entry["query"], q["raw_query"], target_ddl)
      except Exception as e:
        print(f"[{qid}] Equivalence check failed for {method_id}, marking INV: {e}")
        equivalence = Equivalence.INV

      query_store.set_method_entry(q, method_id, {
        "query": entry["query"],
        "cost": cost,
        "cold_runtime": cold_runtime,
        "hot_runtime": hot_runtime,
        "relative_cost": relative(cost, baseline_cost),
        "relative_cold_runtime": relative(cold_runtime, baseline_cold_runtime),
        "relative_hot_runtime": relative(hot_runtime, baseline_hot_runtime),
        "equivalence": equivalence.name,
      })

    # Saved per query: this script restarts postgres between every measurement, so a
    # run is long and easily interrupted - whatever finished stays on disk.
    query_store.save_queries(args.db, q_data)
    print(f"[{qid}] JSON: \n{json.dumps(summarize(q), indent=2)}")

  print("Done.")


if __name__ == "__main__":
  main()
