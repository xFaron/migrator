You will be given the schema of a relational database.

Your task is to generate **K SQL queries** that can be executed against this database.

The goal is to generate a diverse set of queries that meaningfully exercise the database schema.

## Input

You will receive:

1. A database schema.
2. An integer `K`, specifying the number of queries to generate.

The schema may contain:

* Multiple tables
* Primary keys
* Foreign keys
* Different data types
* Constraints and relationships

## Task

Generate exactly **K** valid SQL queries based on the provided database schema.

The queries should be:

* Syntactically valid.
* Semantically meaningful for the given schema.
* Executable against the provided database.
* Diverse in structure and complexity.

Prefer generating a mixture of query types, such as:

* Simple selections and filtering
* Multi-table joins
* Aggregations
* `GROUP BY`
* `HAVING`
* Sorting and limiting
* Subqueries
* Correlated subqueries
* Common table expressions (`WITH`)
* Conditional expressions (`CASE`)
* Date/time operations
* Aggregate comparisons
* Queries involving multiple relationships

Do not generate queries that require tables or columns not present in the schema.

Avoid generating many queries that are trivial variations of one another.

Queries should use the actual semantics implied by the schema whenever possible rather than arbitrary operations.

## Query Diversity

Across the K queries, aim for a reasonable distribution of complexity:

* Some simple queries
* Some intermediate queries
* Some complex analytical queries

Prefer queries that demonstrate different ways of navigating the relationships in the schema.

When foreign-key relationships exist, use them to construct meaningful joins where appropriate.

## Output Format

Return the result as JSON:

```json
{
  "queries": [
    {
      "id": 1,
      "query": "SELECT ..."
    },
    {
      "id": 2,
      "query": "SELECT ..."
    }
  ]
}
```

The output must contain exactly `K` queries.

Do not include explanations outside the JSON.

## Examples

### Input

```sql
CREATE TABLE PART (

	P_PARTKEY		SERIAL,
	P_NAME			VARCHAR(55),
	P_MFGR			CHAR(25),
	P_BRAND			CHAR(10),
	P_TYPE			VARCHAR(25),
	P_SIZE			INTEGER,
	P_CONTAINER		CHAR(10),
	P_RETAILPRICE	DECIMAL,
	P_COMMENT		VARCHAR(23)
);

CREATE TABLE SUPPLIER (
	S_SUPPKEY		SERIAL,
	S_NAME			CHAR(25),
	S_ADDRESS		VARCHAR(40),
	S_NATIONKEY		INTEGER NOT NULL, -- references N_NATIONKEY
	S_PHONE			CHAR(15),
	S_ACCTBAL		DECIMAL,
	S_COMMENT		VARCHAR(101)
);

CREATE TABLE PARTSUPP (
	PS_PARTKEY		INTEGER NOT NULL, -- references P_PARTKEY
	PS_SUPPKEY		INTEGER NOT NULL, -- references S_SUPPKEY
	PS_AVAILQTY		INTEGER,
	PS_SUPPLYCOST	DECIMAL,
	PS_COMMENT		VARCHAR(199)
);

CREATE TABLE CUSTOMER (
	C_CUSTKEY		SERIAL,
	C_NAME			VARCHAR(25),
	C_ADDRESS		VARCHAR(40),
	C_NATIONKEY		INTEGER NOT NULL, -- references N_NATIONKEY
	C_PHONE			CHAR(15),
	C_ACCTBAL		DECIMAL,
	C_MKTSEGMENT	CHAR(10),
	C_COMMENT		VARCHAR(117)
);

CREATE TABLE ORDERS (
	O_ORDERKEY		SERIAL,
	O_CUSTKEY		INTEGER NOT NULL, -- references C_CUSTKEY
	O_ORDERSTATUS	CHAR(1),
	O_TOTALPRICE	DECIMAL,
	O_ORDERDATE		DATE,
	O_ORDERPRIORITY	CHAR(15),
	O_CLERK			CHAR(15),
	O_SHIPPRIORITY	INTEGER,
	O_COMMENT		VARCHAR(79)
);

CREATE TABLE LINEITEM (
	L_ORDERKEY		INTEGER NOT NULL, -- references O_ORDERKEY
	L_PARTKEY		INTEGER NOT NULL, -- references P_PARTKEY (compound fk to PARTSUPP)
	L_SUPPKEY		INTEGER NOT NULL, -- references S_SUPPKEY (compound fk to PARTSUPP)
	L_LINENUMBER	INTEGER,
	L_QUANTITY		DECIMAL,
	L_EXTENDEDPRICE	DECIMAL,
	L_DISCOUNT		DECIMAL,
	L_TAX			DECIMAL,
	L_RETURNFLAG	CHAR(1),
	L_LINESTATUS	CHAR(1),
	L_SHIPDATE		DATE,
	L_COMMITDATE	DATE,
	L_RECEIPTDATE	DATE,
	L_SHIPINSTRUCT	CHAR(25),
	L_SHIPMODE		CHAR(10),
	L_COMMENT		VARCHAR(44)
);

CREATE TABLE NATION (
	N_NATIONKEY		SERIAL,
	N_NAME			CHAR(25),
	N_REGIONKEY		INTEGER NOT NULL,  -- references R_REGIONKEY
	N_COMMENT		VARCHAR(152)
);

CREATE TABLE REGION (
	R_REGIONKEY	SERIAL,
	R_NAME		CHAR(25),
	R_COMMENT	VARCHAR(152)
);
```

K = 22

### Output

```json
{
  "queries": [
    {
      "id": 1,
      "query": "-- $ID$\n-- TPC-H/TPC-R Pricing Summary Report Query (Q1)\n-- Functional Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\tl_returnflag,\n\tl_linestatus,\n\tsum(l_quantity) as sum_qty,\n\tsum(l_extendedprice) as sum_base_price,\n\tsum(l_extendedprice * (1 - l_discount)) as sum_disc_price,\n\tsum(l_extendedprice * (1 - l_discount) * (1 + l_tax)) as sum_charge,\n\tavg(l_quantity) as avg_qty,\n\tavg(l_extendedprice) as avg_price,\n\tavg(l_discount) as avg_disc,\n\tcount(*) as count_order\nfrom\n\tlineitem\nwhere\n\tl_shipdate <= date '1998-12-01' - interval ':1' day (3)\ngroup by\n\tl_returnflag,\n\tl_linestatus\norder by\n\tl_returnflag,\n\tl_linestatus;\n:n -1\n"
    },
    {
      "id": 2,
      "query": "-- $ID$\n-- TPC-H/TPC-R Minimum Cost Supplier Query (Q2)\n-- Functional Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\ts_acctbal,\n\ts_name,\n\tn_name,\n\tp_partkey,\n\tp_mfgr,\n\ts_address,\n\ts_phone,\n\ts_comment\nfrom\n\tpart,\n\tsupplier,\n\tpartsupp,\n\tnation,\n\tregion\nwhere\n\tp_partkey = ps_partkey\n\tand s_suppkey = ps_suppkey\n\tand p_size = :1\n\tand p_type like '%:2'\n\tand s_nationkey = n_nationkey\n\tand n_regionkey = r_regionkey\n\tand r_name = ':3'\n\tand ps_supplycost = (\n\t\tselect\n\t\t\tmin(ps_supplycost)\n\t\tfrom\n\t\t\tpartsupp,\n\t\t\tsupplier,\n\t\t\tnation,\n\t\t\tregion\n\t\twhere\n\t\t\tp_partkey = ps_partkey\n\t\t\tand s_suppkey = ps_suppkey\n\t\t\tand s_nationkey = n_nationkey\n\t\t\tand n_regionkey = r_regionkey\n\t\t\tand r_name = ':3'\n\t)\norder by\n\ts_acctbal desc,\n\tn_name,\n\ts_name,\n\tp_partkey;\n:n 100\n"
    },
    {
      "id": 3,
      "query": "-- $ID$\n-- TPC-H/TPC-R Shipping Priority Query (Q3)\n-- Functional Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\tl_orderkey,\n\tsum(l_extendedprice * (1 - l_discount)) as revenue,\n\to_orderdate,\n\to_shippriority\nfrom\n\tcustomer,\n\torders,\n\tlineitem\nwhere\n\tc_mktsegment = ':1'\n\tand c_custkey = o_custkey\n\tand l_orderkey = o_orderkey\n\tand o_orderdate < date ':2'\n\tand l_shipdate > date ':2'\ngroup by\n\tl_orderkey,\n\to_orderdate,\n\to_shippriority\norder by\n\trevenue desc,\n\to_orderdate;\n:n 10\n"
    },
    {
      "id": 4,
      "query": "-- $ID$\n-- TPC-H/TPC-R Order Priority Checking Query (Q4)\n-- Functional Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\to_orderpriority,\n\tcount(*) as order_count\nfrom\n\torders\nwhere\n\to_orderdate >= date ':1'\n\tand o_orderdate < date ':1' + interval '3' month\n\tand exists (\n\t\tselect\n\t\t\t*\n\t\tfrom\n\t\t\tlineitem\n\t\twhere\n\t\t\tl_orderkey = o_orderkey\n\t\t\tand l_commitdate < l_receiptdate\n\t)\ngroup by\n\to_orderpriority\norder by\n\to_orderpriority;\n:n -1\n"
    },
    {
      "id": 5,
      "query": "-- $ID$\n-- TPC-H/TPC-R Local Supplier Volume Query (Q5)\n-- Functional Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\tn_name,\n\tsum(l_extendedprice * (1 - l_discount)) as revenue\nfrom\n\tcustomer,\n\torders,\n\tlineitem,\n\tsupplier,\n\tnation,\n\tregion\nwhere\n\tc_custkey = o_custkey\n\tand l_orderkey = o_orderkey\n\tand l_suppkey = s_suppkey\n\tand c_nationkey = s_nationkey\n\tand s_nationkey = n_nationkey\n\tand n_regionkey = r_regionkey\n\tand r_name = ':1'\n\tand o_orderdate >= date ':2'\n\tand o_orderdate < date ':2' + interval '1' year\ngroup by\n\tn_name\norder by\n\trevenue desc;\n:n -1\n"
    },
    {
      "id": 6,
      "query": "-- $ID$\n-- TPC-H/TPC-R Forecasting Revenue Change Query (Q6)\n-- Functional Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\tsum(l_extendedprice * l_discount) as revenue\nfrom\n\tlineitem\nwhere\n\tl_shipdate >= date ':1'\n\tand l_shipdate < date ':1' + interval '1' year\n\tand l_discount between :2 - 0.01 and :2 + 0.01\n\tand l_quantity < :3;\n:n -1\n"
    },
    {
      "id": 7,
      "query": "-- $ID$\n-- TPC-H/TPC-R Volume Shipping Query (Q7)\n-- Functional Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\tsupp_nation,\n\tcust_nation,\n\tl_year,\n\tsum(volume) as revenue\nfrom\n\t(\n\t\tselect\n\t\t\tn1.n_name as supp_nation,\n\t\t\tn2.n_name as cust_nation,\n\t\t\textract(year from l_shipdate) as l_year,\n\t\t\tl_extendedprice * (1 - l_discount) as volume\n\t\tfrom\n\t\t\tsupplier,\n\t\t\tlineitem,\n\t\t\torders,\n\t\t\tcustomer,\n\t\t\tnation n1,\n\t\t\tnation n2\n\t\twhere\n\t\t\ts_suppkey = l_suppkey\n\t\t\tand o_orderkey = l_orderkey\n\t\t\tand c_custkey = o_custkey\n\t\t\tand s_nationkey = n1.n_nationkey\n\t\t\tand c_nationkey = n2.n_nationkey\n\t\t\tand (\n\t\t\t\t(n1.n_name = ':1' and n2.n_name = ':2')\n\t\t\t\tor (n1.n_name = ':2' and n2.n_name = ':1')\n\t\t\t)\n\t\t\tand l_shipdate between date '1995-01-01' and date '1996-12-31'\n\t) as shipping\ngroup by\n\tsupp_nation,\n\tcust_nation,\n\tl_year\norder by\n\tsupp_nation,\n\tcust_nation,\n\tl_year;\n:n -1\n"
    },
    {
      "id": 8,
      "query": "-- $ID$\n-- TPC-H/TPC-R National Market Share Query (Q8)\n-- Functional Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\to_year,\n\tsum(case\n\t\twhen nation = ':1' then volume\n\t\telse 0\n\tend) / sum(volume) as mkt_share\nfrom\n\t(\n\t\tselect\n\t\t\textract(year from o_orderdate) as o_year,\n\t\t\tl_extendedprice * (1 - l_discount) as volume,\n\t\t\tn2.n_name as nation\n\t\tfrom\n\t\t\tpart,\n\t\t\tsupplier,\n\t\t\tlineitem,\n\t\t\torders,\n\t\t\tcustomer,\n\t\t\tnation n1,\n\t\t\tnation n2,\n\t\t\tregion\n\t\twhere\n\t\t\tp_partkey = l_partkey\n\t\t\tand s_suppkey = l_suppkey\n\t\t\tand l_orderkey = o_orderkey\n\t\t\tand o_custkey = c_custkey\n\t\t\tand c_nationkey = n1.n_nationkey\n\t\t\tand n1.n_regionkey = r_regionkey\n\t\t\tand r_name = ':2'\n\t\t\tand s_nationkey = n2.n_nationkey\n\t\t\tand o_orderdate between date '1995-01-01' and date '1996-12-31'\n\t\t\tand p_type = ':3'\n\t) as all_nations\ngroup by\n\to_year\norder by\n\to_year;\n:n -1\n"
    },
    {
      "id": 9,
      "query": "-- $ID$\n-- TPC-H/TPC-R Product Type Profit Measure Query (Q9)\n-- Functional Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\tnation,\n\to_year,\n\tsum(amount) as sum_profit\nfrom\n\t(\n\t\tselect\n\t\t\tn_name as nation,\n\t\t\textract(year from o_orderdate) as o_year,\n\t\t\tl_extendedprice * (1 - l_discount) - ps_supplycost * l_quantity as amount\n\t\tfrom\n\t\t\tpart,\n\t\t\tsupplier,\n\t\t\tlineitem,\n\t\t\tpartsupp,\n\t\t\torders,\n\t\t\tnation\n\t\twhere\n\t\t\ts_suppkey = l_suppkey\n\t\t\tand ps_suppkey = l_suppkey\n\t\t\tand ps_partkey = l_partkey\n\t\t\tand p_partkey = l_partkey\n\t\t\tand o_orderkey = l_orderkey\n\t\t\tand s_nationkey = n_nationkey\n\t\t\tand p_name like '%:1%'\n\t) as profit\ngroup by\n\tnation,\n\to_year\norder by\n\tnation,\n\to_year desc;\n:n -1\n"
    },
    {
      "id": 10,
      "query": "-- $ID$\n-- TPC-H/TPC-R Returned Item Reporting Query (Q10)\n-- Functional Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\tc_custkey,\n\tc_name,\n\tsum(l_extendedprice * (1 - l_discount)) as revenue,\n\tc_acctbal,\n\tn_name,\n\tc_address,\n\tc_phone,\n\tc_comment\nfrom\n\tcustomer,\n\torders,\n\tlineitem,\n\tnation\nwhere\n\tc_custkey = o_custkey\n\tand l_orderkey = o_orderkey\n\tand o_orderdate >= date ':1'\n\tand o_orderdate < date ':1' + interval '3' month\n\tand l_returnflag = 'R'\n\tand c_nationkey = n_nationkey\ngroup by\n\tc_custkey,\n\tc_name,\n\tc_acctbal,\n\tc_phone,\n\tn_name,\n\tc_address,\n\tc_comment\norder by\n\trevenue desc;\n:n 20\n"
    },
    {
      "id": 11,
      "query": "-- $ID$\n-- TPC-H/TPC-R Important Stock Identification Query (Q11)\n-- Functional Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\tps_partkey,\n\tsum(ps_supplycost * ps_availqty) as value\nfrom\n\tpartsupp,\n\tsupplier,\n\tnation\nwhere\n\tps_suppkey = s_suppkey\n\tand s_nationkey = n_nationkey\n\tand n_name = ':1'\ngroup by\n\tps_partkey having\n\t\tsum(ps_supplycost * ps_availqty) > (\n\t\t\tselect\n\t\t\t\tsum(ps_supplycost * ps_availqty) * :2\n\t\t\tfrom\n\t\t\t\tpartsupp,\n\t\t\t\tsupplier,\n\t\t\t\tnation\n\t\t\twhere\n\t\t\t\tps_suppkey = s_suppkey\n\t\t\t\tand s_nationkey = n_nationkey\n\t\t\t\tand n_name = ':1'\n\t\t)\norder by\n\tvalue desc;\n:n -1\n"
    },
    {
      "id": 12,
      "query": "-- $ID$\n-- TPC-H/TPC-R Shipping Modes and Order Priority Query (Q12)\n-- Functional Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\tl_shipmode,\n\tsum(case\n\t\twhen o_orderpriority = '1-URGENT'\n\t\t\tor o_orderpriority = '2-HIGH'\n\t\t\tthen 1\n\t\telse 0\n\tend) as high_line_count,\n\tsum(case\n\t\twhen o_orderpriority <> '1-URGENT'\n\t\t\tand o_orderpriority <> '2-HIGH'\n\t\t\tthen 1\n\t\telse 0\n\tend) as low_line_count\nfrom\n\torders,\n\tlineitem\nwhere\n\to_orderkey = l_orderkey\n\tand l_shipmode in (':1', ':2')\n\tand l_commitdate < l_receiptdate\n\tand l_shipdate < l_commitdate\n\tand l_receiptdate >= date ':3'\n\tand l_receiptdate < date ':3' + interval '1' year\ngroup by\n\tl_shipmode\norder by\n\tl_shipmode;\n:n -1\n"
    },
    {
      "id": 13,
      "query": "-- $ID$\n-- TPC-H/TPC-R Customer Distribution Query (Q13)\n-- Functional Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\tc_count,\n\tcount(*) as custdist\nfrom\n\t(\n\t\tselect\n\t\t\tc_custkey,\n\t\t\tcount(o_orderkey)\n\t\tfrom\n\t\t\tcustomer left outer join orders on\n\t\t\t\tc_custkey = o_custkey\n\t\t\t\tand o_comment not like '%:1%:2%'\n\t\tgroup by\n\t\t\tc_custkey\n\t) as c_orders (c_custkey, c_count)\ngroup by\n\tc_count\norder by\n\tcustdist desc,\n\tc_count desc;\n:n -1\n"
    },
    {
      "id": 14,
      "query": "-- $ID$\n-- TPC-H/TPC-R Promotion Effect Query (Q14)\n-- Functional Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\t100.00 * sum(case\n\t\twhen p_type like 'PROMO%'\n\t\t\tthen l_extendedprice * (1 - l_discount)\n\t\telse 0\n\tend) / sum(l_extendedprice * (1 - l_discount)) as promo_revenue\nfrom\n\tlineitem,\n\tpart\nwhere\n\tl_partkey = p_partkey\n\tand l_shipdate >= date ':1'\n\tand l_shipdate < date ':1' + interval '1' month;\n:n -1\n"
    },
    {
      "id": 15,
      "query": "-- $ID$\n-- TPC-H/TPC-R Top Supplier Query (Q15)\n-- Functional Query Definition\n-- Approved February 1998\n:x\ncreate view revenue:s (supplier_no, total_revenue) as\n\tselect\n\t\tl_suppkey,\n\t\tsum(l_extendedprice * (1 - l_discount))\n\tfrom\n\t\tlineitem\n\twhere\n\t\tl_shipdate >= date ':1'\n\t\tand l_shipdate < date ':1' + interval '3' month\n\tgroup by\n\t\tl_suppkey;\n\n:o\nselect\n\ts_suppkey,\n\ts_name,\n\ts_address,\n\ts_phone,\n\ttotal_revenue\nfrom\n\tsupplier,\n\trevenue:s\nwhere\n\ts_suppkey = supplier_no\n\tand total_revenue = (\n\t\tselect\n\t\t\tmax(total_revenue)\n\t\tfrom\n\t\t\trevenue:s\n\t)\norder by\n\ts_suppkey;\n\ndrop view revenue:s;\n:n -1\n"
    },
    {
      "id": 16,
      "query": "-- $ID$\n-- TPC-H/TPC-R Parts/Supplier Relationship Query (Q16)\n-- Functional Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\tp_brand,\n\tp_type,\n\tp_size,\n\tcount(distinct ps_suppkey) as supplier_cnt\nfrom\n\tpartsupp,\n\tpart\nwhere\n\tp_partkey = ps_partkey\n\tand p_brand <> ':1'\n\tand p_type not like ':2%'\n\tand p_size in (:3, :4, :5, :6, :7, :8, :9, :10)\n\tand ps_suppkey not in (\n\t\tselect\n\t\t\ts_suppkey\n\t\tfrom\n\t\t\tsupplier\n\t\twhere\n\t\t\ts_comment like '%Customer%Complaints%'\n\t)\ngroup by\n\tp_brand,\n\tp_type,\n\tp_size\norder by\n\tsupplier_cnt desc,\n\tp_brand,\n\tp_type,\n\tp_size;\n:n -1\n"
    },
    {
      "id": 17,
      "query": "-- $ID$\n-- TPC-H/TPC-R Small-Quantity-Order Revenue Query (Q17)\n-- Functional Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\tsum(l_extendedprice) / 7.0 as avg_yearly\nfrom\n\tlineitem,\n\tpart\nwhere\n\tp_partkey = l_partkey\n\tand p_brand = ':1'\n\tand p_container = ':2'\n\tand l_quantity < (\n\t\tselect\n\t\t\t0.2 * avg(l_quantity)\n\t\tfrom\n\t\t\tlineitem\n\t\twhere\n\t\t\tl_partkey = p_partkey\n\t);\n:n -1\n"
    },
    {
      "id": 18,
      "query": "-- $ID$\n-- TPC-H/TPC-R Large Volume Customer Query (Q18)\n-- Function Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\tc_name,\n\tc_custkey,\n\to_orderkey,\n\to_orderdate,\n\to_totalprice,\n\tsum(l_quantity)\nfrom\n\tcustomer,\n\torders,\n\tlineitem\nwhere\n\to_orderkey in (\n\t\tselect\n\t\t\tl_orderkey\n\t\tfrom\n\t\t\tlineitem\n\t\tgroup by\n\t\t\tl_orderkey having\n\t\t\t\tsum(l_quantity) > :1\n\t)\n\tand c_custkey = o_custkey\n\tand o_orderkey = l_orderkey\ngroup by\n\tc_name,\n\tc_custkey,\n\to_orderkey,\n\to_orderdate,\n\to_totalprice\norder by\n\to_totalprice desc,\n\to_orderdate;\n:n 100\n"
    },
    {
      "id": 19,
      "query": "-- $ID$\n-- TPC-H/TPC-R Discounted Revenue Query (Q19)\n-- Functional Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\tsum(l_extendedprice* (1 - l_discount)) as revenue\nfrom\n\tlineitem,\n\tpart\nwhere\n\t(\n\t\tp_partkey = l_partkey\n\t\tand p_brand = ':1'\n\t\tand p_container in ('SM CASE', 'SM BOX', 'SM PACK', 'SM PKG')\n\t\tand l_quantity >= :4 and l_quantity <= :4 + 10\n\t\tand p_size between 1 and 5\n\t\tand l_shipmode in ('AIR', 'AIR REG')\n\t\tand l_shipinstruct = 'DELIVER IN PERSON'\n\t)\n\tor\n\t(\n\t\tp_partkey = l_partkey\n\t\tand p_brand = ':2'\n\t\tand p_container in ('MED BAG', 'MED BOX', 'MED PKG', 'MED PACK')\n\t\tand l_quantity >= :5 and l_quantity <= :5 + 10\n\t\tand p_size between 1 and 10\n\t\tand l_shipmode in ('AIR', 'AIR REG')\n\t\tand l_shipinstruct = 'DELIVER IN PERSON'\n\t)\n\tor\n\t(\n\t\tp_partkey = l_partkey\n\t\tand p_brand = ':3'\n\t\tand p_container in ('LG CASE', 'LG BOX', 'LG PACK', 'LG PKG')\n\t\tand l_quantity >= :6 and l_quantity <= :6 + 10\n\t\tand p_size between 1 and 15\n\t\tand l_shipmode in ('AIR', 'AIR REG')\n\t\tand l_shipinstruct = 'DELIVER IN PERSON'\n\t);\n:n -1\n"
    },
    {
      "id": 20,
      "query": "-- $ID$\n-- TPC-H/TPC-R Potential Part Promotion Query (Q20)\n-- Function Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\ts_name,\n\ts_address\nfrom\n\tsupplier,\n\tnation\nwhere\n\ts_suppkey in (\n\t\tselect\n\t\t\tps_suppkey\n\t\tfrom\n\t\t\tpartsupp\n\t\twhere\n\t\t\tps_partkey in (\n\t\t\t\tselect\n\t\t\t\t\tp_partkey\n\t\t\t\tfrom\n\t\t\t\t\tpart\n\t\t\t\twhere\n\t\t\t\t\tp_name like ':1%'\n\t\t\t)\n\t\t\tand ps_availqty > (\n\t\t\t\tselect\n\t\t\t\t\t0.5 * sum(l_quantity)\n\t\t\t\tfrom\n\t\t\t\t\tlineitem\n\t\t\t\twhere\n\t\t\t\t\tl_partkey = ps_partkey\n\t\t\t\t\tand l_suppkey = ps_suppkey\n\t\t\t\t\tand l_shipdate >= date ':2'\n\t\t\t\t\tand l_shipdate < date ':2' + interval '1' year\n\t\t\t)\n\t)\n\tand s_nationkey = n_nationkey\n\tand n_name = ':3'\norder by\n\ts_name;\n:n -1\n"
    },
    {
      "id": 21,
      "query": "-- $ID$\n-- TPC-H/TPC-R Suppliers Who Kept Orders Waiting Query (Q21)\n-- Functional Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\ts_name,\n\tcount(*) as numwait\nfrom\n\tsupplier,\n\tlineitem l1,\n\torders,\n\tnation\nwhere\n\ts_suppkey = l1.l_suppkey\n\tand o_orderkey = l1.l_orderkey\n\tand o_orderstatus = 'F'\n\tand l1.l_receiptdate > l1.l_commitdate\n\tand exists (\n\t\tselect\n\t\t\t*\n\t\tfrom\n\t\t\tlineitem l2\n\t\twhere\n\t\t\tl2.l_orderkey = l1.l_orderkey\n\t\t\tand l2.l_suppkey <> l1.l_suppkey\n\t)\n\tand not exists (\n\t\tselect\n\t\t\t*\n\t\tfrom\n\t\t\tlineitem l3\n\t\twhere\n\t\t\tl3.l_orderkey = l1.l_orderkey\n\t\t\tand l3.l_suppkey <> l1.l_suppkey\n\t\t\tand l3.l_receiptdate > l3.l_commitdate\n\t)\n\tand s_nationkey = n_nationkey\n\tand n_name = ':1'\ngroup by\n\ts_name\norder by\n\tnumwait desc,\n\ts_name;\n:n 100\n"
    },
    {
      "id": 22,
      "query": "-- $ID$\n-- TPC-H/TPC-R Global Sales Opportunity Query (Q22)\n-- Functional Query Definition\n-- Approved February 1998\n:x\n:o\nselect\n\tcntrycode,\n\tcount(*) as numcust,\n\tsum(c_acctbal) as totacctbal\nfrom\n\t(\n\t\tselect\n\t\t\tsubstring(c_phone from 1 for 2) as cntrycode,\n\t\t\tc_acctbal\n\t\tfrom\n\t\t\tcustomer\n\t\twhere\n\t\t\tsubstring(c_phone from 1 for 2) in\n\t\t\t\t(':1', ':2', ':3', ':4', ':5', ':6', ':7')\n\t\t\tand c_acctbal > (\n\t\t\t\tselect\n\t\t\t\t\tavg(c_acctbal)\n\t\t\t\tfrom\n\t\t\t\t\tcustomer\n\t\t\t\twhere\n\t\t\t\t\tc_acctbal > 0.00\n\t\t\t\t\tand substring(c_phone from 1 for 2) in\n\t\t\t\t\t\t(':1', ':2', ':3', ':4', ':5', ':6', ':7')\n\t\t\t)\n\t\t\tand not exists (\n\t\t\t\tselect\n\t\t\t\t\t*\n\t\t\t\tfrom\n\t\t\t\t\torders\n\t\t\t\twhere\n\t\t\t\t\to_custkey = c_custkey\n\t\t\t)\n\t) as custsale\ngroup by\n\tcntrycode\norder by\n\tcntrycode;\n:n -1\n"
    }
  ]
}

```

## Database Schema

```sql
{DB_SCHEMA}
```

## Number of Queries

```text
K = {K}
```