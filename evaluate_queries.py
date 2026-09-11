"""Evaluate migrated queries: planner cost, measured runtime, and correctness.

Every *generation method* is a different way of producing Q' (queries against
D') from Q (queries against D) -- the deterministic CTE-inlining rewrite of
`generate_raw_queries.py`, the LLM migrations of `generate_baselines.py`, the
rewrites of `generate_optim_queries.py`, and whatever comes next. They all
write the same artifact shape, `{"queries": [{"id": ..., "query": ...}]}` keyed
by `queries.json`'s ids, so they can all be evaluated by the same code.

A method is therefore identified by nothing more than its file name: method
`<name>` reads `test_dbs/db<N>/<name>_queries.json` and writes
`test_dbs/db<N>/eval_<name>_queries.json`. Adding a generation method needs no
change here -- `--method <name>` picks it up as soon as its file exists, and
`--all-methods` evaluates every method present. `METHOD_OVERRIDES` records only
the file names that predate this convention.

For each query, both sides are measured with `EXPLAIN ANALYZE`: the original
against D (`GENERATED_SCHEMA`) and the method's migration against D'
(`SOURCE_SCHEMA`). The `d`/`d_prime`/`ratio` shape of the output is the same for
every method, which is what lets `tabulate_results.py` compare them head to
head. Queries that cannot be evaluated are tagged with an `error` field and
kept in place rather than dropped, so ids stay aligned across methods.
"""

import argparse
import glob
import json
import os

import psycopg
from dotenv import load_dotenv

from db_tools import O_LST, fetch_schema_ddl, get_query_plan_analyze
from db_tools.correctness import Equivalence, rate_equivalence

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
GENERATED_SCHEMA = os.getenv("GENERATED_SCHEMA", "query_migr_generated")
SOURCE_SCHEMA = os.getenv("SOURCE_SCHEMA", "public")

DEFAULT_METHOD = "raw"
QUERIES_SUFFIX = "_queries.json"
EVAL_PREFIX = "eval_"

# Methods whose file names don't follow the convention. `raw` predates
# per-method evaluation files and keeps writing `eval_queries.json` so existing
# artifacts (and tabulate_results.py's default baseline) stay valid.
METHOD_OVERRIDES = {
  "raw": ("raw_queries.json", "eval_queries.json"),
}

if not DB_URL:
  raise RuntimeError("Missing required environment variable: DATABASE_URL")


def method_paths(db_dir: str, method: str) -> tuple[str, str]:
  """(migrated queries file, evaluation output file) for one method."""
  queries_file, eval_file = METHOD_OVERRIDES.get(
    method, (f"{method}{QUERIES_SUFFIX}", f"{EVAL_PREFIX}{method}{QUERIES_SUFFIX}")
  )
  return os.path.join(db_dir, queries_file), os.path.join(db_dir, eval_file)


def discover_methods(db_dir: str) -> list[str]:
  """Every generation method with an artifact in this test case. Evaluation
  outputs are skipped so re-running with --all-methods doesn't try to evaluate
  its own results."""
  overrides_by_file = {f: m for m, (f, _) in METHOD_OVERRIDES.items()}
  methods = set()

  for path in glob.glob(os.path.join(db_dir, f"*{QUERIES_SUFFIX}")):
    name = os.path.basename(path)
    if name.startswith(EVAL_PREFIX):
      continue
    methods.add(overrides_by_file.get(name, name[: -len(QUERIES_SUFFIX)]))

  return sorted(methods)


def split_statements(sql: str) -> list[str]:
  return [f"{s.strip()};" for s in sql.split(";") if s.strip()]


def measure(cur, query: str, search_path: str) -> dict:
  """Runs the query once via EXPLAIN ANALYZE and returns its planner cost and
  measured runtime."""
  cur.execute(f"SET search_path TO {search_path};")
  plan = get_query_plan_analyze(cur, query)
  return {
    "cost": plan["Plan"]["Total Cost"],
    "runtime_ms": plan["Execution Time"],
  }


def ratio(d_value, d_prime_value):
  return (d_value / d_prime_value) if d_prime_value else None


def evaluate_method(
  cur, method: str, src_queries: list[dict], migrated: list[dict], schema_stmts: list[str]
) -> list[dict]:
  """Measure and rate every query of one generation method, pairing each
  original query with the migration carrying the same id."""
  migrated_by_id = {q.get("id"): q for q in migrated}
  results = []

  for q in src_queries:
    qid = q.get("id", "?")

    if "error" in q:
      print(f"[{method}][{qid}] Skipping (already has error): {q['error']}")
      results.append(q)
      continue

    migrated_q = migrated_by_id.get(qid)
    if migrated_q is None:
      print(f"[{method}][{qid}] Skipping: no matching migrated query")
      results.append({**q, "error": "Could not evaluate: no matching migrated query"})
      continue
    if "error" in migrated_q:
      print(f"[{method}][{qid}] Skipping: migrated query has error: {migrated_q['error']}")
      results.append({
        **q,
        "error": f"Could not evaluate: migrated query has error: {migrated_q['error']}",
      })
      continue

    query, migrated_query = q["query"], migrated_q["query"]
    print(f"[{method}][{qid}] Evaluating...")
    record = {**q, "method": method, "migrated_query": migrated_query}

    try:
      d_stats = measure(cur, query, f"{GENERATED_SCHEMA}, {SOURCE_SCHEMA}")
      dp_stats = measure(cur, migrated_query, SOURCE_SCHEMA)
    except Exception as e:
      print(f"[{method}][{qid}] Failed to measure cost/runtime: {e}")
      results.append({**record, "error": f"Failed to measure cost/runtime: {e}"})
      continue

    try:
      cur.execute(f"SET search_path TO {GENERATED_SCHEMA}, {SOURCE_SCHEMA};")
      equivalence = rate_equivalence(cur, query, migrated_query, schema_stmts)
    except Exception as e:
      print(f"[{method}][{qid}] Equivalence check failed, marking UNK: {e}")
      equivalence = Equivalence.UNK

    record["cost"] = {
      "d": d_stats["cost"],
      "d_prime": dp_stats["cost"],
      "ratio": ratio(d_stats["cost"], dp_stats["cost"]),
    }
    record["runtime_ms"] = {
      "d": d_stats["runtime_ms"],
      "d_prime": dp_stats["runtime_ms"],
      "ratio": ratio(d_stats["runtime_ms"], dp_stats["runtime_ms"]),
    }
    record["equivalence"] = equivalence.name

    print(f"[{method}][{qid}] cost={record['cost']} runtime_ms={record['runtime_ms']} "
          f"equivalence={equivalence.name}")
    results.append(record)

  return results


def main() -> None:
  parser = argparse.ArgumentParser(
    description="Evaluate each generation method's migrated queries for cost, "
                "runtime and correctness."
  )
  parser.add_argument("--db", type=int, default=1, metavar="N")
  parser.add_argument(
    "--method", action="append", metavar="NAME",
    help=f"generation method to evaluate, i.e. the file <NAME>{QUERIES_SUFFIX}; "
         f"repeatable (default: {DEFAULT_METHOD})",
  )
  parser.add_argument(
    "--all-methods", action="store_true",
    help="evaluate every generation method with an artifact in this test case",
  )
  args = parser.parse_args()

  db_dir = os.path.join("test_dbs", f"db{args.db}")
  db_path = os.path.join(db_dir, "db.json")
  queries_path = os.path.join(db_dir, "queries.json")

  for path in (db_path, queries_path):
    if not os.path.exists(path):
      raise FileNotFoundError(
        f"Could not find {path!r}. Run generate_db.py, generate_query.py and "
        "instantiate.py first."
      )

  available = discover_methods(db_dir)
  if args.all_methods:
    methods = available
    if args.method:
      parser.error("--all-methods and --method are mutually exclusive")
  else:
    methods = sorted(set(args.method or [DEFAULT_METHOD]))

  if not methods:
    raise FileNotFoundError(
      f"No generation method artifacts (*{QUERIES_SUFFIX}) in {db_dir!r}. Run "
      "generate_raw_queries.py (or another generation script) first."
    )

  for method in methods:
    queries_file, _ = method_paths(db_dir, method)
    if not os.path.exists(queries_file):
      raise FileNotFoundError(
        f"Could not find {queries_file!r} for method {method!r}. "
        f"Available in {db_dir!r}: {', '.join(available) or 'none'}."
      )

  with open(db_path) as f:
    db_data = json.load(f)
  with open(queries_path) as f:
    q_data = json.load(f)

  # Combined schema (D + D') for the sqlsolver-based logical equivalence check.
  # Shared by every method, so it is fetched once.
  schema_stmts = (
    split_statements(db_data["target_database_schema"])
    + fetch_schema_ddl(DB_URL, SOURCE_SCHEMA, flags=O_LST)
  )

  with psycopg.connect(DB_URL, autocommit=True) as conn:
    with conn.cursor() as cur:
      # LLM-generated queries can be pathologically expensive; cap runtime so
      # one bad query can't hang evaluation indefinitely (same policy as
      # instantiate.py).
      cur.execute("SET statement_timeout = '60s';")

      for method in methods:
        queries_file, output_path = method_paths(db_dir, method)
        with open(queries_file) as f:
          migrated = json.load(f)["queries"]

        results = evaluate_method(cur, method, q_data["queries"], migrated, schema_stmts)

        with open(output_path, "w") as f:
          json.dump({"queries": results}, f, indent=2)

        evaluated = sum(1 for r in results if "error" not in r)
        print(f"[{method}] Wrote {output_path} ({evaluated}/{len(results)} evaluated)")

  print("Done.")


if __name__ == "__main__":
  main()
