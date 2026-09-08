"""Async orchestrator for the query-migration generation pipeline.

Replaces run_pipeline.sh with a version that (1) adds a final evaluate_queries.py
stage, (2) runs multiple db numbers' pipelines concurrently, and (3) is safe to
run that way despite a shared, non-namespaced Postgres resource.

Concurrency model
------------------
generate_db.py, generate_query.py, instantiate.py and evaluate_queries.py all
create/drop/populate or read the SAME physical Postgres schema, named by the
GENERATED_SCHEMA env var (default "query_migr_generated"). That schema name is
NOT namespaced per db number, so:

  - generate_db.py's validate_generated_db() does a transient
    DROP SCHEMA IF EXISTS / CREATE SCHEMA dance to validate DDL.
  - generate_query.py's validate_generated_queries() does the same dance to
    EXPLAIN candidate queries.
  - instantiate.py DROPs/CREATEs it for real and populates it -- this is the
    schema every later step for that db number actually reads from.
  - evaluate_queries.py reads from it via `SET search_path`.

Running any two of these four scripts concurrently -- even for two *different*
db numbers -- races on the same DROP/CREATE SCHEMA calls: e.g. db A's
DROP SCHEMA ... CASCADE could wipe out db B's tables mid-populate. So these
four steps are serialized against each other GLOBALLY, across every db number
in this invocation, via a single `asyncio.Lock`.

generate_raw_queries.py never touches Postgres at all (pure local sqlglot
transform), and generate_optim_queries.py only ever touches the SOURCE schema
(D', e.g. "public") for sample rows/plans -- never GENERATED_SCHEMA -- so
neither needs the lock and both run freely in parallel across db numbers.

Within one db number, steps still run in this fixed order:

    generate_db -> generate_query -> generate_raw_queries ->
    generate_optim_queries -> instantiate -> evaluate_queries

Note instantiate.py and evaluate_queries.py are NOT independently-lockable
steps like generate_db.py/generate_query.py -- they are held under a SINGLE
continuous acquisition of the schema lock, back-to-back, with no release in
between. This matters because instantiate.py commits real data into
GENERATED_SCHEMA that must survive, untouched, until THIS SAME db's
evaluate_queries.py reads it. If the lock were released between the two (as
it is between every other pair of locked steps), a different db number's
generate_db.py/generate_query.py/instantiate.py could legally acquire it in
the gap and DROP SCHEMA CASCADE + recreate GENERATED_SCHEMA for itself,
destroying this db's already-committed data before its own
evaluate_queries.py ever runs. Holding the lock continuously across both
subprocess calls closes that window entirely. generate_raw_queries.py and
generate_optim_queries.py are run *before* instantiate.py precisely so they
don't need to be inside (or contend for) that same combined locked section --
they only need db.json/queries.json/raw_queries.json as plain files, which
are already written by generate_db.py/generate_query.py by that point.

Across different db numbers, whole per-db pipelines run as concurrent asyncio
tasks, contending for the global schema lock only during their locked steps.
While db 1 holds the lock (say, running generate_db.py), db 2 can be running
its own unlocked generate_raw_queries.py/generate_optim_queries.py at the
same time; the instant the lock frees, whichever db is next in line for a
locked step proceeds. This -- plus genuine LLM-call concurrency during the two
unlocked, LLM-calling-adjacent stages -- is the real parallelism win over the
old fully-sequential bash script.

Rate limiting
-------------
llm_tools.py's query_model() already retries individual HTTP calls on 429/5xx
with exponential backoff (honoring Retry-After). This script's job is the
other half: not provoking a burst of 429s by having too many db pipelines
firing LLM calls at the same instant. `--max-parallel` (default 3) bounds how
many db pipelines may be concurrently in flight at all, via an
`asyncio.Semaphore` acquired around each db's *entire* pipeline (not just its
locked steps), so its LLM-calling stages are bounded by it too.

CLI
---
    run_pipeline.py [--start N] [--runs R] [--dbs N [N ...]] [--k K]
                     [--max-parallel P] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

PYTHON = sys.executable

# Steps that touch the shared, non-namespaced GENERATED_SCHEMA and therefore
# must be serialized globally across every db number's pipeline.
#
# generate_db.py and generate_query.py are each locked independently (via
# run_step below). instantiate.py and evaluate_queries.py are NOT run through
# run_step/this set individually -- run_db_pipeline acquires schema_lock once
# and runs both of them back-to-back under that single acquisition, so no
# other db's locked step can interleave between them. They're listed here
# only for documentation/completeness of "steps that touch GENERATED_SCHEMA".
LOCKED_STEPS = {"generate_db.py", "generate_query.py", "instantiate.py", "evaluate_queries.py"}


class StepFailed(Exception):
  def __init__(self, db_num: int, step: str, returncode: int):
    super().__init__(f"db{db_num}: {step} failed with exit code {returncode}")
    self.db_num = db_num
    self.step = step
    self.returncode = returncode


def default_k() -> int:
  # Mirrors run_pipeline.sh's own default of 10 (NOT generate_query.py's
  # internal fallback of 5).
  return int(os.getenv("DEFAULT_K", "10"))


async def stream_prefixed(stream: asyncio.StreamReader, prefix: str) -> None:
  """Read lines from a subprocess's combined stdout/stderr and print them each
  prefixed, so interleaved output from concurrent db pipelines stays readable."""
  while True:
    line = await stream.readline()
    if not line:
      break
    text = line.decode(errors="replace").rstrip("\n")
    print(f"{prefix}{text}")


async def run_command(db_num: int, cmd: list[str], dry_run: bool) -> None:
  """Run one subprocess command, prefixing its merged output, and raise
  StepFailed on a non-zero return code."""
  prefix = f"[db{db_num}] "
  step_name = os.path.basename(cmd[1]) if len(cmd) > 1 else cmd[0]
  print(f"{prefix}running: {' '.join(cmd)}")

  if dry_run:
    # No subprocess is spawned, so there is no natural suspension point for
    # asyncio to switch between concurrently running db pipelines on. Yield
    # once here purely so --dry-run's output actually demonstrates the
    # interleaving/lock-respecting behavior (max-parallel, lock contention)
    # instead of running each db's steps to completion before the next
    # starts. Real (non-dry-run) runs get this naturally from awaiting
    # subprocess I/O and never hit this branch.
    await asyncio.sleep(0)
    return

  proc = await asyncio.create_subprocess_exec(
    *cmd,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.STDOUT,
  )
  await stream_prefixed(proc.stdout, prefix)
  returncode = await proc.wait()

  if returncode != 0:
    raise StepFailed(db_num, step_name, returncode)


async def run_step(
  db_num: int,
  cmd: list[str],
  dry_run: bool,
  schema_lock: asyncio.Lock,
) -> None:
  """Run a single pipeline step, acquiring the global schema lock first if
  this step touches the shared GENERATED_SCHEMA."""
  step_name = os.path.basename(cmd[1]) if len(cmd) > 1 else cmd[0]
  if step_name in LOCKED_STEPS:
    async with schema_lock:
      await run_command(db_num, cmd, dry_run)
  else:
    await run_command(db_num, cmd, dry_run)


async def run_db_pipeline(
  db_num: int,
  k: int,
  dry_run: bool,
  schema_lock: asyncio.Lock,
  semaphore: asyncio.Semaphore,
) -> tuple[int, Exception | None]:
  """Run the full ordered pipeline for one db number, bounded by the global
  concurrency semaphore. Returns (db_num, error-or-None)."""
  async with semaphore:
    db_dir = os.path.join("test_dbs", f"db{db_num}")
    db_json = os.path.join(db_dir, "db.json")
    queries_json = os.path.join(db_dir, "queries.json")

    steps = [
      [PYTHON, "generate_db.py", "--db", str(db_num)],
      [PYTHON, "generate_query.py", "--db", str(db_num), "--k", str(k)],
      [PYTHON, "generate_raw_queries.py", "--db", str(db_num)],
      [PYTHON, "generate_optim_queries.py", "--db", str(db_num)],
    ]

    instantiate_cmd = [PYTHON, "instantiate.py", db_json, queries_json]
    evaluate_cmd = [PYTHON, "evaluate_queries.py", "--db", str(db_num)]

    try:
      for cmd in steps:
        await run_step(db_num, cmd, dry_run, schema_lock)

      # instantiate.py commits real data into GENERATED_SCHEMA that must
      # survive untouched until this same db's evaluate_queries.py reads it.
      # Hold the schema lock continuously across both calls -- one single
      # acquisition, no release in between -- so no other db's
      # generate_db.py/generate_query.py/instantiate.py can drop/recreate
      # GENERATED_SCHEMA out from under this db in the gap.
      async with schema_lock:
        await run_command(db_num, instantiate_cmd, dry_run)
        await run_command(db_num, evaluate_cmd, dry_run)

      print(f"[db{db_num}] Pipeline complete.")
      return db_num, None
    except StepFailed as e:
      print(f"[db{db_num}] [FAILED] {e} - skipping remaining steps for this db.", file=sys.stderr)
      return db_num, e
    except Exception as e:
      print(f"[db{db_num}] [FAILED] unexpected error: {e} - skipping remaining steps for this db.", file=sys.stderr)
      return db_num, e


def resolve_db_numbers(args: argparse.Namespace) -> list[int]:
  if args.dbs:
    return list(args.dbs)
  return [args.start + i for i in range(args.runs)]


async def main() -> None:
  parser = argparse.ArgumentParser(
    description="Orchestrate the query-migration generation pipeline across one or more db numbers."
  )
  parser.add_argument("--start", type=int, default=1, metavar="N",
                       help="first db number (default: 1); ignored if --dbs is given")
  parser.add_argument("--runs", type=int, default=1, metavar="R",
                       help="how many consecutive db numbers starting at --start (default: 1); "
                            "ignored if --dbs is given")
  parser.add_argument("--dbs", type=int, nargs="+", metavar="N",
                       help="explicit list of db numbers to run instead of a --start/--runs range")
  parser.add_argument("--k", type=int, default=default_k(), metavar="K",
                       help="value passed as generate_query.py's --k (default: DEFAULT_K env var, "
                            "falling back to 10)")
  parser.add_argument("--max-parallel", type=int, default=3, metavar="P",
                       help="max number of db pipelines concurrently in flight (default: 3)")
  parser.add_argument("--dry-run", action="store_true",
                       help="print each stage's command instead of running it")
  args = parser.parse_args()

  db_numbers = resolve_db_numbers(args)

  schema_lock = asyncio.Lock()
  semaphore = asyncio.Semaphore(args.max_parallel)

  tasks = [
    run_db_pipeline(db_num, args.k, args.dry_run, schema_lock, semaphore)
    for db_num in db_numbers
  ]
  results = await asyncio.gather(*tasks)

  failed = [db_num for db_num, err in results if err is not None]

  if failed:
    print(f"==> Done. {len(failed)} run(s) failed: {failed}", file=sys.stderr)
    sys.exit(1)
  else:
    print(f"==> Done. All {len(db_numbers)} run(s) succeeded.")


if __name__ == "__main__":
  asyncio.run(main())
