"""Tabulate per-query evaluation metrics into a cross-method comparison table.

`evaluate_queries.py` writes one evaluation file per test case, holding, for
every query, the planner cost and measured runtime of the *original* query
against D and of the *migrated* query against D', plus an equivalence rating.
This script reads those files across every test case and every generation
method and reduces them to the three headline metrics:

  correctness   -- the percentage of queries a method migrated correctly,
                   reported per database and pooled across databases.
  runtime       -- the geometric mean of per-query runtime improvements over a
                   chosen baseline method (baseline_runtime / method_runtime;
                   > 1 means the method is faster).
  cost          -- the same, over planner cost.

A "generation method" is just an evaluation file: `eval_queries.json` is the
deterministic CTE-inlining rewrite of `generate_raw_queries.py` (method `raw`),
and `eval_<name>_queries.json` is method `<name>` (so `eval_baseline1_queries.json`
is `baseline1`). The baseline the improvements are measured against is
`--baseline` (default `raw`); the pseudo-method `d` selects the original query
running against D, i.e. the pre-migration numbers carried in every eval record,
which answers "what did migrating to D' cost us" rather than "which migration
method won".

Output: a JSON file with every intermediate count and ratio (per database and
overall), plus the same numbers printed as tables on stdout.
"""

import argparse
import glob
import json
import math
import os
import re

# Ordered worst -> best, mirroring db_tools.correctness.Equivalence. Redefined
# here rather than imported so the script stays a pure JSON reader with no
# database or JVM dependency. The enum's UNK is deliberately absent: it means
# "the check did not conclude", not a level of correctness, so it is counted
# separately and never treated as correct.
EQUIVALENCE_LEVELS = ["INV", "NEQ", "ST_EQ", "DB_EQ", "EQ"]
DEFAULT_CORRECT_AT = "DB_EQ"

# The baseline name that means "the original query, run against D", read from
# the `d` side of each eval record instead of from a separate eval file.
SOURCE_BASELINE = "d"

METRICS = ["runtime_ms", "cost"]


def method_name(path: str) -> str:
  """`eval_queries.json` -> `raw`; `eval_baseline1_queries.json` -> `baseline1`."""
  base = os.path.basename(path)
  if base == "eval_queries.json":
    return "raw"
  m = re.fullmatch(r"eval_(.+)_queries\.json", base)
  return m.group(1) if m else base


def discover(test_dbs_dir: str, dbs: list[str], methods: list[str] | None) -> dict:
  """Collect {db: {method: [records]}} from every eval file under `test_dbs_dir`."""
  found: dict[str, dict[str, list]] = {}

  for db_dir in sorted(glob.glob(os.path.join(test_dbs_dir, "db*"))):
    db = os.path.basename(db_dir)
    if dbs and db not in dbs:
      continue
    for path in sorted(glob.glob(os.path.join(db_dir, "eval*queries.json"))):
      method = method_name(path)
      if methods and method not in methods:
        continue
      with open(path) as f:
        data = json.load(f)
      found.setdefault(db, {})[method] = data.get("queries", [])

  return found


def is_correct(record: dict, correct_at: str) -> bool:
  """A query counts as correctly generated when it produced a usable migration
  whose equivalence rating reaches `correct_at`. Anything the pipeline tagged
  with an `error`, and anything rated UNK or unrated, does not."""
  if "error" in record:
    return False
  rating = record.get("equivalence")
  if rating not in EQUIVALENCE_LEVELS:
    return False
  return EQUIVALENCE_LEVELS.index(rating) >= EQUIVALENCE_LEVELS.index(correct_at)


def measurement(record: dict, metric: str, side: str) -> float | None:
  """Pull one positive measurement out of an eval record. `side` is `d_prime`
  (the migrated query on D') or `d` (the original query on D). Missing and
  non-positive values are dropped: they cannot take part in a geometric mean,
  and a zero denominator is a division by zero, not an infinite speedup."""
  value = (record.get(metric) or {}).get(side)
  if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
    return None
  return float(value)


def geomean(ratios: list[float]) -> float | None:
  if not ratios:
    return None
  return math.exp(sum(math.log(r) for r in ratios) / len(ratios))


def improvements(
  method_records: dict,
  baseline_records: dict,
  baseline: str,
  metric: str,
  correct_at: str,
  pairs: str,
) -> dict:
  """Per-query improvement ratios of one method over the baseline, for one
  metric. A query contributes only when both sides have a usable measurement
  for it and the `pairs` policy admits it."""
  ratios, per_query, skipped = [], {}, 0

  for qid, record in method_records.items():
    method_value = measurement(record, metric, "d_prime")

    if baseline == SOURCE_BASELINE:
      # The pre-migration number lives on the method's own record, so both
      # sides are always the same query and pairing is exact.
      baseline_value = measurement(record, metric, "d")
      baseline_correct = True
    else:
      baseline_record = baseline_records.get(qid) or {}
      baseline_value = measurement(baseline_record, metric, "d_prime")
      baseline_correct = bool(baseline_record) and is_correct(baseline_record, correct_at)

    if method_value is None or baseline_value is None:
      skipped += 1
      continue

    method_correct = is_correct(record, correct_at)
    if pairs == "both-correct" and not (method_correct and baseline_correct):
      skipped += 1
      continue
    if pairs == "method-correct" and not method_correct:
      skipped += 1
      continue

    ratio = baseline_value / method_value
    ratios.append(ratio)
    per_query[qid] = {
      "baseline": baseline_value,
      "method": method_value,
      "improvement": ratio,
    }

  return {
    "geomean_improvement": geomean(ratios),
    "n_pairs": len(ratios),
    "n_skipped": skipped,
    "per_query": per_query,
  }


def summarize(records: list[dict], correct_at: str) -> dict:
  """Correctness counts for one method on one database."""
  counts: dict[str, int] = {}
  correct = 0

  for record in records:
    key = "ERROR" if "error" in record else (record.get("equivalence") or "UNRATED")
    counts[key] = counts.get(key, 0) + 1
    if is_correct(record, correct_at):
      correct += 1

  total = len(records)
  return {
    "queries_total": total,
    "queries_correct": correct,
    "correctness_pct": (100.0 * correct / total) if total else None,
    "equivalence_counts": dict(sorted(counts.items())),
  }


def by_id(records: list[dict]) -> dict:
  """Index an eval file's queries by id, so methods can be paired query by
  query. Records without an id cannot be paired and are dropped."""
  return {q["id"]: q for q in records if q.get("id") is not None}


def analyse(found: dict, baseline: str, correct_at: str, pairs: str) -> dict:
  methods = sorted({m for per_method in found.values() for m in per_method})
  databases = sorted(found, key=lambda db: (len(db), db))

  per_database: dict[str, dict] = {}
  pooled = {
    method: {
      "queries_total": 0,
      "queries_correct": 0,
      "equivalence_counts": {},
      **{metric: {"ratios": [], "n_skipped": 0} for metric in METRICS},
    }
    for method in methods
  }

  for db in databases:
    baseline_records = (
      {} if baseline == SOURCE_BASELINE else by_id(found[db].get(baseline, []))
    )
    per_database[db] = {}

    for method, records in sorted(found[db].items()):
      stats = summarize(records, correct_at)
      method_records = by_id(records)

      for metric in METRICS:
        result = improvements(
          method_records, baseline_records, baseline, metric, correct_at, pairs
        )
        stats[metric] = result
        pooled[method][metric]["ratios"] += [
          pair["improvement"] for pair in result["per_query"].values()
        ]
        pooled[method][metric]["n_skipped"] += result["n_skipped"]

      per_database[db][method] = stats

      pooled[method]["queries_total"] += stats["queries_total"]
      pooled[method]["queries_correct"] += stats["queries_correct"]
      for key, count in stats["equivalence_counts"].items():
        pooled[method]["equivalence_counts"][key] = (
          pooled[method]["equivalence_counts"].get(key, 0) + count
        )

  overall = {}
  for method in methods:
    acc = pooled[method]
    total = acc["queries_total"]
    # Two ways to pool correctness: micro weights every query equally (so a
    # database contributing more queries counts for more), macro weights every
    # database equally (so one large test case cannot dominate).
    per_db_pcts = [
      per_database[db][method]["correctness_pct"]
      for db in databases
      if per_database[db].get(method)
      and per_database[db][method]["correctness_pct"] is not None
    ]
    overall[method] = {
      "databases": sum(1 for db in databases if method in per_database[db]),
      "queries_total": total,
      "queries_correct": acc["queries_correct"],
      "correctness_pct": (100.0 * acc["queries_correct"] / total) if total else None,
      "correctness_pct_macro": (sum(per_db_pcts) / len(per_db_pcts)) if per_db_pcts else None,
      "equivalence_counts": dict(sorted(acc["equivalence_counts"].items())),
      **{
        metric: {
          "geomean_improvement": geomean(acc[metric]["ratios"]),
          "n_pairs": len(acc[metric]["ratios"]),
          "n_skipped": acc[metric]["n_skipped"],
        }
        for metric in METRICS
      },
    }

  return {
    "methods": methods,
    "databases": databases,
    "per_database": per_database,
    "overall": overall,
  }


def fmt(value, spec: str = ".2f") -> str:
  return "-" if value is None else format(value, spec)


def render_table(headers: list[str], rows: list[list[str]]) -> str:
  widths = (
    [max(len(str(cell)) for cell in column) for column in zip(headers, *rows)]
    if rows else [len(h) for h in headers]
  )

  def line(cells):
    return "| " + " | ".join(str(c).ljust(w) for c, w in zip(cells, widths)) + " |"

  separator = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
  return "\n".join([line(headers), separator] + [line(row) for row in rows])


def print_report(analysis: dict, baseline: str, correct_at: str, pairs: str) -> None:
  methods, databases = analysis["methods"], analysis["databases"]
  per_database, overall = analysis["per_database"], analysis["overall"]

  print(f"\nCorrectness (queries rated >= {correct_at}), by database\n")
  rows = []
  for method in methods:
    row = [method]
    for db in databases:
      stats = per_database[db].get(method)
      row.append(
        "-" if not stats else
        f"{fmt(stats['correctness_pct'], '.1f')}% "
        f"({stats['queries_correct']}/{stats['queries_total']})"
      )
    summary = overall[method]
    row.append(
      f"{fmt(summary['correctness_pct'], '.1f')}% "
      f"({summary['queries_correct']}/{summary['queries_total']})"
    )
    row.append(f"{fmt(summary['correctness_pct_macro'], '.1f')}%")
    rows.append(row)
  print(render_table(["method", *databases, "overall", "macro avg"], rows))

  print(
    f"\nImprovement over baseline {baseline!r} "
    f"(geometric mean of baseline/method; > 1 = better), pairs={pairs}\n"
  )
  rows = [
    [
      method,
      f"{fmt(overall[method]['runtime_ms']['geomean_improvement'], '.3f')}x",
      str(overall[method]["runtime_ms"]["n_pairs"]),
      f"{fmt(overall[method]['cost']['geomean_improvement'], '.3f')}x",
      str(overall[method]["cost"]["n_pairs"]),
    ]
    for method in methods
  ]
  print(render_table(["method", "runtime geomean", "n", "cost geomean", "n"], rows))


def main() -> None:
  parser = argparse.ArgumentParser(
    description="Tabulate evaluated query metrics across generation methods."
  )
  parser.add_argument("--test-dbs", default="test_dbs", metavar="DIR",
                      help="directory holding the db<N>/ test cases (default: test_dbs)")
  parser.add_argument("--db", action="append", metavar="N",
                      help="restrict to this test case; repeatable (default: all)")
  parser.add_argument("--method", action="append", metavar="NAME",
                      help="restrict to this generation method; repeatable (default: all found)")
  parser.add_argument("--baseline", default="raw", metavar="NAME",
                      help=f"method that improvements are measured against, or "
                           f"{SOURCE_BASELINE!r} for the original query on D (default: raw)")
  parser.add_argument("--correct-at", default=DEFAULT_CORRECT_AT, choices=EQUIVALENCE_LEVELS,
                      help="lowest equivalence rating counted as correct "
                           f"(default: {DEFAULT_CORRECT_AT})")
  parser.add_argument("--pairs", default="both-correct",
                      choices=("both-correct", "method-correct", "all"),
                      help="which queries contribute to the geometric means "
                           "(default: both-correct)")
  parser.add_argument("--output", default="results_table.json", metavar="PATH")
  args = parser.parse_args()

  dbs = [db if db.startswith("db") else f"db{db}" for db in (args.db or [])]
  found = discover(args.test_dbs, dbs, args.method)
  if not found:
    raise SystemExit(
      f"No evaluation files found under {args.test_dbs!r}. Run evaluate_queries.py first."
    )

  methods = sorted({m for per_method in found.values() for m in per_method})
  if args.baseline != SOURCE_BASELINE and args.baseline not in methods:
    raise SystemExit(
      f"Baseline method {args.baseline!r} not found. Available: {', '.join(methods)} "
      f"(or {SOURCE_BASELINE!r} for the original query on D)."
    )

  analysis = analyse(found, args.baseline, args.correct_at, args.pairs)
  print_report(analysis, args.baseline, args.correct_at, args.pairs)

  output = {
    "config": {
      "test_dbs": args.test_dbs,
      "baseline": args.baseline,
      "correct_at": args.correct_at,
      "pairs": args.pairs,
      "equivalence_levels": EQUIVALENCE_LEVELS,
    },
    **analysis,
  }
  with open(args.output, "w") as f:
    json.dump(output, f, indent=2)

  print(f"\nWrote {args.output}")


if __name__ == "__main__":
  main()
