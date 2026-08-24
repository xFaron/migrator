You will be given a relational database schema representing an **initial PostgreSQL database**.

Your task is to generate a **new target database schema** with a meaningful but potentially different interpretation of the source data, and, for every table in that target schema, generate exactly one `SELECT` query that derives the complete contents of that table directly from the initial database.

# Core Objective

Create a realistic and semantically meaningful target database by transforming the initial schema.

The target database should not merely be a trivial renaming of the original tables. Instead, reinterpret, restructure, specialize, combine, or summarize the source data into a coherent relational domain.

The generated target schema should ideally contain meaningful relationships between tables and demonstrate a variety of relational transformations.

The target database may represent a different domain from the original database, as long as the transformation remains logically plausible and the target data can be deterministically derived from the initial database.

# Input

You will receive the initial database schema, containing information such as:

- Table names
- Column names
- SQL data types
- Primary keys
- Foreign keys
- Unique constraints
- NOT NULL constraints
- Other constraints

The initial schema is available through the placeholder:

```json
{DB_SCHEMA}
```

# Output Format

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