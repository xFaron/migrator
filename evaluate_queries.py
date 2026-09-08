import argparse
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

if not DB_URL:
  raise RuntimeError("Missing required environment variable: DATABASE_URL")


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


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--db", type=int, default=1, metavar="N")
  args = parser.parse_args()

  db_dir = os.path.join("test_dbs", f"db{args.db}")
  db_path = os.path.join(db_dir, "db.json")
  queries_path = os.path.join(db_dir, "queries.json")
  raw_path = os.path.join(db_dir, "raw_queries.json")
  output_path = os.path.join(db_dir, "eval_queries.json")

  for path in (db_path, queries_path, raw_path):
    if not os.path.exists(path):
      raise FileNotFoundError(
        f"Could not find {path!r}. Run generate_db.py, generate_query.py, "
        "instantiate.py and generate_raw_queries.py first."
      )

  with open(db_path) as f:
    db_data = json.load(f)
  with open(queries_path) as f:
    q_data = json.load(f)
  with open(raw_path) as f:
    raw_data = json.load(f)

  raw_by_id = {q.get("id"): q for q in raw_data["queries"]}

  # Combined schema (D + D') for the sqlsolver-based logical equivalence check.
  schema_stmts = (
    split_statements(db_data["target_database_schema"])
    + fetch_schema_ddl(DB_URL, SOURCE_SCHEMA, flags=O_LST)
  )

  results = []

  with psycopg.connect(DB_URL, autocommit=True) as conn:
    with conn.cursor() as cur:
      # LLM-generated queries can be pathologically expensive; cap runtime so
      # one bad query can't hang evaluation indefinitely (same policy as
      # instantiate.py).
      cur.execute("SET statement_timeout = '60s';")

      for q in q_data["queries"]:
        qid = q.get("id", "?")

        if "error" in q:
          print(f"[{qid}] Skipping (already has error): {q['error']}")
          results.append(q)
          continue

        raw_q = raw_by_id.get(qid)
        if raw_q is None:
          print(f"[{qid}] Skipping: no matching raw query")
          results.append({**q, "error": "Could not evaluate: no matching raw query"})
          continue
        if "error" in raw_q:
          print(f"[{qid}] Skipping: raw query has error: {raw_q['error']}")
          results.append({**q, "error": f"Could not evaluate: raw query has error: {raw_q['error']}"})
          continue

        query, raw_query = q["query"], raw_q["query"]
        print(f"[{qid}] Evaluating...")
        record = {**q, "raw_query": raw_query}

        try:
          d_stats = measure(cur, query, f"{GENERATED_SCHEMA}, {SOURCE_SCHEMA}")
          dp_stats = measure(cur, raw_query, SOURCE_SCHEMA)
        except Exception as e:
          print(f"[{qid}] Failed to measure cost/runtime: {e}")
          results.append({**record, "error": f"Failed to measure cost/runtime: {e}"})
          continue

        try:
          cur.execute(f"SET search_path TO {GENERATED_SCHEMA}, {SOURCE_SCHEMA};")
          equivalence = rate_equivalence(cur, query, raw_query, schema_stmts)
        except Exception as e:
          print(f"[{qid}] Equivalence check failed, marking UNK: {e}")
          equivalence = Equivalence.UNK

        record["cost"] = {
          "d": d_stats["cost"],
          "d_prime": dp_stats["cost"],
          "ratio": (d_stats["cost"] / dp_stats["cost"]) if dp_stats["cost"] else None,
        }
        record["runtime_ms"] = {
          "d": d_stats["runtime_ms"],
          "d_prime": dp_stats["runtime_ms"],
          "ratio": (d_stats["runtime_ms"] / dp_stats["runtime_ms"]) if dp_stats["runtime_ms"] else None,
        }
        record["equivalence"] = equivalence.name

        print(f"[{qid}] cost={record['cost']} runtime_ms={record['runtime_ms']} equivalence={equivalence.name}")
        results.append(record)

  with open(output_path, "w") as f:
    json.dump({"queries": results}, f, indent=2)

  print("Done.")


if __name__ == "__main__":
  main()
