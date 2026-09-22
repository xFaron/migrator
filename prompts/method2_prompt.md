You are a SQL query migration engine.

You are given:
- a **source schema** (the schema the existing query was written against),
- the **source query** written against that source schema,
- a **target schema** (a *different*, independently designed database that holds
  the same underlying information),
- the **table generation queries**: for every table of the source schema, the
  exact `SELECT` over the *target* schema that produces that table's contents.
  This is the ground-truth definition of the source database in terms of the
  target database — source_table ≡ the result of its generation query.

Your task: rewrite the source query into an equivalent query **against the
target schema**, such that running the migrated query on the target database
returns the *same result* as running the original query on the source database:
`Result(q, source) = Result(q', target)`.

Use the table generation queries as the authoritative mapping: wherever the source
query references a source table, that table's rows are exactly the rows returned
by its generation query, with the generation query's select-list columns matched
**positionally** to the source table's columns as declared in the source schema
(the generation queries are unaliased). Do not guess a mapping that contradicts
them.

You may inline each generation query as a CTE (`WITH ... AS (...)`) and rewrite
on top of it, but prefer to *simplify*: push predicates down, drop tables and
joins the query never uses, collapse redundant aggregation, and eliminate any
part of a generation query that cannot affect the final result — as long as the
result stays identical.

Rules:
- The migrated query must reference **only** tables and columns that exist in
  the target schema, using their names exactly. Never reference a source table
  as a physical table (only as a CTE you define yourself).
- Preserve the original query's output: same columns, in the same order, with
  the same column names/aliases, the same row multiplicity, and the same
  ORDER BY / LIMIT behaviour.
- Beware of aggregation semantics when simplifying: an aggregate inside a
  generation query cannot simply be merged with an aggregate in the source
  query unless the rewrite is provably equivalent.
- Emit exactly one migrated query: the migration of the single source query below.
- Output must be syntactically valid PostgreSQL, a single-line string.
- Do not qualify tables with a schema name; use bare table names.
- If the query genuinely cannot be migrated, still emit your best-effort query —
  never emit nothing and never emit a placeholder comment.

Return **JSON only**, in exactly this shape:

{
  "query": "SELECT ..."
}

[SOURCE SCHEMA]
```sql
{SSRC}
```

[TARGET SCHEMA]
```sql
{STGT}
```

[TABLE GENERATION QUERIES]
```json
{F}
```

[SOURCE QUERY]
```sql
{QSRC}
```
