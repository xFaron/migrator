import json
import os
from pathlib import Path

import pandas as pd
import sqlglot
import streamlit as st

st.set_page_config(page_title="Test Case Viewer", page_icon="🗂️", layout="wide")

st.markdown(
    """
    <style>
    .block-container { padding-top: 2rem; }
    h1 { font-weight: 700; }
    [data-testid="stExpander"] { border-radius: 8px; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🗂️ Test Case Viewer")

# --- Sidebar: folder selection ---
test_dbs = Path("test_dbs")
detected = sorted(str(p) for p in test_dbs.iterdir() if p.is_dir()) if test_dbs.is_dir() else []

if detected:
    folder = st.sidebar.selectbox("Test case", detected)
else:
    folder = st.sidebar.text_input("Folder path", value="test_dbs/db1")

folder_path = Path(folder)
if not folder_path.is_dir():
    st.error(f"Folder not found: `{folder}`")
    st.stop()

all_files = sorted(
    (p for p in folder_path.iterdir() if p.is_file() and p.suffix in (".json", ".txt")),
    key=lambda p: p.name,
)
if not all_files:
    st.warning("No JSON or raw-text files found.")
    st.stop()

st.sidebar.caption(f"{len(all_files)} file(s) in `{folder_path}`")


# --- Rendering ---

def is_sql(s: str) -> bool:
    upper = s.upper().lstrip()
    return any(upper.startswith(kw) for kw in ("SELECT", "INSERT", "CREATE", "WITH", "UPDATE", "DELETE"))

def format_sql(s: str) -> str:
    try:
        statements = sqlglot.transpile(s.strip(), read="postgres", pretty=True)
        return ";\n\n".join(statements)
    except Exception:
        return s.strip()


# Cosmetic labels/order/colors for the measurements table - display only, the
# underlying values are shown exactly as stored, just laid out as a table
# (method x metric) instead of a nested key/value dump.
_METRIC_ORDER = [
    "equivalence",
    "cost", "relative_cost",
    "cold_runtime", "relative_cold_runtime",
    "hot_runtime", "relative_hot_runtime",
]
_METRIC_LABELS = {
    "cost": "cost (planner)",
    "relative_cost": "cost vs. raw_query",
    "cold_runtime": "cold runtime (ms)",
    "relative_cold_runtime": "cold runtime vs. raw_query",
    "hot_runtime": "hot runtime (ms)",
    "relative_hot_runtime": "hot runtime vs. raw_query",
    "equivalence": "equivalence",
}
_EQUIVALENCE_COLORS = {
    "EQ": "#1a7f37",
    "DB_EQ": "#0969da",
    "ST_EQ": "#9a6700",
    "NEQ": "#cf222e",
    "INV": "#6e7781",
    "UNK": "#6e7781",
}

# The query's own two measurements are stored prefixed, so `query` (Qsrc, run on D)
# and `raw_query` (Qgt, run on D') stay tellable apart; method entries are already
# scoped by their method_id and keep the bare metric names.
_QUERY_METRIC_PREFIXES = {"source_query": "query", "raw_query": "raw_query"}


def metric_rows(query: dict) -> dict:
    """One row per measured thing: the source query, the ground-truth rewrite it was
    migrated into (the baseline), then every `method_gen` entry."""
    rows = {}
    for prefix, label in _QUERY_METRIC_PREFIXES.items():
        metrics = {k: query[f"{prefix}_{k}"] for k in _METRIC_ORDER if f"{prefix}_{k}" in query}
        if metrics:
            rows[label] = metrics
    for entry in query.get("method_gen", []):
        metrics = {k: entry[k] for k in _METRIC_ORDER if k in entry}
        if metrics:
            rows[entry.get("method_id", "?")] = metrics
    return rows


def render_metrics(rows: dict):
    df = pd.DataFrame(rows).T
    cols = [c for c in _METRIC_ORDER if c in df.columns] + [c for c in df.columns if c not in _METRIC_ORDER]
    df = df[cols].rename(columns=_METRIC_LABELS)
    df.index.name = "query / method"  # the first rows are the query itself, not methods

    fmt = {}
    for col in df.columns:
        if col.endswith("vs. raw_query"):
            fmt[col] = "{:.2f}x"
        elif col in ("cold runtime (ms)", "hot runtime (ms)", "cost (planner)"):
            fmt[col] = "{:.2f}"

    styler = df.style.format(fmt, na_rep="-")
    if "equivalence" in df.columns:
        styler = styler.map(
            lambda v: f"color: {_EQUIVALENCE_COLORS.get(v, '')}; font-weight: 700",
            subset=["equivalence"],
        )
    st.dataframe(styler, use_container_width=True)


def render_method_gen(entries: list):
    """The generated SQL per method, below the metrics table. An entry that only
    holds an `error` (generation or measurement failed) is shown as that text."""
    for entry in entries:
        if not isinstance(entry, dict):
            render_value(entry)
            continue
        st.caption(entry.get("method_id", "?"))
        for k in ("query", "error"):
            if k in entry:
                render_value(entry[k])


def render_dict_item(item: dict):
    """One entry of a list of records - a query, or a table generation query."""
    rows = metric_rows(item)
    if rows:
        st.caption("measurements")
        render_metrics(rows)

    for k, v in item.items():
        if rows and k in _METRIC_ORDER:
            continue  # already in the table above
        if k == "method_gen" and isinstance(v, list):
            render_method_gen(v)
            continue
        st.caption(k)
        render_value(v)


def render_value(value):
    if isinstance(value, str):
        if is_sql(value):
            st.code(format_sql(value), language="sql")
        else:
            # Render \n as actual newlines in a text block
            st.text(value.strip())
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                label = (
                    item.get("source_table")
                    # the top-level `methods` registry has neither a table nor an id
                    or item.get("method_id")
                    or f"Query #{item.get('id', '?')}"
                )
                with st.expander(label, expanded=False):
                    render_dict_item(item)
            else:
                render_value(item)
    elif isinstance(value, dict):
        for k, v in value.items():
            st.markdown(f"**{k}**")
            render_value(v)
    else:
        st.write(value)


# --- Tabs: one per file ---
tabs = st.tabs([f.name for f in all_files])
for tab, file_path in zip(tabs, all_files):
    with tab:
        content = file_path.read_text()
        if file_path.suffix == ".json":
            data = json.loads(content)
            for key, value in data.items():
                st.subheader(key)
                render_value(value)
                st.divider()
        else:
            # Raw LLM response text (e.g. *.raw.txt) - shown verbatim, unparsed.
            st.caption("Raw file (not JSON) - shown as-is")
            st.code(content, language="text")
