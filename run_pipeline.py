"""
run_pipeline.py [--start N --end N | --dbs N [N ...]] [--k K] [--dry-run]

Runs the full generation pipeline for each given db number, sequentially.
"""

import argparse
import os
import subprocess
import sys

from dotenv import load_dotenv

load_dotenv()

PYTHON = sys.executable

def default_k() -> int:
  return int(os.getenv("DEFAULT_K", "10"))

def pipeline_steps(db_num: int, k: int) -> list[list[str]]:
  db_dir = os.path.join("test_dbs", f"db{db_num}")
  db_json = os.path.join(db_dir, "db.json")
  queries_json = os.path.join(db_dir, "queries.json")

  return [
    [PYTHON, "generate_db.py", "--db", str(db_num)],
    [PYTHON, "generate_query.py", "--db", str(db_num), "--k", str(k)],
    [PYTHON, "instantiate.py", f"test_dbs/db{db_num}/db.json", f"test_dbs/db{db_num}/queries.json"],
    [PYTHON, "generate_raw_queries.py", "--db", str(db_num)],
    [PYTHON, "generate_baselines.py", "--db", str(db_num)],
    [PYTHON, "generate_optim_queries.py", "--db", str(db_num)],
    [PYTHON, "evaluate_queries.py", "--db", str(db_num)],
  ]


def run_db_pipeline(db_num: int, k: int, dry_run: bool) -> bool:
  """Runs all steps for one db number. Returns True on success."""
  prefix = f"[db{db_num}] "

  for cmd in pipeline_steps(db_num, k):
    print(f"{prefix}running: {' '.join(cmd)}")
    if dry_run:
      continue

    result = subprocess.run(cmd)
    if result.returncode != 0:
      print(f"{prefix}[FAILED] {os.path.basename(cmd[1])} exited with code "
            f"{result.returncode} - skipping remaining steps for this db.", file=sys.stderr)
      return False

  print(f"{prefix}Pipeline complete.")
  return True


def resolve_db_numbers(args: argparse.Namespace) -> list[int]:
  if args.dbs:
    return list(args.dbs)
  return list(range(args.start, args.end + 1))


def main() -> None:
  parser = argparse.ArgumentParser(
    description="Run the query-migration generation pipeline sequentially across one or more db numbers."
  )
  parser.add_argument("--start", type=int, default=1, metavar="N",
                       help="first db number (default: 1); ignored if --dbs is given")
  parser.add_argument("--end", type=int, default=1, metavar="N",
                       help="last db number, inclusive (default: 1); ignored if --dbs is given")
  parser.add_argument("--dbs", type=int, nargs="+", metavar="N",
                       help="explicit list of db numbers to run instead of a --start/--end range")
  parser.add_argument("--k", type=int, default=default_k(), metavar="K",
                       help="value passed as generate_query.py's --k (default: DEFAULT_K env var, "
                            "falling back to 10)")
  parser.add_argument("--dry-run", action="store_true",
                       help="print each stage's command instead of running it")
  args = parser.parse_args()

  db_numbers = resolve_db_numbers(args)

  failed = [db_num for db_num in db_numbers if not run_db_pipeline(db_num, args.k, args.dry_run)]

  if failed:
    print(f"==> Done. {len(failed)} run(s) failed: {failed}", file=sys.stderr)
    sys.exit(1)
  else:
    print(f"==> Done. All {len(db_numbers)} run(s) succeeded.")


if __name__ == "__main__":
  main()
