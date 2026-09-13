import argparse
import json
import os
import re

import psycopg
import sqlglot as exp
from dotenv import load_dotenv

from db_tools import fetch_schema_ddl, get_table_samples
from llm_tools import *

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
SOURCE_SCHEMA = os.getenv("SOURCE_SCHEMA", "public")
GENERATED_SCHEMA = os.getenv("GENERATED_SCHEMA", "query_migr_generated")
BASELINE1_PROMPT_PATH = os.getenv("BASELINE1_PROMPT_PATH", "prompts/baseline1_prompt.md")
BASELINE2_PROMPT_PATH = os.getenv("BASELINE2_PROMPT_PATH", "prompts/baseline2_prompt.md")

PROMPT_PATHS = {1: BASELINE1_PROMPT_PATH, 2: BASELINE2_PROMPT_PATH}

if not DB_URL:
  raise RuntimeError("Missing required environment variable: DATABASE_URL")


def extract_json(content: str) -> dict:
  fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
  raw = fenced[-1] if fenced else content
  return json.loads(raw, strict=False)


def get_schema_tables(conn, schema: str) -> list[str]:
  with conn.cursor() as cur:
    cur.execute(
      "SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_type = 'BASE TABLE'",
      (schema,),
    )
    return [f"{schema}.{row[0]}" for row in cur.fetchall()]


def build_prompt(
  template_path: str,
  source_schema: str,
  target_schema: str,
  src_queries: list[dict],
  table_samples: dict,
  table_generation_queries: list[dict] | None = None,
) -> str:
  with open(template_path) as f:
    template = f.read()

  prompt = (
    template
    .replace("{SOURCE_SCHEMA}", source_schema)
    .replace("{TARGET_SCHEMA}", target_schema)
    .replace("{SRC_QUERIES}", json.dumps(src_queries, indent=2))
    .replace("{TABLE_SAMPLES}", json.dumps(table_samples, indent=2, default=str))
  )
  if table_generation_queries is not None:
    prompt = prompt.replace(
      "{TABLE_GENERATION_QUERIES}", json.dumps(table_generation_queries, indent=2)
    )
  return prompt


def merge_baseline(baseline: int, src_queries: list[dict], migrated: list[dict]) -> None:
  """Writes each migrated query into its matching src_queries entry in place, as
  baseline_<N>_query (or error if the model didn't return one)."""
  query_key = f"baseline_{baseline}_query"

  migrated_by_id = {}
  for q in migrated:
    if isinstance(q, dict) and q.get("query"):
      migrated_by_id[q.get("id")] = q["query"]

  for q in src_queries:
    qid = q.get("id")
    if "error" in q:
      print(f"[{qid}] Skipping (already has error): {q['error']}")
      continue

    migrated_query = migrated_by_id.get(qid)
    if not migrated_query:
      print(f"[{qid}] Model returned no migrated query")
      q["error"] = "Model returned no migrated query"
      continue

    print(f"[{qid}] OK")
    q[query_key] = migrated_query

  extra = set(migrated_by_id) - {q.get("id") for q in src_queries}
  if extra:
    print(f"Ignoring {len(extra)} migrated quer(y/ies) with unknown id(s): {sorted(map(str, extra))}")


def run_baseline(
  baseline: int,
  db_dir: str,
  source_schema: str,
  target_schema: str,
  src_queries: list[dict],
  table_samples: dict,
  table_generation_queries: list[dict],
) -> None:
  fallback_path = os.path.join(db_dir, f"baseline{baseline}_queries.raw.txt")

  prompt = build_prompt(
    PROMPT_PATHS[baseline],
    source_schema,
    target_schema,
    # Only the queries the model is actually asked to migrate; already-failed
    # ones are skipped by merge_baseline().
    [{"id": q.get("id"), "query": q["query"]} for q in src_queries if "error" not in q],
    table_samples,
    table_generation_queries if baseline == 2 else None,
  )

  print(f"[baseline {baseline}] Calling LLM...")
  message = query_model(prompt)
  content = message.get("content") or ""

  error = None
  try:
    response = extract_json(content)
    migrated = response.get("queries", [])
  except json.JSONDecodeError as e:
    error = e
    raise RuntimeError(
      f"Model did not return valid JSON. Raw response saved to {fallback_path!r} for inspection."
    )
  finally:
    with open(fallback_path, "w") as f:
      f.write(content)
      f.write(f"\n\n\nERROR: {error}")

  merge_baseline(baseline, src_queries, migrated)


def main() -> None:
  parser = argparse.ArgumentParser(
    description="Generate LLM baselines that migrate queries from D to D'."
  )
  parser.add_argument("--db", type=int, default=1, metavar="N")
  parser.add_argument(
    "--baseline", type=int, choices=(1, 2), action="append", metavar="B",
    help="which baseline to run; repeatable (default: both)",
  )
  args = parser.parse_args()

  baselines = sorted(set(args.baseline or (1, 2)))

  db_dir = os.path.join("test_dbs", f"db{args.db}")
  db_path = os.path.join(db_dir, "db.json")
  queries_path = os.path.join(db_dir, "queries.json")

  for path in (db_path, queries_path):
    if not os.path.exists(path):
      raise FileNotFoundError(
        f"Could not find {path!r}. Run generate_db.py and generate_query.py first."
      )

  with open(db_path) as f:
    db_data = json.load(f)
  with open(queries_path) as f:
    q_data = json.load(f)

  source_schema = db_data["target_database_schema"]
  try:
    target_schema = fetch_schema_ddl(DB_URL, SOURCE_SCHEMA)
  except Exception as e:
    print(f"Could not dump {SOURCE_SCHEMA!r} ({e}); falling back to db.json's copy.")
    target_schema = db_data["source_database_schema"]

  src_queries = q_data["queries"]
  table_generation_queries = db_data["table_generation_queries"]

  with psycopg.connect(DB_URL, autocommit=True) as conn:
    tables = get_schema_tables(conn, SOURCE_SCHEMA)
    table_samples = get_table_samples(conn, tables)

  for baseline in baselines:
    run_baseline(
      baseline, db_dir, source_schema, target_schema, src_queries, table_samples, table_generation_queries
    )
    with open(queries_path, "w") as f:
      json.dump(q_data, f, indent=2)

  print("Done.")


if __name__ == "__main__":
  main()
