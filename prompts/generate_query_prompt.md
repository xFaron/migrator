Given a PostgreSQL schema (`pg_dump --schema-only`) and integer K, generate exactly K valid, executable, diverse SQL queries.

Requirements:
- Reference only tables/columns present in the schema; use their names exactly.
- Every query must return ≥1 row on a reasonably populated database.
- Prefer meaningful diversity: SELECTs, FK-based joins, multi-table joins, aggregates, GROUP BY/HAVING, subqueries, CTEs, CASE, date operations, and correlated subqueries.
- Avoid trivial variations.
- Queries must be syntactically valid PostgreSQL.
- Return JSON only, with exactly K entries, each query as a single-line string:

{
  "queries": [
    {"id": 1, "query": "SELECT ..."},
    ...
  ]
}

Schema:
```sql
{DB_SCHEMA}
````

K = {K}