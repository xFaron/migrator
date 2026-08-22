You will be given a relational database schema representing an **initial database**.

Your task is to generate a **new target database schema** and, for every table in that new schema, a single `SELECT` query that produces the complete set of rows and columns for that table directly from the initial database.

## Input

You will receive the initial database schema, containing:

- Table names
- Column names
- Data types
- Primary keys
- Foreign keys
- Other constraints

## Task

### 1. Generate a New Database Schema

Design a new database containing one or more tables.

The new schema may be:

- **More concrete:** Interpret generic tables as real-world entities.
- **More specific:** Specialize a general schema into a particular domain.
- **Semantically transformed:** Give the data a different but reasonable interpretation.
- **Randomly generated:** Create a plausible schema with a new interpretation.

You may:

- Rename tables and columns.
- Split a source table into multiple target tables.
- Combine information from multiple source tables.
- Add derived columns.
- Change data types where appropriate.
- Create new relationships between tables.
- Generate values using constants or deterministic SQL expressions.

The target schema should be realistically derivable from the source data wherever possible.

### 2. Generate a Table Population Query for Each Target Table

For **every table in the target schema**, write exactly **one `SELECT` query** that produces every row and every column needed to populate that table.

Each query must:

- Be a single `SELECT` statement — never `INSERT`, `CREATE`, `UPDATE`, or multiple statements separated by `;`.
- Return exactly one output column per column in the target table.
- Alias each output column with its exact target column name, and list columns in the same order as the target table's `CREATE TABLE` definition.
- Be fully self-contained and directly executable against the **initial database only**. It must not reference any other target table, since target tables do not exist yet — only the initial schema is available when these queries run.
- Use whatever SQL is needed to derive the data: `JOIN`, `WHERE`, `GROUP BY`, `HAVING`, `CASE`, `CAST`/`::`, arithmetic and string expressions, aggregates, window functions, subqueries, CTEs, constants, and SQL functions.

Additional guidance:

- If a target column can't be directly derived from the source data, fill it with a deterministic constant or expression (e.g. `NULL`, a literal default, `ROW_NUMBER()` over a stable order) — every column must still appear in the output.
- Prefer deterministic, reproducible expressions. Avoid non-deterministic functions (`RANDOM()`, `NOW()`, etc.) unless the column is explicitly meant to represent generation time.
- When a target table's primary or foreign key must line up with a key produced by another table's query (to preserve the relationship after the data is loaded), derive both from the same stable source identifier — don't use a value, like a `ROW_NUMBER()` over an arbitrary or table-local order, that could differ between the two queries.
- Match each column's SQL result type to its declared type in the target schema, casting where necessary.
- Write standard PostgreSQL-compatible SQL, since the initial database is PostgreSQL.

---

## Output Format

Return the result as JSON:

```json
{
  "target_database_schema": "-- CREATE TABLE statements",
  "table_generation_queries": [
    {
      "target_table": "<table_name>",
      "query": "SELECT <expr> AS <column_name>, <expr> AS <next_column_name>, ... FROM ... [JOIN ...] [WHERE ...];"
    }
  ]
}
```

`table_generation_queries` must contain exactly one entry per table in `target_database_schema`, in the same order the tables are declared.

Do not include explanations outside the JSON.

# Initial Database Schema

```json
{DB_SCHEMA}
```