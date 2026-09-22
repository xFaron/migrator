# Query Migration Evaluation Results

> **Pre-refactor record.** These results were produced before the source/target
> naming refactor, with the method framework's predecessors: `baseline_1` here is
> today's `method_1`, `baseline_2` is `method_2`, and `optim_query` has no successor
> method (it was removed, not renumbered). The field names below (`baseline_1_query`,
> `baseline_2_query`, `optim_query`, `analysis`) no longer exist in `queries.json`;
> see `README.md` for the current shape. Kept verbatim as a record of that run.

Correctness (equivalence rating vs. `raw_query`) and relative performance metrics per query, for test-case DBs that have completed `evaluate_queries.py`.

Equivalence scale (weakest to strongest): `INV` < `NEQ` < `DB_EQ` < `EQ`.

Relative metrics are only reported when equivalence is above `NEQ` (i.e. not `INV`/`NEQ`); otherwise the runtime/cost figures aren't meaningful comparisons and are omitted.

## Method definitions

Let $D'$ be the real source database and $D$ the LLM-generated target database, where each table $T \in D$ is defined by a mapping $f_T : D' \to T$ (a `SELECT` over $D'$, i.e. `table_generation_queries`), so $D = \{f_T(D')\}_{T \in D}$. Let $q \in Q$ be a query written against $D$.

- **`raw_query`** (ground truth): $q_{raw} = q[T \mapsto f_T]_{T \in D}$ — each table reference in $q$ is substituted, deterministically and exactly, by its defining CTE $f_T$, producing a query that runs on $D'$ alone with a provably identical result to $q$ on $D$. This is the reference every other method is checked against.
- **`baseline_1`**: $q'_1 = \mathrm{LLM}(q,\ \mathrm{schema}(D),\ \mathrm{schema}(D'),\ \mathrm{samples}(D'))$ — the LLM is given $q$ and the schemas of $D$ and $D'$ (plus sample rows of $D'$) but **not** $f$, and must infer the correspondence between $D$ and $D'$ itself before producing a query on $D'$.
- **`baseline_2`**: $q'_2 = \mathrm{LLM}(q,\ \mathrm{schema}(D),\ \mathrm{schema}(D'),\ \{f_T\}_{T \in D})$ — same as `baseline_1`, except the LLM is additionally handed the true mapping $\{f_T\}$, so it only has to apply a known correspondence rather than discover one.
- **`optim_query`**: $q_{opt} = \mathrm{LLM}(q_{raw})$ — not a migration at all; the LLM is asked to produce an optimized/rewritten form of `raw_query` itself (already a $D'$-only query), so it measures rewrite quality rather than cross-database correspondence.

## db3532

### Correctness (Equivalence)

| Query ID | raw_query (ground truth) | baseline_1 | baseline_2 | optim_query |
|---|---|---|---|---|
| 1 | EQ | NEQ | DB_EQ | DB_EQ |
| 2 | ERROR: Failed to measure raw_query: canceling statement due to stat | - | - | - |
| 3 | EQ | NEQ | DB_EQ | DB_EQ |
| 4 | EQ | NEQ | DB_EQ | DB_EQ |
| 5 | EQ | NEQ | DB_EQ | DB_EQ |
| 7 | EQ | DB_EQ | DB_EQ | DB_EQ |
| 8 | EQ | NEQ | DB_EQ | DB_EQ |
| 9 | EQ | NEQ | DB_EQ | NEQ |
| 10 | EQ | - | - | - |
| 11 | EQ | NEQ | DB_EQ | DB_EQ |
| 12 | EQ | NEQ | DB_EQ | DB_EQ |
| 13 | EQ | - | - | - |
| 15 | EQ | NEQ | DB_EQ | DB_EQ |

**Note:** Queries 10, 13 are blank for `baseline_1`/`baseline_2`/`optim_query` because their record has `error: "Raw query result does not match source query"`, and `baseline_1_query`/`baseline_2_query`/`optim_query` are `null` — those stages never ran for them.

### Relative Cost

| Query ID | raw_query (ground truth) | baseline_1 | baseline_2 | optim_query |
|---|---|---|---|---|
| 1 | 1.0000 | - | 0.7077 | 0.2178 |
| 2 | ERROR: Failed to measure raw_query: canceling statement due to stat | - | - | - |
| 3 | 1.0000 | - | 0.9917 | 0.9801 |
| 4 | 1.0000 | - | 1.0000 | 0.5808 |
| 5 | 1.0000 | - | 0.3671 | 0.3661 |
| 7 | 1.0000 | 0.9227 | 1.7449 | 1.6611 |
| 8 | 1.0000 | - | 0.9504 | 0.8765 |
| 9 | 1.0000 | - | 0.9635 | - |
| 10 | 1.0000 | - | - | - |
| 11 | 1.0000 | - | 0.5052 | 4.2881 |
| 12 | 1.0000 | - | 1.0000 | 0.5367 |
| 13 | 1.0000 | - | - | - |
| 15 | 1.0000 | - | 1.0000 | 1.0000 |

### Relative Cold Runtime

| Query ID | raw_query (ground truth) | baseline_1 | baseline_2 | optim_query |
|---|---|---|---|---|
| 1 | 1.0000 | - | 0.9580 | 0.9052 |
| 2 | ERROR: Failed to measure raw_query: canceling statement due to stat | - | - | - |
| 3 | 1.0000 | - | 0.9811 | 1.1649 |
| 4 | 1.0000 | - | 0.9963 | 0.2697 |
| 5 | 1.0000 | - | 0.3341 | 0.3685 |
| 7 | 1.0000 | 0.7711 | 0.8262 | 0.7695 |
| 8 | 1.0000 | - | 0.9617 | 1.2733 |
| 9 | 1.0000 | - | 0.9425 | - |
| 10 | 1.0000 | - | - | - |
| 11 | 1.0000 | - | 0.4526 | 0.4415 |
| 12 | 1.0000 | - | 1.0184 | 0.2934 |
| 13 | 1.0000 | - | - | - |
| 15 | 1.0000 | - | 1.0259 | 0.9899 |

### Relative Hot Runtime

| Query ID | raw_query (ground truth) | baseline_1 | baseline_2 | optim_query |
|---|---|---|---|---|
| 1 | 1.0000 | - | 0.9598 | 0.9078 |
| 2 | ERROR: Failed to measure raw_query: canceling statement due to stat | - | - | - |
| 3 | 1.0000 | - | 0.9843 | 0.5397 |
| 4 | 1.0000 | - | 1.0025 | 0.2026 |
| 5 | 1.0000 | - | 0.3059 | 0.3022 |
| 7 | 1.0000 | 0.7899 | 0.9139 | 0.7818 |
| 8 | 1.0000 | - | 1.0392 | 0.6870 |
| 9 | 1.0000 | - | 0.9629 | - |
| 10 | 1.0000 | - | - | - |
| 11 | 1.0000 | - | 0.4204 | 0.4162 |
| 12 | 1.0000 | - | 0.9991 | 0.2485 |
| 13 | 1.0000 | - | - | - |
| 15 | 1.0000 | - | 1.0049 | 1.0086 |

## db3631

### Correctness (Equivalence)

| Query ID | raw_query (ground truth) | baseline_1 | baseline_2 | optim_query |
|---|---|---|---|---|
| 1 | EQ | NEQ | NEQ | NEQ |
| 2 | EQ | DB_EQ | DB_EQ | DB_EQ |
| 4 | EQ | NEQ | INV | INV |
| 5 | ERROR: Failed to measure raw_query: connection failed: connection t | - | - | - |
| 6 | EQ | DB_EQ | DB_EQ | DB_EQ |
| 7 | EQ | DB_EQ | DB_EQ | DB_EQ |
| 9 | EQ | DB_EQ | DB_EQ | DB_EQ |
| 10 | EQ | NEQ | DB_EQ | DB_EQ |
| 11 | EQ | DB_EQ | DB_EQ | DB_EQ |
| 12 | EQ | - | - | - |
| 13 | EQ | DB_EQ | DB_EQ | DB_EQ |
| 14 | EQ | DB_EQ | DB_EQ | DB_EQ |
| 15 | EQ | DB_EQ | DB_EQ | DB_EQ |

**Note:** Query 12 is blank for `baseline_1`/`baseline_2`/`optim_query` because its record has `error: "Raw query result does not match source query"`, and `baseline_1_query`/`baseline_2_query`/`optim_query` are `null` — those stages never ran for it.

### Relative Cost

| Query ID | raw_query (ground truth) | baseline_1 | baseline_2 | optim_query |
|---|---|---|---|---|
| 1 | 1.0000 | - | - | - |
| 2 | 1.0000 | 0.0059 | 0.0064 | 0.0066 |
| 4 | 1.0000 | - | - | - |
| 5 | ERROR: Failed to measure raw_query: connection failed: connection t | - | - | - |
| 6 | 1.0000 | 0.8838 | 0.8158 | 1.1788 |
| 7 | 1.0000 | 0.0002 | 0.0003 | 0.0001 |
| 9 | 1.0000 | 0.0499 | 0.0577 | 0.1085 |
| 10 | 1.0000 | - | 0.7078 | 0.7744 |
| 11 | 1.0000 | 3.9408 | 0.0005 | 0.0005 |
| 12 | 1.0000 | - | - | - |
| 13 | 1.0000 | 0.8221 | 0.8348 | 0.8695 |
| 14 | 1.0000 | 0.6687 | 0.7388 | 0.8879 |
| 15 | 1.0000 | 0.7747 | 0.7904 | 0.7982 |

### Relative Cold Runtime

| Query ID | raw_query (ground truth) | baseline_1 | baseline_2 | optim_query |
|---|---|---|---|---|
| 1 | 1.0000 | - | - | - |
| 2 | 1.0000 | 0.1224 | 0.1631 | 0.1622 |
| 4 | 1.0000 | - | - | - |
| 5 | ERROR: Failed to measure raw_query: connection failed: connection t | - | - | - |
| 6 | 1.0000 | 0.7063 | 1.1995 | 1.2142 |
| 7 | 1.0000 | 0.3323 | 0.4821 | 0.0605 |
| 9 | 1.0000 | 0.1146 | 0.1761 | 0.2738 |
| 10 | 1.0000 | - | 0.7149 | 0.7903 |
| 11 | 1.0000 | 0.0023 | 0.0015 | 0.0015 |
| 12 | 1.0000 | - | - | - |
| 13 | 1.0000 | 0.6819 | 0.8412 | 0.7223 |
| 14 | 1.0000 | 0.5277 | 0.9152 | 1.0089 |
| 15 | 1.0000 | 0.9917 | 1.0585 | 1.0671 |

### Relative Hot Runtime

| Query ID | raw_query (ground truth) | baseline_1 | baseline_2 | optim_query |
|---|---|---|---|---|
| 1 | 1.0000 | - | - | - |
| 2 | 1.0000 | 0.0669 | 0.1089 | 0.1035 |
| 4 | 1.0000 | - | - | - |
| 5 | ERROR: Failed to measure raw_query: connection failed: connection t | - | - | - |
| 6 | 1.0000 | 0.8325 | 1.5351 | 1.5553 |
| 7 | 1.0000 | 0.2312 | 0.3355 | 0.0613 |
| 9 | 1.0000 | 0.0872 | 0.1494 | 0.2172 |
| 10 | 1.0000 | - | 0.8488 | 1.0257 |
| 11 | 1.0000 | 0.0002 | 0.0002 | 0.0002 |
| 12 | 1.0000 | - | - | - |
| 13 | 1.0000 | 0.8138 | 1.0061 | 0.8640 |
| 14 | 1.0000 | 0.5295 | 0.8776 | 0.9674 |
| 15 | 1.0000 | 1.1456 | 1.1738 | 1.2753 |

## db3632

### Correctness (Equivalence)

| Query ID | raw_query (ground truth) | baseline_1 | baseline_2 | optim_query |
|---|---|---|---|---|
| 1 | EQ | DB_EQ | DB_EQ | - |
| 2 | EQ | NEQ | DB_EQ | - |
| 3 | EQ | NEQ | DB_EQ | - |
| 4 | EQ | NEQ | DB_EQ | - |
| 5 | EQ | NEQ | DB_EQ | - |
| 7 | EQ | INV | DB_EQ | - |
| 8 | EQ | NEQ | DB_EQ | - |
| 9 | EQ | DB_EQ | DB_EQ | - |
| 10 | EQ | NEQ | DB_EQ | - |
| 11 | EQ | - | - | - |
| 12 | EQ | DB_EQ | DB_EQ | - |
| 13 | EQ | DB_EQ | DB_EQ | - |
| 15 | EQ | DB_EQ | DB_EQ | - |

**Note:** Query 11 is blank for `baseline_1`/`baseline_2`/`optim_query` because its record has `error: "Raw query result does not match source query"`, and `baseline_1_query`/`baseline_2_query`/`optim_query` are `null` — those stages never ran for it.

### Relative Cost

| Query ID | raw_query (ground truth) | baseline_1 | baseline_2 | optim_query |
|---|---|---|---|---|
| 1 | 1.0000 | 1.0812 | 0.9785 | - |
| 2 | 1.0000 | - | 1.0213 | - |
| 3 | 1.0000 | - | 0.9655 | - |
| 4 | 1.0000 | - | 0.9791 | - |
| 5 | 1.0000 | - | 0.9973 | - |
| 7 | 1.0000 | - | 0.9774 | - |
| 8 | 1.0000 | - | 0.0268 | - |
| 9 | 1.0000 | 0.9988 | 0.9988 | - |
| 10 | 1.0000 | - | 0.9841 | - |
| 11 | 1.0000 | - | - | - |
| 12 | 1.0000 | 12.1246 | 0.9924 | - |
| 13 | 1.0000 | 0.4057 | 0.7149 | - |
| 15 | 1.0000 | 3.1143 | 1.0249 | - |

### Relative Cold Runtime

| Query ID | raw_query (ground truth) | baseline_1 | baseline_2 | optim_query |
|---|---|---|---|---|
| 1 | 1.0000 | 1.7216 | 0.9849 | - |
| 2 | 1.0000 | - | 1.0700 | - |
| 3 | 1.0000 | - | 0.7363 | - |
| 4 | 1.0000 | - | 1.0292 | - |
| 5 | 1.0000 | - | 1.1953 | - |
| 7 | 1.0000 | - | 1.1416 | - |
| 8 | 1.0000 | - | 0.0456 | - |
| 9 | 1.0000 | 0.9509 | 1.0292 | - |
| 10 | 1.0000 | - | 0.9785 | - |
| 11 | 1.0000 | - | - | - |
| 12 | 1.0000 | 1.2370 | 0.9479 | - |
| 13 | 1.0000 | 0.0927 | 0.5217 | - |
| 15 | 1.0000 | 3.8513 | 1.0117 | - |

### Relative Hot Runtime

| Query ID | raw_query (ground truth) | baseline_1 | baseline_2 | optim_query |
|---|---|---|---|---|
| 1 | 1.0000 | 1.3898 | 0.8475 | - |
| 2 | 1.0000 | - | 0.9979 | - |
| 3 | 1.0000 | - | 1.1521 | - |
| 4 | 1.0000 | - | 1.0257 | - |
| 5 | 1.0000 | - | 0.9813 | - |
| 7 | 1.0000 | - | 0.9959 | - |
| 8 | 1.0000 | - | 0.0399 | - |
| 9 | 1.0000 | 0.9456 | 1.0151 | - |
| 10 | 1.0000 | - | 1.1488 | - |
| 11 | 1.0000 | - | - | - |
| 12 | 1.0000 | 1.2345 | 0.9857 | - |
| 13 | 1.0000 | 0.0620 | 0.4909 | - |
| 15 | 1.0000 | 1.4126 | 0.9838 | - |

## Summary

Per (db, method): **equivalence %** = share of attempted queries rated `EQ`/`DB_EQ` against `raw_query` (N = number of queries where that method has an analysis entry at all); **geomean relative hot runtime** and **geomean relative cost** are the geometric mean of `relative_hot_runtime`/`relative_cost` taken only over that method's queries with equivalence above `NEQ` (i.e. excluding `INV`/`NEQ`, since those figures aren't meaningful there) — so each of the three numbers in a cell can be an average over a different N; that N is shown alongside each figure.

| DB | raw_query (ground truth) | baseline_1 | baseline_2 | optim_query |
|---|---|---|---|---|
| db3532 | Eq: 100.0% (N=12)<br>GM hot runtime: 1.0000 (N=12)<br>GM cost: 1.0000 (N=12) | Eq: 10.0% (N=10)<br>GM hot runtime: 0.7899 (N=1)<br>GM cost: 0.9227 (N=1) | Eq: 100.0% (N=10)<br>GM hot runtime: 0.8033 (N=10)<br>GM cost: 0.8547 (N=10) | Eq: 90.0% (N=10)<br>GM hot runtime: 0.4917 (N=9)<br>GM cost: 0.8112 (N=9) |
| db3631 | Eq: 100.0% (N=12)<br>GM hot runtime: 1.0000 (N=12)<br>GM cost: 1.0000 (N=12) | Eq: 72.7% (N=11)<br>GM hot runtime: 0.1309 (N=8)<br>GM cost: 0.1335 (N=8) | Eq: 81.8% (N=11)<br>GM hot runtime: 0.2253 (N=9)<br>GM cost: 0.0624 (N=9) | Eq: 81.8% (N=11)<br>GM hot runtime: 0.1944 (N=9)<br>GM cost: 0.0674 (N=9) |
| db3632 | Eq: 100.0% (N=13)<br>GM hot runtime: 1.0000 (N=13)<br>GM cost: 1.0000 (N=13) | Eq: 41.7% (N=12)<br>GM hot runtime: 0.6768 (N=5)<br>GM cost: 1.7528 (N=5) | Eq: 100.0% (N=12)<br>GM hot runtime: 0.7265 (N=12)<br>GM cost: 0.7143 (N=12) | - |
