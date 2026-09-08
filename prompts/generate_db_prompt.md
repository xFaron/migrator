You will be given a relational database schema representing an **initial PostgreSQL database**.

Your task is to generate a **new target database schema** with a meaningful and potentially different interpretation of the source data, and, for every table in that target schema, generate exactly one `SELECT` query that derives the complete contents of that table directly from the initial database.

# Core Objective

Create a realistic, semantically meaningful, and **non-trivial target database by performing substantial relational transformations on the initial schema**.

The target database should not merely rename, reorder, or lightly filter the original tables. Instead, it should **reinterpret, restructure, specialize, combine, split, derive, normalize, denormalize, aggregate, or otherwise transform** the source data into a coherent relational domain.

The primary goal is to make the transformation **challenging and interesting to reconstruct manually**. A person translating the initial database into the target schema should need to reason carefully about how source columns and rows map to the target, rather than being able to produce the target through simple column selection or renaming.

Prefer transformations that involve **complex SQL expressions and non-trivial relational relationships**, such as derived columns, conditional logic, string/date/numeric transformations, aggregations, window functions, joins across multiple source tables, many-to-one and many-to-many relationships, composite keys, primary/foreign-key dependencies, and tables whose contents are derived from combinations or summaries of several source tables.

The target schema should ideally contain **rich inter-table relationships**, with primary keys, foreign keys, and meaningful dependencies between derived tables. Target tables may contain values that require substantial computation from multiple source columns or rows.

The generated target database may represent a different domain from the original database, provided that the transformation remains **logically plausible, deterministic, and fully derivable from the initial database**.

Favor **structurally and computationally complex transformations over superficial renaming or formatting changes**. The resulting schema and queries should be realistic enough that manually translating the initial database into the target would be a substantial reasoning task.

# Input

You will receive the schema definition of an existing database. The schema describes the tables and relational structure available as the source for generating the target database.

The input may contain information such as:

- Schema name
- Table names
- Column names
- SQL data types
- Nullability / NOT NULL constraints
- Primary keys
- Foreign keys and their referenced tables and columns
- Unique constraints
- Check constraints
- Default expressions
- Generated columns
- Identity columns
- Indexes and their definitions
- Other relational constraints and metadata

The initial database information is available through the placeholder below, given as PostgreSQL DDL produced by `pg_dump --schema-only`:

```sql
{DB_SCHEMA}
```

Treat the schema represented above as the **source database**. All target tables must be generated solely from data available in this source database.

# Output Format

Return the result as JSON:

```json
{
  "target_database_schema": "-- CREATE TABLE statements ONLY",
  "table_generation_queries": [
    {
      "target_table": "<table_name>",
      "query": "SELECT <expr> AS <column_name>, <expr> AS <next_column_name>, ... FROM ... [JOIN ...] [WHERE ...];"
    }
  ]
}
```

## Target Database Schema

`target_database_schema` must **only** contain `CREATE TABLE` statements for **every target table**.

The target schema should explicitly define:

* Every target table
* Every target column
* The SQL data type of every target column
* Primary keys
* Foreign keys
* Unique constraints
* NOT NULL constraints
* Check constraints
* Other constraints that are part of the target relational design

Use valid PostgreSQL SQL.
**Note** : When generating Primary key or Foreign key constraints, define them using the `ALTER TABLE` command.
**Note** : When generating Foriegn key constraints, make sure that the foriegn key and the referenced key have the same type, and the referenced key is indeed a primary key.
**Note** : DO NOT USE `schema_name.table_name` format for the CREATE and SELECT queries. ONLY USE `table_name` in the queries, and the `schema` will be decided by the user.
**Note** : PostgreSQL: `DATE - DATE` returns the number of days as an integer; do not use `EXTRACT(DAY FROM ...)` on DATE differences.


## Table Generation Queries

`table_generation_queries` must contain **exactly one entry for every target table** defined in `target_database_schema`, in the same order that the target tables are declared.

Each generation query must generate the **complete contents of its corresponding target table directly from the source schema**.

This means that each query must explicitly generate:

* Every row of the target table
* Every target column
* The value of every target column

No target column may be left to a `DEFAULT`, identity, generated-column expression, or implicit database behavior. The generation query itself must produce the value that will be inserted into that column.

The expressions used for target columns may be arbitrarily complex and may involve:

* Multiple source tables
* Multiple joins
* Nested subqueries
* Aggregations
* Window functions
* Conditional expressions
* String, numeric, date/time, and JSON functions
* Derived values computed from multiple source columns
* Grouping and summarization
* Restructuring or combining source data
* Splitting or reshaping source data
* Any other deterministic PostgreSQL operations supported by the source data

The target tables and their columns must therefore be fully reconstructible from the source schema and the provided generation queries.

Every generation query must reference only the **initial/source schema**. It must not depend on another target table being generated first, and it must not read from the target schema.

The generation queries must be deterministic: running them against the same source database state must produce the same target-table contents.

Do not include explanations outside the JSON.