# Query Migration

## Problem Statement

Given two databases, **D** and **D′**, and a set of queries **Q** written for **D**, automatically generate an equivalent set of queries **Q′** for **D′** such that each migrated query produces the same result as its original query.

Formally, for every query \(q \in Q\), generate a corresponding query \(q' \in Q'\) satisfying:

\[
Result(q, D) = Result(q', D')
\]

where equality is determined by comparing the results of the two queries.

## Usage

Requires a `.env` to run `generate_*` files.

```.env
LLM_API_KEY="<api-key>"
API_URL="https://<your-provider>/api/v1/chat/completions"
DATABASE_URL="<db-url>"
```

Only tested with OPERROUTER as the provider.