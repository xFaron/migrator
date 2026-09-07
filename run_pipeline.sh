#!/usr/bin/env bash
#
# Runs the full query-migration generation pipeline for one test case, in order.
# If any step in an iteration fails, that iteration is skipped (logged as
# failed) and the loop moves on to the next DB_NUM. set -e still aborts
# immediately on errors *outside* the per-iteration steps (e.g. bad args).
#
# Usage: ./run_pipeline.sh [DB_NUM] [K] [RUNS]
#   DB_NUM  test case number to start from under test_dbs/db<N>  (default: 1)
#   K       number of queries to generate           (default: 10)
#   RUNS    number of times to run the pipeline, incrementing DB_NUM
#           by 1 each time (default: 1)

set -euo pipefail

DB_NUM_START="${1:-1}"
K="${2:-10}"
RUNS="${3:-1}"

PYTHON="venv/bin/python"

K_ARGS=()
if [[ -n "$K" ]]; then
  K_ARGS=(--k "$K")
fi

FAILED_RUNS=()

run_iteration() {
  local db_num="$1"
  local db_dir="test_dbs/db${db_num}"
  local db_json="${db_dir}/db.json"
  local queries_json="${db_dir}/queries.json"

  echo "==> [1/5] generate_db.py --db ${db_num}"
  "$PYTHON" generate_db.py --db "$db_num"

  echo "==> [2/5] generate_query.py --db ${db_num} ${K:+--k $K}"
  "$PYTHON" generate_query.py --db "$db_num" "${K_ARGS[@]}"

  echo "==> [3/5] instantiate.py (pass 2: repopulate schema + filter zero-row queries)"
  "$PYTHON" instantiate.py "$db_json" "$queries_json"

  echo "==> [4/5] generate_raw_queries.py --db ${db_num}"
  "$PYTHON" generate_raw_queries.py --db "$db_num"

  echo "==> [5/5] generate_optim_queries.py --db ${db_num}"
  "$PYTHON" generate_optim_queries.py --db "$db_num"
}

for (( i=0; i<RUNS; i++ )); do
  DB_NUM=$(( DB_NUM_START + i ))

  echo "==> Run $((i + 1))/${RUNS}: db${DB_NUM}"

  # Calling run_iteration directly as the `if` condition suspends set -e
  # for everything inside it, so a failing step returns non-zero here
  # instead of killing the whole script.
  if run_iteration "$DB_NUM"; then
    echo "==> Pipeline complete for db${DB_NUM}."
  else
    echo "==> [FAILED] db${DB_NUM} - skipping to next run." >&2
    FAILED_RUNS+=("$DB_NUM")
    continue
  fi
done

if (( ${#FAILED_RUNS[@]} > 0 )); then
  echo "==> Done. ${#FAILED_RUNS[@]} run(s) failed: ${FAILED_RUNS[*]}" >&2
else
  echo "==> Done. All ${RUNS} run(s) succeeded."
fi
