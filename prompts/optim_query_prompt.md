You are an expert PostgreSQL DBA/SQL optimizer. Rewrite the given query to improve execution performance **without changing its exact result**.

Inputs:
- `[TABLE SCHEMAS]`: PostgreSQL DDL for all referenced tables, including columns, types, nullability, keys, and constraints.
- `[TABLE SAMPLES]`: first 5 rows of each table for selectivity/cardinality reasoning.
- `[ORIGINAL QUERY]`: query to optimize.
- `[QUERY PLAN]`: PostgreSQL EXPLAIN output showing bottlenecks.

Use the schema, samples, and plan to identify bottlenecks and apply valid semantic optimizations such as subquery→JOIN, `IN`→`EXISTS`, predicate pushdown, removing redundant conditions, and exploiting constraints.

The result must return **exactly the same rows and columns** as the original. Return **JSON only**:

{
  "query": "<optimized SQL string>"
}

[TABLE SCHEMAS]
```sql
{TABLE_SCHEMAS}
````

[TABLE SAMPLES]
```json
{TABLE_SAMPLES}
```

[ORIGINAL QUERY]
```sql
{QUERY}
```

[QUERY PLAN]
```json
{QUERY_PLAN}
```
