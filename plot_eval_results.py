"""Plots summarizing `evaluate_queries.py` output across one or more test cases.

Reads `queries.json` for each requested `--db`, flattens every `method_gen`
entry into one row of a long-form table, and renders:

  1. equivalence_by_method.png   - stacked bar of equivalence class counts per method;
                                    the DB_EQ segment is split into two (cold runtime
                                    beats raw_query or not), folding in what used to be
                                    a separate win-rate plot
  2. relative_cost_by_method.png - box+strip of relative_cost per method (DB_EQ+ only)
  3. cold_vs_hot_runtime.png     - mean relative_cold_runtime vs relative_hot_runtime per method
  4. cost_vs_runtime_scatter.png - relative_cost vs relative_hot_runtime (DB_EQ+ only),
                                    colored by method with each method's mean marked, to
                                    show which generation method is cheapest and fastest
  5. raw_vs_source_runtime.png   - raw_query hot runtime vs source_query hot runtime,
                                    one point per query (query-level, not per-method)

Queries or methods with no measurements yet (no `method_gen` entry with a
`cost`) are silently skipped rather than erroring - this is meant to run on
whatever subset of the pipeline has completed.
"""

import argparse
import glob
import os

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

import query_store

# Fixed-order categorical palette (dataviz skill's validated default, slots 1-5).
METHOD_PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]

# Fixed status palette, ordered weakest -> strongest equivalence. UNK sits outside
# that ordering (it means "not determined", not "stronger than EQ") so it gets a
# neutral color rather than a spot on the red->green ramp.
EQUIVALENCE_ORDER = ["INV", "NEQ", "ST_EQ", "DB_EQ", "EQ", "UNK"]
EQUIVALENCE_COLORS = {
  "INV": "#d03b3b",     # red
  "NEQ": "#e87ba4",     # magenta
  "ST_EQ": "#eda100",   # yellow
  "DB_EQ": "#2a78d6",   # blue
  "EQ": "#0ca30c",      # green
  "UNK": "#898781",     # neutral gray
}

CORRECT_ENOUGH = ("DB_EQ", "EQ")  # threshold for "is this a usable rewrite"

sns.set_theme(style="whitegrid")


def discover_dbs() -> list[int]:
  dbs = []
  for path in sorted(glob.glob(os.path.join("test_dbs", "db*", "queries.json"))):
    name = os.path.basename(os.path.dirname(path))
    if name[2:].isdigit():
      dbs.append(int(name[2:]))
  return dbs


def method_names(data: dict) -> dict[str, str]:
  return {m["method_id"]: m.get("name", m["method_id"]) for m in data.get("methods", [])}


def load_rows(dbs: list[int]) -> pd.DataFrame:
  rows = []
  for db in dbs:
    data = query_store.load_queries(db, hint="Run the pipeline for this db first.")
    names = method_names(data)
    for q in data["queries"]:
      qid = q.get("id")
      for entry in q.get("method_gen", []):
        if "cost" not in entry:
          continue  # generation failed or not yet measured
        method_id = entry["method_id"]
        rows.append({
          "db": db,
          "qid": qid,
          "query_label": f"db{db}#{qid}",
          "method_id": method_id,
          "method_name": names.get(method_id, method_id),
          "cost": entry.get("cost"),
          "cold_runtime": entry.get("cold_runtime"),
          "hot_runtime": entry.get("hot_runtime"),
          "relative_cost": entry.get("relative_cost"),
          "relative_cold_runtime": entry.get("relative_cold_runtime"),
          "relative_hot_runtime": entry.get("relative_hot_runtime"),
          "equivalence": entry.get("equivalence", "UNK"),
        })
  return pd.DataFrame(rows)


def load_query_rows(dbs: list[int]) -> pd.DataFrame:
  """One row per query (not per method), for fields that live on the query itself
  rather than in a `method_gen` entry."""
  rows = []
  for db in dbs:
    data = query_store.load_queries(db, hint="Run the pipeline for this db first.")
    for q in data["queries"]:
      rows.append({
        "db": db,
        "qid": q.get("id"),
        "query_label": f"db{db}#{q.get('id')}",
        "raw_query_hot_runtime": q.get("raw_query_hot_runtime"),
        "source_query_hot_runtime": q.get("source_query_hot_runtime"),
      })
  return pd.DataFrame(rows)


def method_order(df: pd.DataFrame) -> list[str]:
  return sorted(df["method_id"].unique(), key=lambda m: int(m.split("_")[1]) if m.split("_")[-1].isdigit() else 0)


def method_palette_map(methods: list[str]) -> dict[str, str]:
  return {m: METHOD_PALETTE[i % len(METHOD_PALETTE)] for i, m in enumerate(methods)}


def label_for(df: pd.DataFrame, method_id: str) -> str:
  row = df.loc[df["method_id"] == method_id, "method_name"]
  return row.iloc[0] if len(row) else method_id


def plot_equivalence_by_method(df: pd.DataFrame, out_dir: str) -> None:
  """Stacked bar of equivalence class counts per method. DB_EQ is split into two
  sub-segments - cold runtime beats raw_query, or it doesn't - so the win-rate
  question (is a "correct enough" rewrite actually faster) reads directly off this
  one chart instead of a separate win_rate_by_method plot. EQ is left whole: it is
  proven equivalent regardless of speed, so there is no "does it even help" question
  to fold in the way there is for DB_EQ."""
  sub = df.copy()
  is_db_eq = sub["equivalence"] == "DB_EQ"
  faster = is_db_eq & (sub["relative_cold_runtime"] < 1)
  sub["class"] = sub["equivalence"]
  sub.loc[is_db_eq & faster, "class"] = "DB_EQ_faster"
  sub.loc[is_db_eq & ~faster, "class"] = "DB_EQ_slower"

  # (color, hatch, legend label) per stacked segment, in weakest -> strongest order;
  # DB_EQ_faster/slower share DB_EQ's color and are told apart by hatching.
  class_meta = {}
  class_order = []
  for eq in EQUIVALENCE_ORDER:
    if eq == "DB_EQ":
      class_order += ["DB_EQ_faster", "DB_EQ_slower"]
      class_meta["DB_EQ_faster"] = (EQUIVALENCE_COLORS["DB_EQ"], None, "DB_EQ, cold runtime < raw_query")
      class_meta["DB_EQ_slower"] = (EQUIVALENCE_COLORS["DB_EQ"], "///", "DB_EQ, cold runtime ≥ raw_query")
    else:
      class_order.append(eq)
      class_meta[eq] = (EQUIVALENCE_COLORS.get(eq, "#898781"), None, eq)

  methods = method_order(sub)
  counts = (
    sub.groupby(["method_id", "class"]).size().unstack(fill_value=0)
    .reindex(index=methods, columns=[c for c in class_order if c in sub["class"].unique()], fill_value=0)
  )
  fig, ax = plt.subplots(figsize=(1.4 * len(methods) + 2, 5))
  bottom = pd.Series(0, index=counts.index, dtype=float)
  for cls in counts.columns:
    color, hatch, label = class_meta[cls]
    ax.bar(
      [label_for(df, m) for m in counts.index], counts[cls], bottom=bottom,
      color=color, label=label, edgecolor="#fcfcfb", linewidth=1.5, hatch=hatch,
    )
    bottom += counts[cls]
  ax.set_xticks(range(len(counts.index)))
  ax.set_xticklabels([label_for(df, m) for m in counts.index], rotation=20, ha="right")
  ax.set_ylabel("Number of queries")
  ax.set_xlabel("Method")
  ax.set_title("Equivalence class vs. raw_query, by method")
  ax.legend(title="Equivalence", frameon=False, fontsize=8, loc="upper left", bbox_to_anchor=(1.02, 1.0))
  fig.savefig(os.path.join(out_dir, "equivalence_by_method.png"), dpi=150, bbox_inches="tight")
  plt.close(fig)


def plot_relative_cost_by_method(df: pd.DataFrame, out_dir: str) -> None:
  sub = df[df["equivalence"].isin(CORRECT_ENOUGH) & df["relative_cost"].notna()]
  if sub.empty:
    print("Skipping relative_cost_by_method.png: no DB_EQ/EQ rows with relative_cost")
    return
  methods = method_order(sub)
  palette = method_palette_map(methods)
  fig, ax = plt.subplots(figsize=(1.4 * len(methods) + 2, 5))
  sns.boxplot(
    data=sub, x="method_id", y="relative_cost", order=methods, hue="method_id", hue_order=methods,
    palette=palette, legend=False, ax=ax, fliersize=0, boxprops=dict(alpha=0.6),
  )
  sns.stripplot(
    data=sub, x="method_id", y="relative_cost", order=methods, color="#0b0b0b",
    alpha=0.6, size=4, jitter=0.15, ax=ax,
  )
  ax.axhline(1.0, color="#898781", linestyle="--", linewidth=1, label="raw_query baseline")
  ax.set_xticks(range(len(methods)))
  ax.set_xticklabels([label_for(sub, m) for m in methods], rotation=20, ha="right")
  ax.set_xlabel("Method")
  ax.set_ylabel("Planner cost relative to raw_query")
  ax.set_title("Relative planner cost by method (DB_EQ/EQ queries only)")
  ax.legend(frameon=False)
  fig.tight_layout()
  fig.savefig(os.path.join(out_dir, "relative_cost_by_method.png"), dpi=150)
  plt.close(fig)


def plot_cold_vs_hot_runtime(df: pd.DataFrame, out_dir: str) -> None:
  sub = df[df["equivalence"].isin(CORRECT_ENOUGH)]
  means = sub.groupby("method_id")[["relative_cold_runtime", "relative_hot_runtime"]].mean().dropna(how="all")
  if means.empty:
    print("Skipping cold_vs_hot_runtime.png: no DB_EQ/EQ rows with runtime ratios")
    return
  methods = method_order(means.reset_index())
  means = means.reindex(methods)
  fig, ax = plt.subplots(figsize=(7, 1.1 * len(methods) + 1.5))
  y = range(len(methods))
  for i, m in enumerate(methods):
    cold, hot = means.loc[m, "relative_cold_runtime"], means.loc[m, "relative_hot_runtime"]
    if pd.notna(cold) and pd.notna(hot):
      ax.plot([cold, hot], [i, i], color="#898781", linewidth=1.5, zorder=1)
    if pd.notna(cold):
      ax.scatter(cold, i, color="#2a78d6", s=90, zorder=2, label="cold" if i == 0 else None)
    if pd.notna(hot):
      ax.scatter(hot, i, color="#eb6834", s=90, zorder=2, label="hot" if i == 0 else None)
  ax.axvline(1.0, color="#898781", linestyle="--", linewidth=1)
  ax.set_yticks(list(y))
  ax.set_yticklabels([label_for(df, m) for m in methods])
  ax.set_xlabel("Mean runtime relative to raw_query")
  ax.set_title("Cold vs. hot relative runtime by method\n(DB_EQ/EQ queries only)")
  ax.legend(frameon=False, loc="best")
  fig.tight_layout()
  fig.savefig(os.path.join(out_dir, "cold_vs_hot_runtime.png"), dpi=150)
  plt.close(fig)


def plot_cost_vs_runtime_scatter(df: pd.DataFrame, out_dir: str) -> None:
  """Colored by method (not equivalence, which gave no way to tell methods apart)
  and restricted to DB_EQ/EQ rows, since a cheap/fast rewrite that isn't even a
  correct one isn't a candidate for "best method." Each method's mean is marked
  with a large X, so the method whose cluster sits closest to the origin - cheapest
  and fastest relative to raw_query - is visible at a glance."""
  sub = df[df["equivalence"].isin(CORRECT_ENOUGH) & df["relative_cost"].notna() & df["relative_hot_runtime"].notna()]
  if sub.empty:
    print("Skipping cost_vs_runtime_scatter.png: no DB_EQ/EQ rows with both ratios")
    return
  methods = method_order(sub)
  palette = method_palette_map(methods)
  means = sub.groupby("method_id")[["relative_cost", "relative_hot_runtime"]].mean()

  fig, ax = plt.subplots(figsize=(7, 6))
  for m in methods:
    part = sub[sub["method_id"] == m]
    ax.scatter(
      part["relative_cost"], part["relative_hot_runtime"], color=palette[m],
      label=label_for(sub, m), alpha=0.6, s=40, edgecolor="#fcfcfb", linewidth=0.5,
    )
  for m in methods:
    if m in means.index:
      ax.scatter(
        means.loc[m, "relative_cost"], means.loc[m, "relative_hot_runtime"], color=palette[m],
        marker="X", s=220, edgecolor="#0b0b0b", linewidth=1.2, zorder=5,
      )
  ax.axhline(1.0, color="#898781", linestyle="--", linewidth=1)
  ax.axvline(1.0, color="#898781", linestyle="--", linewidth=1)
  ax.set_xlabel("Planner cost relative to raw_query")
  ax.set_ylabel("Hot runtime relative to raw_query")
  ax.set_title("Cost vs. runtime by method (DB_EQ/EQ queries; ✕ = method mean)")
  ax.legend(title="Method", frameon=False)
  fig.tight_layout()
  fig.savefig(os.path.join(out_dir, "cost_vs_runtime_scatter.png"), dpi=150)
  plt.close(fig)


def plot_raw_vs_source_runtime(query_df: pd.DataFrame, out_dir: str) -> None:
  """raw_query (Qgt, on D') vs source_query (Qsrc, on D) hot runtime, one point per
  query - are the two roughly comparable, or does moving off D change the cost
  picture on its own, before any migration method even gets involved?"""
  sub = query_df[query_df["raw_query_hot_runtime"].notna() & query_df["source_query_hot_runtime"].notna()]
  if sub.empty:
    print("Skipping raw_vs_source_runtime.png: no rows with both raw_query and source_query runtimes")
    return
  lo = min(sub["source_query_hot_runtime"].min(), sub["raw_query_hot_runtime"].min())
  hi = max(sub["source_query_hot_runtime"].max(), sub["raw_query_hot_runtime"].max())
  pad = (hi - lo) * 0.05 if hi > lo else 1.0

  fig, ax = plt.subplots(figsize=(6.5, 6))
  ax.plot([lo - pad, hi + pad], [lo - pad, hi + pad], color="#898781", linestyle="--", linewidth=1, label="y = x")
  ax.scatter(
    sub["source_query_hot_runtime"], sub["raw_query_hot_runtime"], color="#2a78d6",
    alpha=0.7, s=40, edgecolor="#fcfcfb", linewidth=0.5,
  )
  ax.set_xlim(lo - pad, hi + pad)
  ax.set_ylim(lo - pad, hi + pad)
  ax.set_xlabel("source_query (Qsrc, on D) hot runtime (ms)")
  ax.set_ylabel("raw_query (Qgt, on D') hot runtime (ms)")
  ax.set_title("raw_query vs. source_query hot runtime")
  ax.legend(frameon=False)
  fig.tight_layout()
  fig.savefig(os.path.join(out_dir, "raw_vs_source_runtime.png"), dpi=150)
  plt.close(fig)


def main() -> None:
  parser = argparse.ArgumentParser(description="Plot evaluate_queries.py results across one or more test cases.")
  parser.add_argument("--dbs", type=int, nargs="+", metavar="N", help="db numbers to include (default: all under test_dbs/)")
  parser.add_argument("--out-dir", default="plots", help="directory to write PNGs into (default: plots)")
  args = parser.parse_args()

  dbs = args.dbs or discover_dbs()
  if not dbs:
    raise SystemExit("No test_dbs/db<N>/queries.json found")

  df = load_rows(dbs)
  if df.empty:
    raise SystemExit("No measured method_gen entries found (run evaluate_queries.py first)")

  os.makedirs(args.out_dir, exist_ok=True)
  plot_equivalence_by_method(df, args.out_dir)
  plot_relative_cost_by_method(df, args.out_dir)
  plot_cold_vs_hot_runtime(df, args.out_dir)
  plot_cost_vs_runtime_scatter(df, args.out_dir)
  plot_raw_vs_source_runtime(load_query_rows(dbs), args.out_dir)
  print(f"Wrote plots to {args.out_dir}/")


if __name__ == "__main__":
  main()
