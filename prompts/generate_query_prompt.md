You will be given the schema of a relational database (as PostgreSQL DDL produced by `pg_dump --schema-only`) and an integer K.

Your task is to generate exactly **K** valid, diverse SQL queries that can be executed against this schema.

## Requirements

- Queries must be syntactically valid and executable against the provided schema.
- Do not reference tables or columns not present in the schema.
- Each query must return at least one row against a reasonably populated database.
- Aim for diversity across query types: simple selections, multi-table joins, aggregations, `GROUP BY`, `HAVING`, subqueries, CTEs (`WITH`), `CASE` expressions, date operations, correlated subqueries.
- Use foreign-key relationships to construct meaningful joins where applicable.
- Avoid trivial variations of the same query.

**Important** : All the names of the tables and columns should not be taken incorrectly into the query.

## Output Format

Return **only** a JSON object — no text or explanations outside of it:

```json
{
  "queries": [
    { "id": 1, "query": "SELECT ..." },
    { "id": 2, "query": "SELECT ..." }
  ]
}
```

The array must contain exactly K entries. Write each query as a single-line string.

## Example

**Schema** (as produced by `pg_dump --schema-only`):

```sql
CREATE TABLE public.nation (
    n_nationkey integer NOT NULL,
    n_name character(25),
    PRIMARY KEY (n_nationkey)
);

CREATE TABLE public.customer (
    c_custkey integer NOT NULL,
    c_name character varying(25),
    c_nationkey integer,
    c_acctbal numeric,
    PRIMARY KEY (c_custkey)
);
ALTER TABLE ONLY public.customer
    ADD CONSTRAINT customer_c_nationkey_fkey FOREIGN KEY (c_nationkey) REFERENCES public.nation(n_nationkey);

CREATE TABLE public.orders (
    o_orderkey integer NOT NULL,
    o_custkey integer,
    o_orderdate date,
    o_totalprice numeric,
    PRIMARY KEY (o_orderkey)
);
ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_o_custkey_fkey FOREIGN KEY (o_custkey) REFERENCES public.customer(c_custkey);
```

**K = 2**

**Output:**

```json
{
  "queries": [
    {
      "id": 1,
      "query": "SELECT n.n_name, COUNT(c.c_custkey) AS num_customers, AVG(c.c_acctbal) AS avg_balance FROM customer c JOIN nation n ON c.c_nationkey = n.n_nationkey GROUP BY n.n_name ORDER BY num_customers DESC"
    },
    {
      "id": 2,
      "query": "SELECT c.c_name, SUM(o.o_totalprice) AS total_spent FROM customer c JOIN orders o ON c.c_custkey = o.o_custkey WHERE o.o_orderdate >= '1995-01-01' GROUP BY c.c_custkey, c.c_name HAVING SUM(o.o_totalprice) > 10000 ORDER BY total_spent DESC"
    }
  ]
}
```

---

## Database Schema

```sql
{DB_SCHEMA}
```

## Number of Queries

K = {K}
