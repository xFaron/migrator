You are given a PostgreSQL source database schema (`pg_dump --schema-only`):

```sql
{DB_SCHEMA}
```

Generate a realistic, semantically meaningful **target schema** that substantially transforms/reinterprets the source data. Avoid trivial renaming, reordering, or simple filtering. Prefer non-trivial joins, derived columns, conditional logic, aggregations, window functions, string/date/numeric transformations, normalization/denormalization, many-to-many relationships, composite relationships, and tables derived from multiple source tables. The result should be logically plausible, deterministic, and difficult to reconstruct manually.

Return **JSON only**:

```json
{
  "target_database_schema": "-- CREATE TABLE statements ONLY",
  "table_generation_queries": [
    {
      "target_table": "<table_name>",
      "query": "SELECT ...;"
    }
  ]
}
```

Rules:

* `target_database_schema` contains **only `CREATE TABLE` statements**, one for every target table.
* Define all columns, types, NOT NULL, UNIQUE, CHECK, etc.
* Define **PRIMARY KEY and FOREIGN KEY in `CREATE TABLE` itself**.
* Every FK must reference an actual PK and have the **same type**.
* No `schema.table` notation; use table names only.
* For every target table, provide **exactly one** generation query, in the same order as the table declarations.
* Each query must generate **all rows and all columns explicitly**; nothing may rely on DEFAULTs, identities, generated columns, or implicit behavior.
* Queries may use any deterministic PostgreSQL expressions, joins, subqueries, aggregations, window functions, etc.
* Generation queries may reference **only the source database**, never target tables.
* `DATE - DATE` already returns an integer number of days; **do not use `EXTRACT(DAY FROM date_difference)`**.
* All target data must be fully derivable from the source database.
* The code needs to be Postgres SQL
