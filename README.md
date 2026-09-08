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

### 4. Generate raw queries on D′ — `generate_raw_queries.py`

Rewrites each query in `queries.json` to run directly on D′ by inlining each table's generation subquery.
Validates that every rewritten query returns the same result as its original. Raises on any mismatch.

```bash
python generate_raw_queries.py [--db N]
```

Output: `test_dbs/db<N>/raw_queries.json`

### 5. Evaluate queries — `evaluate_queries.py`

Matches each query in `queries.json` with its counterpart in `raw_queries.json` and, per pair, captures planner
cost and measured runtime (`EXPLAIN ANALYZE`) plus a correctness rating (via `db_tools/correctness`, backed by
sqlsolver).

```bash
python evaluate_queries.py [--db N]
```

Output: `test_dbs/db<N>/eval_queries.json`

### 6. Generate optimized queries — `generate_optim_queries.py` (WIP)

Baseline for generating an optimized/rewritten version of a query and checking equivalence with the original.
See `TODO.md` for the broader evaluation plan.

## Test case layout

```
test_dbs/
  db1/
    db.json           # Generated database D (schema + population queries)
    queries.json      # Queries on D
    raw_queries.json  # Equivalent queries on D′
  db2/
    ...
```

## Notes

- LLM provider prompt templates live under `prompts/`.
- `instantiate.py` must be run before `generate_raw_queries.py` for a given test case, as the latter runs the original queries against the instantiated schema to verify equivalence.
