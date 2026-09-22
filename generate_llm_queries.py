"""Ask the LLM to migrate each query of D onto D', once per method.

A "method" is one way of asking: it differs only in which inputs it is handed
(see METHODS below). Everything else — one LLM call per (query, method), the
`{"query": "<sql>"}` response contract, the per-pair error handling — is shared,
so adding a method is one registry entry plus one prompt file.
"""

import argparse
import json
import os
import re
from dataclasses import dataclass

import psycopg
import sqlglot
from dotenv import load_dotenv
from sqlglot import exp

import query_store
from db_tools import check_env, extract_tables, fetch_schema_ddl, get_query_plan
from llm_tools import query_model

load_dotenv()
check_env()

DB_URL = os.getenv("DATABASE_URL")
TARGET_PG_SCHEMA = os.getenv("TARGET_PG_SCHEMA", "public")


def method_prompt_path(n: int) -> str:
  """Each method's template, overridable as METHOD<N>_PROMPT_PATH. Derived from
  the method number rather than a constant per method, so adding a method really
  is one registry entry plus one prompt file."""
  return os.getenv(f"METHOD{n}_PROMPT_PATH", f"prompts/method{n}_prompt.md")


# One placeholder per param name; a method's `params` decide both what is
# gathered and what is substituted, so the two can never drift apart.
PLACEHOLDERS = {
  "Ssrc": "{SSRC}",
  "Stgt": "{STGT}",
  "Qsrc": "{QSRC}",
  "Qgt": "{QGT}",
  "Pgt": "{PGT}",
  "f": "{F}",
}


@dataclass
class RunContext:
  """Everything shared by every (query, method) pair of one run: a single
  connection and a single D' DDL dump, both reused rather than re-fetched."""
  db: int
  db_data: dict
  target_ddl: str
  conn: psycopg.Connection


def extract_json(content: str) -> dict:
  fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
  raw = fenced[-1] if fenced else content
  return json.loads(raw, strict=False)


def filter_table_schema(schema_ddl: str, tables: list[str]) -> str:
  """Keeps only the DDL statements that mention one of `tables`."""
  table_set = set(tables)
  statements = []
  for stmt in sqlglot.transpile(schema_ddl, read="postgres"):
    try:
      parsed = sqlglot.parse_one(stmt, dialect="postgres")
    except Exception:
      continue
    if {t.name for t in parsed.find_all(exp.Table)} & table_set:
      statements.append(stmt)
  return "\n\n".join(statements)


def gather_inputs(params: list[str], q: dict, ctx: RunContext) -> dict[str, str]:
  """Returns exactly the inputs named by `params` and nothing else, so a method
  never sees (nor pays for) context it did not ask for."""
  inputs: dict[str, str] = {}
  for param in params:
    if param == "Ssrc":
      inputs[param] = ctx.db_data["source_schema"]
    elif param == "Qsrc":
      inputs[param] = q["query"]
    elif param == "Qgt":
      inputs[param] = q["raw_query"]
    elif param == "Pgt":
      inputs[param] = get_query_plan(ctx.conn, q["raw_query"], analyze=False, json=False)
    elif param == "f":
      inputs[param] = json.dumps(ctx.db_data["table_generation_queries"], indent=2)
    elif param == "Stgt":
      if "Qgt" in params:
        # A method holding Qgt is rewriting a query we already have, so it only
        # needs the DDL of the tables that query actually touches.
        tables = extract_tables(q["raw_query"])
        filtered = filter_table_schema(ctx.target_ddl, tables)
        if not filtered.strip():
          raise ValueError(f"no target DDL matched the tables {tables} of raw_query")
        inputs[param] = filtered
      else:
        # Methods 1 and 2 have no Qgt to filter by — inferring the schema
        # correspondence is their whole point — so they get the full D' DDL.
        inputs[param] = ctx.target_ddl
    else:
      raise ValueError(f"Method asked for unknown param {param!r}")
  return inputs


def render_prompt(prompt_path: str, inputs: dict[str, str]) -> str:
  with open(prompt_path) as f:
    template = f.read()
  for param, value in inputs.items():
    template = template.replace(PLACEHOLDERS[param], value)
  return template


def run_method(method: dict, q: dict, ctx: RunContext) -> dict:
  """Runs one method on one query and returns its `method_gen` entry, either
  `{"query": ...}` or `{"error": ...}`. Self-contained per (query, method) pair,
  so scheduling these concurrently later needs no other change."""
  qid = q.get("id", "?")

  try:
    inputs = gather_inputs(method["params"], q, ctx)
    prompt = render_prompt(method["prompt_path"], inputs)
  except Exception as e:
    return {"error": f"Could not gather context: {e}"}

  try:
    message = query_model(prompt)
    content = message.get("content") or ""
  except Exception as e:
    return {"error": f"LLM failed: {e}"}

  try:
    return {"query": extract_json(content)["query"]}
  except Exception as e:
    try:
      detail = f"; raw response saved to {save_raw_response(ctx.db, method['method_id'], qid, content)!r}"
    except Exception as save_error:
      detail = f"; could not save the raw response: {save_error}"
    return {"error": f"Model did not return valid JSON ({e}){detail}"}


def save_raw_response(db: int, method_id: str, qid, content: str) -> str:
  directory = query_store.raw_responses_dir(db)
  os.makedirs(directory, exist_ok=True)
  path = os.path.join(directory, f"{method_id}_{qid}.txt")
  with open(path, "w") as f:
    f.write(content)
  return path


METHODS = [
  {
    "method_id": "method_1",
    "name": "infer_mapping",
    "desc": "Infer the schema correspondence unaided: (Ssrc, Qsrc, Stgt) -> Q'",
    "function": run_method,
    "params": ["Ssrc", "Qsrc", "Stgt"],
    "prompt_path": method_prompt_path(1),
  },
  {
    "method_id": "method_2",
    "name": "apply_mapping",
    "desc": "Apply the given mapping f: (Ssrc, Qsrc, Stgt, f) -> Q'",
    "function": run_method,
    "params": ["Ssrc", "Qsrc", "Stgt", "f"],
    "prompt_path": method_prompt_path(2),
  },
  {
    "method_id": "method_3",
    "name": "rewrite_bare",
    "desc": "Rewrite the ground-truth query with no extra context: (Qgt, Stgt) -> Q'",
    "function": run_method,
    "params": ["Qgt", "Stgt"],
    "prompt_path": method_prompt_path(3),
  },
  {
    "method_id": "method_4",
    "name": "rewrite_with_plan",
    "desc": "Rewrite the ground-truth query given its plan: (Qgt, Stgt, Pgt) -> Q'",
    "function": run_method,
    "params": ["Qgt", "Stgt", "Pgt"],
    "prompt_path": method_prompt_path(4),
  },
  {
    "method_id": "method_5",
    "name": "rewrite_with_context",
    "desc": "Rewrite the ground-truth query given its plan and origin: (Qgt, Stgt, Pgt, Ssrc, Qsrc) -> Q'",
    "function": run_method,
    "params": ["Qgt", "Stgt", "Pgt", "Ssrc", "Qsrc"],
    "prompt_path": method_prompt_path(5),
  },
]


def public_method(method: dict) -> dict:
  """The registry entry as it is recorded in queries.json — description only,
  never the callable or the local prompt path."""
  return {k: method[k] for k in ("method_id", "name", "desc", "params")}


def resolve_methods(selected: list[str] | None) -> list[dict]:
  """Maps `--method` tokens (`3` or `method_3`) onto registry entries, keeping
  registry order regardless of the order they were passed in."""
  if not selected:
    return list(METHODS)

  by_id = {m["method_id"]: m for m in METHODS}
  chosen = set()
  for token in selected:
    method_id = token if token.startswith("method_") else f"method_{token}"
    if method_id not in by_id:
      raise SystemExit(
        f"Unknown method {token!r}. Valid ids: {', '.join(by_id)} (the number alone also works)."
      )
    chosen.add(method_id)
  return [m for m in METHODS if m["method_id"] in chosen]


def print_methods() -> None:
  for m in METHODS:
    print(f"{m['method_id']}  {m['name']}")
    print(f"  {m['desc']}")
    print(f"  params: {', '.join(m['params'])}")


def run_one_method(method: dict, q_data: dict, ctx: RunContext, overwrite: bool) -> None:
  """Runs one method over every eligible query. A failure is recorded on the
  offending (query, method) pair only — it never aborts the method."""
  method_id = method["method_id"]
  needs_raw_query = "Qgt" in method["params"]
  succeeded = 0
  attempted = 0

  for q in q_data["queries"]:
    qid = q.get("id", "?")

    if "error" in q:
      print(f"[{method_id}][{qid}] Skipping (already has error): {q['error']}")
      continue
    if needs_raw_query and not q.get("raw_query"):
      print(f"[{method_id}][{qid}] Skipping (no raw query to rewrite)")
      continue

    existing = query_store.get_method_entry(q, method_id)
    if existing and existing.get("query") and not overwrite:
      print(f"[{method_id}][{qid}] Skipping (already generated; use --overwrite)")
      continue

    attempted += 1
    print(f"[{method_id}][{qid}] Migrating...")
    try:
      entry = method["function"](method, q, ctx)
    except Exception as e:
      entry = {"error": f"Unexpected failure: {e}"}
    query_store.set_method_entry(q, method_id, entry)

    if "error" in entry:
      print(f"[{method_id}][{qid}] {entry['error']}")
    else:
      print(f"[{method_id}][{qid}] OK")
      succeeded += 1

  print(f"[{method_id}] Done. {succeeded}/{attempted} queries migrated.")


def main() -> None:
  parser = argparse.ArgumentParser(
    description="Migrate each query of D onto D' with the LLM, once per method."
  )
  parser.add_argument("--db", type=int, default=1, metavar="N")
  parser.add_argument(
    "--method", action="append", metavar="M",
    help="method to run, as `3` or `method_3`; repeatable (default: all)",
  )
  parser.add_argument("--list", action="store_true", help="list the methods and exit")
  parser.add_argument(
    "--overwrite", action="store_true",
    help="regenerate entries that already hold a query (failed ones are always retried)",
  )
  args = parser.parse_args()

  if args.list:
    print_methods()
    return

  methods = resolve_methods(args.method)

  if not DB_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")

  db_data = query_store.load_db(args.db)
  q_data = query_store.load_queries(
    args.db, "Run generate_query.py and generate_raw_queries.py first."
  )
  query_store.set_methods(q_data, [public_method(m) for m in METHODS])

  try:
    target_ddl = fetch_schema_ddl(DB_URL, TARGET_PG_SCHEMA)
  except Exception as e:
    print(f"Could not dump {TARGET_PG_SCHEMA!r} ({e}); falling back to db.json's copy.")
    target_ddl = db_data["target_schema"]

  with psycopg.connect(DB_URL, autocommit=True) as conn:
    conn.execute(f"SET search_path TO {TARGET_PG_SCHEMA};")
    ctx = RunContext(db=args.db, db_data=db_data, target_ddl=target_ddl, conn=conn)
    for method in methods:
      run_one_method(method, q_data, ctx, args.overwrite)
      # Written per method so an interrupted run keeps whatever finished.
      query_store.save_queries(args.db, q_data)

  print("Done.")


if __name__ == "__main__":
  main()
