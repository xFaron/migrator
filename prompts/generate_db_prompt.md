You are given the PostgreSQL **target database** schema `Stgt` (`pg_dump --schema-only`):

```sql
{STGT}
```

Design a realistic, semantically meaningful **source database** `Ssrc` that substantially transforms/reinterprets the target data. Avoid trivial renaming, reordering, or simple filtering. Prefer non-trivial joins, derived columns, conditional logic, aggregations, window functions, string/date/numeric transformations, normalization/denormalization, many-to-many relationships, composite relationships, and source tables derived from multiple target tables. The result should be logically plausible, deterministic, and difficult to reconstruct manually.

Return **JSON only**:

```json
{
  "source_schema": "-- CREATE TABLE statements ONLY",
  "table_generation_queries": [
    {
      "source_table": "<table_name>",
      "query": "SELECT ...;"
    }
  ]
}
```

Rules:

* `source_schema` contains **only `CREATE TABLE` statements**, one for every source table.
* Define all columns, types, NOT NULL, UNIQUE, CHECK, etc.
* Define **PRIMARY KEY and FOREIGN KEY in `CREATE TABLE` itself**.
* Every FK must reference an actual PK and have the **same type**.
* No `schema.table` notation; use table names only.
* For every source table, provide **exactly one** generation query, in the same order as the table declarations.
* Each query must generate **all rows and all columns explicitly**; nothing may rely on DEFAULTs, identities, generated columns, or implicit behavior.
* Queries may use any deterministic PostgreSQL expressions, joins, subqueries, aggregations, window functions, etc.
* Generation queries may reference **only the target database**, never source tables.
* `DATE - DATE` already returns an integer number of days; **do not use `EXTRACT(DAY FROM date_difference)`**.
* All source data must be fully derivable from the target database.
* The code needs to be Postgres SQL
