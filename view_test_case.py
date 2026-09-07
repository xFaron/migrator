import json
import os
from pathlib import Path

import sqlglot
import streamlit as st

st.set_page_config(page_title="Test Case Viewer", layout="wide")
st.title("Test Case Viewer")

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

json_files = sorted(folder_path.glob("*.json"))
if not json_files:
    st.warning("No JSON files found.")
    st.stop()


# --- Rendering ---

def is_sql(s: str) -> bool:
    upper = s.upper().lstrip()
    return any(upper.startswith(kw) for kw in ("SELECT", "INSERT", "CREATE", "WITH", "UPDATE", "DELETE"))

def format_sql(s: str) -> str:
    try:
        statements = sqlglot.transpile(s.strip(), pretty=True)
        return ";\n\n".join(statements)
    except Exception:
        return s.strip()

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
                    item.get("target_table")
                    or f"Query #{item.get('id', '?')}"
                )
                with st.expander(label, expanded=False):
                    for k, v in item.items():
                        st.caption(k)
                        render_value(v)
            else:
                render_value(item)
    elif isinstance(value, dict):
        for k, v in value.items():
            st.markdown(f"**{k}**")
            render_value(v)
    else:
        st.write(value)


# --- Tabs: one per JSON file ---
tabs = st.tabs([f.name for f in json_files])
for tab, json_path in zip(tabs, json_files):
    with tab:
        with open(json_path) as f:
            data = json.load(f)
        for key, value in data.items():
            st.subheader(key)
            render_value(value)
            st.divider()
