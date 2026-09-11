# Query Migration

## Problem Statement

Given two databases **D** and **D′**, and a set of queries **Q** written for **D**, automatically generate an equivalent set of queries **Q′** for **D′** such that each migrated query produces the same result as its original.

Formally, for every query `q ∈ Q`, generate `q' ∈ Q'` satisfying:

```
Result(q, D) = Result(q', D')
```

## Setup

Requirements
- Python3 3.12+
- Java 17+

Copy `.env.example` to `.env` and fill in your values:

```env
# LLM provider (defaults to Google; pass provider="openrouter" to query_model() to switch)
OPENROUTER_API_KEY=""    # API key for OpenRouter
OPENROUTER_API_URL=""    # OpenRouter chat completions endpoint
OPENROUTER_MODEL=""      # Model identifier (default: nvidia/nemotron-3-ultra-550b-a55b:free)

GOOGLE_API_KEY=""        # API key for Google's Generative Language API
GOOGLE_API_URL=""        # Google API endpoint
GOOGLE_MODEL=""          # Model identifier (default: models/gemma-4-31b-it)

DATABASE_URL=""          # PostgreSQL connection string for D' (e.g. the TPC-H database)
GENERATED_SCHEMA=""      # Postgres schema to instantiate D in (default: query_migr_generated)
DB_PROMPT_PATH=""        # Prompt template for DB generation (default: prompts/generate_db_prompt.md)
QUERY_PROMPT_PATH=""     # Prompt template for query generation (default: prompts/generate_query_prompt.md)
BASELINE1_PROMPT_PATH="" # Prompt template for baseline 1 (default: prompts/baseline1_prompt.md)
BASELINE2_PROMPT_PATH="" # Prompt template for baseline 2 (default: prompts/baseline2_prompt.md)
DEFAULT_K=""             # Number of queries to generate (default: 5)
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Pipeline

Each test case lives under `test_dbs/db<N>/`. Run the steps below in order.

### 1. Generate target database — `generate_db.py`

Fetches the schema of D′ and uses an LLM to design a target database D (schema + table population queries).

```bash
python generate_db.py [--db N]
```

Output: `test_dbs/db<N>/db.json`

### 2. Instantiate D — `instantiate.py`

Creates D as a Postgres schema, populates its tables, and validates that all queries return non-zero rows.
Rolls back and exits on any failure.

```bash
python instantiate.py test_dbs/db<N>/db.json test_dbs/db<N>/queries.json
```

### 3. Generate queries on D — `generate_query.py`

Uses an LLM to produce K SQL queries that run against D.

```bash
python generate_query.py [--db N] [--k K]
```

Output: `test_dbs/db<N>/queries.json`

| Argument | Default | Description |
|---|---|---|
| `--db N` | 1 | Test-case number |
| `--k K` | `DEFAULT_K` from `.env` | Number of queries to generate |

Steps 4-7 below don't produce their own output files: each one reads `test_dbs/db<N>/queries.json`, adds its
own field(s) to every query by id, and writes the same file back in place. A query's record accumulates
`query` → `raw_query` → `baseline_1_query`/`baseline_2_query` → `optim_query` → `cost`/`runtime_ms`/`equivalence`
as later steps run; a stage that fails for a given query tags it with a `<stage>_error` field instead of
dropping it (e.g. `raw_query_error`, `baseline_1_error`, `optim_error`, `eval_error`).

### 4. Generate raw queries on D′ — `generate_raw_queries.py`

Rewrites each query in `queries.json` to run directly on D′ by inlining each table's generation subquery, and
writes the rewritten query into that query's `raw_query` field (or `raw_query_error` on a transform failure).

```bash
python generate_raw_queries.py [--db N]
```

### 5. Evaluate queries — `evaluate_queries.py`

For each query with a `raw_query`, captures planner cost and measured runtime (`EXPLAIN ANALYZE`) for both
`query` (on D) and `raw_query` (on D′), plus a correctness rating (via `db_tools/correctness`, backed by
sqlsolver), writing `cost`, `runtime_ms` and `equivalence` back onto the query (or `eval_error` on failure).

```bash
python evaluate_queries.py [--db N]
```

### 6. Generate LLM baselines — `generate_baselines.py`

Asks an LLM to do the migration `generate_raw_queries.py` does deterministically, so the two can be compared.
Both baselines are given D's schema (from `db.json`), the queries on D (`queries.json`), D′'s schema
(dumped live from `DATABASE_URL`) and table samples from D′; baseline 2 additionally gets
`table_generation_queries`, i.e. the mapping that defines every table of D as a SELECT over D′.

| Baseline | Inputs | Question it isolates |
|---|---|---|
| 1 | `(D_schema, D′_schema, Q, samples)` | Can the LLM *infer* the schema correspondence? |
| 2 | `(D_schema, D′_schema, Q, f, samples)` | Given the mapping, can it apply (and simplify) it? |

```bash
python generate_baselines.py [--db N] [--baseline 1] [--baseline 2]
```

Writes each baseline's migrated query into that query's `baseline_1_query`/`baseline_2_query` field. Queries
the model dropped are tagged with `baseline_1_error`/`baseline_2_error` instead.

### 7. Generate optimized queries — `generate_optim_queries.py` (WIP)

Asks an LLM to produce an optimized/rewritten version of each query's `raw_query`, writing the result into that
query's `optim_query` field (or `optim_error` on failure). See `TODO.md` for the broader evaluation plan.

## Test case layout

```
test_dbs/
  db1/
    db.json           # Generated database D (schema + population queries)
    queries.json      # Every query, keyed by id, with each pipeline stage's fields merged in
  db2/
    ...
```

## Notes

- LLM provider prompt templates live under `prompts/`.
- `instantiate.py` must be run before `generate_raw_queries.py` for a given test case, as the latter runs the original queries against the instantiated schema to verify equivalence.
