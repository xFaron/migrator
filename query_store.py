"""Shared load/validate/save for a test case's `db.json` and `queries.json`.

Every pipeline script goes through this module so the on-disk shape is defined in
exactly one place. Files written before the source/target naming refactor are
rejected loudly here rather than being silently misread; run
`scripts/migrate_test_dbs.py` to upgrade them.
"""

import json
import os

# Keys that only ever appear in a pre-refactor file. Their presence is what makes
# legacy detection reliable: a freshly generated queries.json legitimately has
# neither `methods` nor `method_gen` yet (no method has run), so absence proves
# nothing while presence of any of these proves the file is stale.
LEGACY_DB_KEYS = ("target_database_schema", "source_database_schema")
LEGACY_TGQ_KEYS = ("target_table",)
LEGACY_QUERY_KEYS = ("baseline_1_query", "baseline_2_query", "optim_query", "analysis")

MIGRATION_HINT = "Run `python scripts/migrate_test_dbs.py` to upgrade it."


class LegacyFormatError(RuntimeError):
  pass


def db_dir(db: int) -> str:
  return os.path.join("test_dbs", f"db{db}")


def db_path(db: int) -> str:
  return os.path.join(db_dir(db), "db.json")


def queries_path(db: int) -> str:
  return os.path.join(db_dir(db), "queries.json")


def raw_responses_dir(db: int) -> str:
  return os.path.join(db_dir(db), "raw_responses")


def _read_json(path: str, hint: str) -> dict:
  if not os.path.exists(path):
    raise FileNotFoundError(f"Could not find {path!r}. {hint}")
  with open(path) as f:
    return json.load(f)


def validate_db(data: dict, path: str = "db.json") -> dict:
  stale = [k for k in LEGACY_DB_KEYS if k in data]
  for tgq in data.get("table_generation_queries", []):
    stale += [k for k in LEGACY_TGQ_KEYS if k in tgq]
  if stale:
    raise LegacyFormatError(
      f"{path!r} uses pre-refactor keys ({', '.join(sorted(set(stale)))}); "
      f"expected `source_schema`/`target_schema`/`source_table`. {MIGRATION_HINT}"
    )
  for key in ("source_schema", "target_schema"):
    if key not in data:
      raise ValueError(f"{path!r} is missing required key {key!r}.")
  return data


def validate_queries(data: dict, path: str = "queries.json") -> dict:
  if "queries" not in data:
    raise ValueError(f"{path!r} is missing required key 'queries'.")
  stale = sorted({k for q in data["queries"] for k in LEGACY_QUERY_KEYS if k in q})
  if stale:
    raise LegacyFormatError(
      f"{path!r} uses pre-refactor per-query fields ({', '.join(stale)}); "
      f"expected a `method_gen` list. {MIGRATION_HINT}"
    )
  return data


def load_db(db: int, hint: str = "Run generate_db.py first.") -> dict:
  path = db_path(db)
  return validate_db(_read_json(path, hint), path)


def load_queries(db: int, hint: str = "Run generate_query.py first.") -> dict:
  path = queries_path(db)
  return validate_queries(_read_json(path, hint), path)


def save_queries(db: int, data: dict) -> None:
  path = queries_path(db)
  os.makedirs(os.path.dirname(path), exist_ok=True)
  with open(path, "w") as f:
    json.dump(data, f, indent=2)


def save_db(db: int, data: dict) -> None:
  path = db_path(db)
  os.makedirs(os.path.dirname(path), exist_ok=True)
  with open(path, "w") as f:
    json.dump(data, f, indent=2)


def set_methods(data: dict, methods: list[dict]) -> None:
  """Replaces the top-level `methods` block, which is regenerated from the
  registry on every run and describes only the methods that exist today."""
  data["methods"] = methods


def method_entries(q: dict) -> list[dict]:
  return q.setdefault("method_gen", [])


def get_method_entry(q: dict, method_id: str) -> dict | None:
  return next((e for e in q.get("method_gen", []) if e.get("method_id") == method_id), None)


def set_method_entry(q: dict, method_id: str, entry: dict) -> None:
  """Inserts or replaces this query's entry for `method_id`, keeping list order
  stable so a rerun of one method doesn't reshuffle the file."""
  entry = {"method_id": method_id, **{k: v for k, v in entry.items() if k != "method_id"}}
  entries = method_entries(q)
  for i, existing in enumerate(entries):
    if existing.get("method_id") == method_id:
      entries[i] = entry
      return
  entries.append(entry)
