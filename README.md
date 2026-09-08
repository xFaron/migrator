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
LLM_API_KEY=""           # API key for the LLM provider
API_URL=""               # Chat completions endpoint
DATABASE_URL=""          # PostgreSQL connection string for D' (e.g. the TPC-H database)

LLM_MODEL=""             # Model identifier (default: nvidia/nemotron-3-ultra-550b-a55b:free)
GENERATED_SCHEMA=""      # Postgres schema to instantiate D in (default: query_migr_generated)
DB_PROMPT_PATH=""        # Prompt template for DB generation (default: generate_db_prompt.md)
QUERY_PROMPT_PATH=""     # Prompt template for query generation (default: generate_query_prompt.md)
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

- Only tested with OpenRouter as the LLM provider.
- `instantiate.py` must be run before `generate_raw_queries.py` for a given test case, as the latter runs the original queries against the instantiated schema to verify equivalence.
