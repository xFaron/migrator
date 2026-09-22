"""One-off upgrade of existing `test_dbs/db<N>/` artifacts to the source/target naming.

This is the only file in the repo allowed to mention the pre-refactor key names:
everywhere else they must simply be gone. Run it once per checkout; it is
idempotent, so a second run touches nothing.

  python scripts/migrate_test_dbs.py [--dbs N ...] [--root test_dbs] [--dry-run]

Note this script deliberately does NOT call `check_env()`: it is the first thing
you run when upgrading a checkout, i.e. before `.env` has been updated, and
aborting on a stale variable name would make the migration unrunnable. It reads
no environment variables at all.
"""

import argparse
import json
import os
import re
import sys
from collections.abc import Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import query_store

DB_KEY_RENAMES = {
  "target_database_schema": "source_schema",  # DDL of D, the source
  "source_database_schema": "target_schema",  # DDL of D', the target
}
TGQ_KEY_RENAMES = {"target_table": "source_table"}

# The two LLM migration baselines became registry methods; the optim step has no
# successor method and is dropped (loudly).
BASELINE_METHODS = {"baseline_1_query": "method_1", "baseline_2_query": "method_2"}
DROPPED_QUERY_KEY = "optim_query"

# `analysis` entries were keyed by the query field they measured.
BASELINE_MEASUREMENTS = ("cost", "cold_runtime", "hot_runtime",
                         "relative_cost", "relative_cold_runtime", "relative_hot_runtime",
                         "equivalence")
# The baseline measures itself, so its relative_* fields are all 1.0 and carry no
# information; only the absolute numbers move onto the query.
RAW_MEASUREMENTS = ("cost", "cold_runtime", "hot_runtime", "equivalence")


def db_dirs(root: str, dbs: list[int] | None) -> list[tuple[int, str]]:
  """Every `db<N>` directory under `root`, numerically ordered."""
  found = []
  for name in os.listdir(root):
    match = re.fullmatch(r"db(\d+)", name)
    if match and os.path.isdir(os.path.join(root, name)):
      found.append((int(match.group(1)), os.path.join(root, name)))
  if dbs is not None:
    wanted = set(dbs)
    missing = wanted - {n for n, _ in found}
    for n in sorted(missing):
      print(f"  db{n}: no such directory under {root!r}")
    found = [(n, p) for n, p in found if n in wanted]
  return sorted(found)


def is_legacy_db(data: dict) -> bool:
  if any(k in data for k in query_store.LEGACY_DB_KEYS):
    return True
  return any(k in tgq for tgq in data.get("table_generation_queries", [])
             for k in query_store.LEGACY_TGQ_KEYS)


def is_legacy_queries(data: dict | list) -> bool:
  if isinstance(data, list):
    return True
  return any(k in q for q in data.get("queries", []) for k in query_store.LEGACY_QUERY_KEYS)


def migrate_db(data: dict) -> dict:
  """Renames db.json's keys, keeping the original field order."""
  out = {DB_KEY_RENAMES.get(k, k): v for k, v in data.items()}
  out["table_generation_queries"] = [
    {TGQ_KEY_RENAMES.get(k, k): v for k, v in tgq.items()}
    for tgq in out.get("table_generation_queries", [])
  ]
  return out


def migrate_query(q: dict) -> tuple[dict, int]:
  """Rewrites one query record; returns it plus how many optim results it lost."""
  analysis = q.get("analysis") or {}
  legacy = set(query_store.LEGACY_QUERY_KEYS)

  out = {k: v for k, v in q.items() if k not in legacy}

  raw = analysis.get("raw_query") or {}
  for field in RAW_MEASUREMENTS:
    if field in raw:
      out[field] = raw[field]

  entries = []
  for legacy_key, method_id in BASELINE_METHODS.items():
    measured = analysis.get(legacy_key) or {}
    if legacy_key not in q and not measured:
      continue
    entry = {"method_id": method_id}
    if legacy_key in q:
      entry["query"] = q[legacy_key]
    for field in BASELINE_MEASUREMENTS:
      if field in measured:
        entry[field] = measured[field]
    entries.append(entry)
  if entries:
    out["method_gen"] = entries

  dropped = 1 if (DROPPED_QUERY_KEY in q or DROPPED_QUERY_KEY in analysis) else 0
  return out, dropped


def migrate_queries(data: dict | list) -> tuple[dict, int]:
  if isinstance(data, list):  # never seen in practice, but cheap to accept
    data = {"queries": data}
  out = dict(data)
  migrated, dropped = [], 0
  for q in data.get("queries", []):
    new_q, lost = migrate_query(q)
    migrated.append(new_q)
    dropped += lost
  out["queries"] = migrated
  return out, dropped


def process(path: str, is_legacy: Callable[[dict], bool],
            migrate: Callable[[dict], tuple[dict, int]],
            validate: Callable[[dict, str], dict], dry_run: bool) -> tuple[bool, int]:
  """Reads, migrates, validates and (unless --dry-run) rewrites one JSON file.

  An already-migrated file is validated but never rewritten, so re-running the
  script changes no bytes. Returns (changed, optim_results_dropped)."""
  if not os.path.exists(path):
    print(f"  {path}: missing, skipped")
    return False, 0

  with open(path) as f:
    original = f.read()
  data = json.loads(original)

  if not is_legacy(data):
    validate(data, path)
    print(f"  {path}: already migrated, unchanged")
    return False, 0

  data, dropped = migrate(data)
  validate(data, path)

  new_text = json.dumps(data, indent=2)
  if new_text == original:
    print(f"  {path}: already migrated, unchanged")
    return False, dropped

  if not os.access(path, os.W_OK):
    raise PermissionError(
      f"{path} is not writable (owned by {_owner(path)}); "
      "re-run this script with sudo, or chown the file back."
    )

  if dry_run:
    print(f"  {path}: would rewrite")
  else:
    with open(path, "w") as f:
      f.write(new_text)
    print(f"  {path}: migrated")
  return True, dropped


def _owner(path: str) -> str:
  try:
    import pwd
    return pwd.getpwuid(os.stat(path).st_uid).pw_name
  except Exception:
    return "another user"


def process_db_dir(path: str, dry_run: bool) -> tuple[int, int]:
  """Returns (files changed, optim results dropped) for one test case."""
  db_changed, _ = process(
    os.path.join(path, "db.json"),
    is_legacy_db, lambda d: (migrate_db(d), 0), query_store.validate_db, dry_run,
  )

  q_file = os.path.join(path, "queries.json")
  q_changed, dropped = process(
    q_file, is_legacy_queries, migrate_queries, query_store.validate_queries, dry_run,
  )
  if dropped:
    print(f"  WARNING: {q_file}: dropped {dropped} `optim_query` result(s); "
          "the optim step has no successor method.")
  return db_changed + q_changed, dropped


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
  parser.add_argument("--dbs", type=int, nargs="+", metavar="N",
                      help="test case numbers to migrate (default: every db<N> found)")
  parser.add_argument("--root", default="test_dbs", metavar="DIR",
                      help="directory holding the db<N> test cases (default: test_dbs)")
  parser.add_argument("--dry-run", action="store_true",
                      help="report what would change without writing anything")
  args = parser.parse_args()

  if not os.path.isdir(args.root):
    raise SystemExit(f"No such directory: {args.root!r}")

  dirs = db_dirs(args.root, args.dbs)
  if not dirs:
    raise SystemExit(f"No db<N> directories found under {args.root!r}.")

  total_changed = 0
  total_dropped = 0
  failed = []
  for num, path in dirs:
    print(f"db{num}:")
    try:
      changed, dropped = process_db_dir(path, args.dry_run)
    except Exception as e:
      print(f"  FAILED: {e}")
      failed.append((num, e))
      continue
    total_changed += changed
    total_dropped += dropped

  verb = "would migrate" if args.dry_run else "migrated"
  if total_changed:
    print(f"\n{verb} {total_changed} file(s) across {len(dirs)} test case(s).")
  elif not failed:
    print(f"\nNothing to do: all {len(dirs)} test case(s) are already migrated.")
  if total_dropped:
    print(f"WARNING: dropped {total_dropped} `optim_query` result(s) in total. "
          "They have no successor method and are not recoverable from the migrated files.")
  if failed:
    print(f"\n{len(failed)} test case(s) could not be migrated: "
          f"{', '.join(f'db{n}' for n, _ in failed)}. Fix the cause and re-run; "
          "the ones that succeeded are already migrated and will be skipped.")
    raise SystemExit(1)


if __name__ == "__main__":
  main()
