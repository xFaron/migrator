# Query Migration

## Problem Statement

Given two databases **D** and **D′**, and a set of queries **Q** written for **D**, automatically generate an equivalent set of queries **Q′** for **D′** such that each migrated query produces the same result as its original.

Formally, for every query `q ∈ Q`, generate `q' ∈ Q'` satisfying:

```
Result(q, D) = Result(q', D')
```

### Naming convention

Queries are migrated **from D to D′**, so throughout this repo:

- **D** = **Ssrc** = the **source**: the LLM-generated database the original queries were written against. It is instantiated as a Postgres schema (`SOURCE_PG_SCHEMA`) whose every table is defined by a SELECT over D′. Anything named `source_*` (`source_schema`, `source_table`, `SOURCE_PG_SCHEMA`) refers to it.
- **D′** = **Stgt** = the **target**: the real database (e.g. TPC-H) reachable through `DATABASE_URL`, living in `TARGET_PG_SCHEMA`. Anything named `target_*` refers to it.

Note this is the opposite of the direction the *generation* pipeline runs in: D is designed from D′, but every query travels D → D′, and the naming follows the queries. The symbols used below and in the prompt templates:

| Symbol | Meaning | Where it lives |
|---|---|---|
| `Ssrc` | DDL of D | `db.json` → `source_schema` |
| `Stgt` | DDL of D′ | `db.json` → `target_schema` |
| `Qsrc` | Original query on D | `queries.json` → `query` |
| `f` | Per-table SELECT over D′ that materializes a table of D | `db.json` → `table_generation_queries[]` (`{source_table, query}`) |
| `Qgt` | Deterministic ground-truth rewrite of `Qsrc` onto D′ | `queries.json` → `raw_query` |
| `Pgt` | `EXPLAIN` plan of `Qgt` on D′ | computed on demand |

## Setup

Requirements
- Python 3.12+
- Java 17+ (for the bundled sqlsolver jar)

Install dependencies:

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your values:

| Variable | Default | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | — | API key for OpenRouter |
| `OPENROUTER_API_URL` | OpenRouter chat-completions endpoint | Chat-completions endpoint |
| `OPENROUTER_MODEL` | `nvidia/nemotron-3-ultra-550b-a55b:free` | Model identifier |
| `GOOGLE_API_KEY` | — | API key for Google's Generative Language API |
| `GOOGLE_API_URL` | Google API endpoint | Generative Language endpoint |
| `GOOGLE_MODEL` | `models/gemma-4-31b-it` | Model identifier |
| `GOOGLE_REASONING` | `minimal` | Reasoning effort for the Google provider |
| `DATABASE_URL` | — | PostgreSQL connection string for D′ (e.g. the TPC-H database) |
| `SOURCE_PG_SCHEMA` | `query_migr_generated` | Postgres schema D is instantiated in |
| `TARGET_PG_SCHEMA` | `public` | Postgres schema D′ lives in |
| `DB_PROMPT_PATH` | `prompts/generate_db_prompt.md` | Prompt template for DB generation |
| `QUERY_PROMPT_PATH` | `prompts/generate_query_prompt.md` | Prompt template for query generation |
| `METHOD1_PROMPT_PATH` | `prompts/method1_prompt.md` | Prompt template for method 1 |
| `METHOD2_PROMPT_PATH` | `prompts/method2_prompt.md` | Prompt template for method 2 |
| `METHOD3_PROMPT_PATH` | `prompts/method3_prompt.md` | Prompt template for method 3 |
| `METHOD4_PROMPT_PATH` | `prompts/method4_prompt.md` | Prompt template for method 4 |
| `METHOD5_PROMPT_PATH` | `prompts/method5_prompt.md` | Prompt template for method 5 |
| `DEFAULT_K` | `5` | Number of queries to generate |

Defaults above are the in-code fallbacks; `.env.example` ships values that work (e.g. `SOURCE_PG_SCHEMA="gen"`, `DEFAULT_K="15"`).

The LLM provider defaults to Google; pass `provider="openrouter"` to `query_model()` to switch.

Every entrypoint calls `check_env()` on startup, which fails loudly (naming each one) if `.env` still sets a variable renamed or removed by the source/target refactor.

## Pipeline

Each test case lives under `test_dbs/db<N>/`. The steps below are what `run_pipeline.py` runs, in this order:

```bash
python run_pipeline.py [--start N --end N | --dbs N [N ...]] [--k K] [--dry-run]
```

### 1. Generate the source database D — `generate_db.py`

Fetches the schema of D′ and uses an LLM to design a source database D: its schema (`source_schema`) plus a `table_generation_queries` entry per table (`f`), each a SELECT over D′ that populates it.

```bash
python generate_db.py [--db N]
```

Output: `test_dbs/db<N>/db.json` (`source_schema`, `target_schema`, `table_generation_queries`).

### 2. Generate queries on D — `generate_query.py`

Uses an LLM to produce K SQL queries (`Qsrc`) that run against D's schema.

```bash
python generate_query.py [--db N] [--k K]
```

Output: `test_dbs/db<N>/queries.json`

| Argument | Default | Description |
|---|---|---|
| `--db N` | 1 | Test-case number |
| `--k K` | `DEFAULT_K` from `.env` | Number of queries to generate |

### 3. Instantiate D — `instantiate.py`

Creates D as a Postgres schema (`SOURCE_PG_SCHEMA`), populates its tables from `table_generation_queries`, and drops any query that returns zero rows. Rolls back and exits non-zero on any failure.

```bash
python instantiate.py [--db N]
```

Must run before `generate_raw_queries.py`, which executes the original queries against the instantiated schema.

### 4. Generate the ground-truth rewrite — `generate_raw_queries.py`

Rewrites each query to run directly on D′ by inlining every referenced table's generation query as a CTE, writing the result into that query's `raw_query` field (`Qgt`) — or `error` on a transform failure.

```bash
python generate_raw_queries.py [--db N]
```

### 5. Generate LLM migrations — `generate_llm_queries.py`

Runs the LLM methods: everything the deterministic rewrite does, asked of a model instead, so the two can be compared. Methods 1-2 migrate `Qsrc` from D to D′; methods 3-5 start from the ground-truth rewrite `Qgt` and ask the model to improve it, given progressively more context.

```bash
python generate_llm_queries.py [--db N] [--method M ...] [--overwrite]  # default: all methods
python generate_llm_queries.py --list                                  # show the registry
```

| method_id | name | params | Question it isolates |
|---|---|---|---|
| `method_1` | `infer_mapping` | `Ssrc, Qsrc, Stgt` | Can the model *infer* the schema correspondence and migrate without being told `f`? |
| `method_2` | `apply_mapping` | `Ssrc, Qsrc, Stgt, f` | Given the mapping, can it apply (and simplify) it? |
| `method_3` | `rewrite_bare` | `Qgt, Stgt` | Can it improve the ground-truth rewrite from the SQL and schema alone? |
| `method_4` | `rewrite_with_plan` | `Qgt, Stgt, Pgt` | Does the query plan let it find optimizations it otherwise misses? |
| `method_5` | `rewrite_with_context` | `Qgt, Stgt, Pgt, Ssrc, Qsrc` | Does knowing the query's *intent* (the original query and D's schema) help further? |

`params` is load-bearing: a method receives exactly the inputs it lists and its prompt template gets exactly the matching placeholders (`{SSRC}`, `{STGT}`, `{QSRC}`, `{QGT}`, `{PGT}`, `{F}`). Methods that take `Qgt` get D′'s DDL filtered down to the tables that query touches; methods 1 and 2 get the full DDL. Adding a method is one registry entry plus one prompt file.

Each result is written into that query's `method_gen` list as `{"method_id": ..., "query": ...}`, or `{"method_id": ..., "error": ...}` when generation fails.

### 6. Evaluate — `evaluate_queries.py`

For each query with a `raw_query`, measures planner cost plus one cold run and the average of `N - 1` hot reruns (`EXPLAIN ANALYZE`), clearing the OS page cache and restarting Postgres before every measurement, and rates equivalence against `raw_query` via `db_tools/correctness` (sqlsolver, falling back to an `EXCEPT ALL` row diff). Three things are measured per query: the source query `query` (Qsrc, on D), the ground-truth rewrite `raw_query` (Qgt, on D′, the comparison baseline), and every `method_gen` entry.

```bash
sudo python evaluate_queries.py [--db N]
```

Requires root — it stops/starts Postgres and drops the page cache — and exits non-zero with a message otherwise. It iterates `method_gen` generically, so whatever methods are present get evaluated. The query's own two measurements are written on the query itself under explicit prefixes, so they stay tellable apart: `source_query_*` for `query` and `raw_query_*` for `raw_query`. Every `method_gen` entry gets its numbers unprefixed (its `method_id` already scopes them) plus ratios against the `raw_query` baseline.

`query` is measured on D, so it needs D still instantiated in `SOURCE_PG_SCHEMA`. If it is not, the run says so once and skips every source measurement rather than failing per query — each measurement restarts Postgres, so failing one by one would cost a full restart cycle per query to learn the same thing. A source query that cannot be measured records `source_query_error` on the query; unlike a top-level `error` this does not make later stages skip it. `query` gets no `relative_*` ratio and no equivalence rating: it runs on a different database from the baseline, and `generate_raw_queries.py` has already verified the two return the same rows.

`queries.json` is rewritten after each query, so an interrupted run keeps everything already measured.

## Test case layout

```
test_dbs/
  db1/
    db.json           # Source database D: source_schema, target_schema, table_generation_queries
    queries.json      # methods registry + every query, with each stage's fields merged in
    raw_responses/    # raw LLM output kept when a response failed to parse
  db2/
    ...
```

Steps 3-6 don't produce their own files: each reads `test_dbs/db<N>/queries.json`, merges its output into the record of every query by id, and writes the same file back. A record accumulates:

```json
{
  "methods": [
    {"method_id": "method_1", "name": "infer_mapping", "desc": "...", "params": ["Ssrc", "Qsrc", "Stgt"]}
  ],
  "queries": [
    {
      "id": 1,
      "query": "SELECT ...",                 // Qsrc, on D            (generate_query.py)
      "raw_query": "WITH ... SELECT ...",    // Qgt, on D'            (generate_raw_queries.py)
      "source_query_cost": 1500.0,           // Qsrc measured on D    (evaluate_queries.py)
      "source_query_cold_runtime": 910.6,
      "source_query_hot_runtime": 400.2,
      "raw_query_cost": 1234.5,              // Qgt on D', the comparison baseline
      "raw_query_cold_runtime": 812.3,
      "raw_query_hot_runtime": 340.1,
      "raw_query_equivalence": "EQ",
      "method_gen": [                        //                       (generate_llm_queries.py)
        {
          "method_id": "method_1",
          "query": "SELECT ...",
          "cost": 900.2,                     //                       (evaluate_queries.py)
          "cold_runtime": 700.4,
          "hot_runtime": 300.0,
          "relative_cost": 0.73,
          "relative_cold_runtime": 0.86,
          "relative_hot_runtime": 0.88,
          "equivalence": "DB_EQ"
        },
        {"method_id": "method_4", "error": "LLM failed: ..."}
      ]
    }
  ]
}
```

The top-level `methods` block is regenerated from the registry on every `generate_llm_queries.py` run and describes only the methods that exist today. A stage that fails for a given query tags it (or its method entry) with an `error` field instead of dropping it, and later stages skip what already carries one.

## Notes

- `query_store.py` is the single reader/writer of `db.json`/`queries.json`. Pipeline scripts never open these files directly, so the on-disk shape is defined in exactly one place. It also rejects pre-refactor files loudly instead of misreading them.
- Artifacts generated before the source/target refactor (`target_database_schema`, `target_table`, `baseline_1_query`, `optim_query`, `analysis`) are upgraded in place by:
  ```bash
  python scripts/migrate_test_dbs.py [--dbs N ...] [--root DIR] [--dry-run]   # re-running is a no-op
  ```
- Prompt templates live under `prompts/`.
- `view_test_case.py` is a Streamlit browser for a test case's JSON artifacts, including the per-method metrics table:
  ```bash
  streamlit run view_test_case.py
  ```
- `TODO.md` tracks the broader evaluation methodology (correctness levels, cost/runtime screening, the comparison against the Lithe paper in `papers/`).
