WITH
selected_tables AS (
    SELECT
        c.oid AS table_oid,
        n.nspname AS schema_name,
        c.relname AS table_name
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n
        ON n.oid = c.relnamespace
    WHERE c.relkind = 'r'
      AND n.nspname = $1
),

columns AS (
    SELECT
        c.oid AS table_oid,
        a.attnum,
        a.attname AS column_name,
        pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
        NOT a.attnotnull AS nullable,
        a.attidentity AS identity_type,
        a.attgenerated AS generated_type,
        pg_catalog.pg_get_expr(ad.adbin, ad.adrelid) AS default_expression,

        EXISTS (
            SELECT 1
            FROM pg_catalog.pg_index i
            WHERE i.indrelid = c.oid
              AND i.indisprimary
              AND a.attnum = ANY(i.indkey)
        ) AS primary_key
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_attribute a
        ON a.attrelid = c.oid
    LEFT JOIN pg_catalog.pg_attrdef ad
        ON ad.adrelid = a.attrelid
       AND ad.adnum = a.attnum
    WHERE c.oid IN (
        SELECT table_oid
        FROM selected_tables
    )
      AND a.attnum > 0
      AND NOT a.attisdropped
),

table_columns AS (
    SELECT
        c.table_oid,
        jsonb_agg(
            jsonb_build_object(
                'name', c.column_name,
                'type', c.data_type,
                'nullable', c.nullable,
                'primary_key', c.primary_key,
                'identity', NULLIF(c.identity_type, ''),
                'generated', NULLIF(c.generated_type, ''),
                'default', c.default_expression
            )
            ORDER BY c.attnum
        ) AS columns
    FROM columns c
    GROUP BY c.table_oid
),

primary_keys AS (
    SELECT
        con.conrelid AS table_oid,
        jsonb_build_object(
            'name', con.conname,
            'columns',
            (
                SELECT jsonb_agg(
                    a.attname
                    ORDER BY u.ordinality
                )
                FROM unnest(con.conkey) WITH ORDINALITY AS u(attnum, ordinality)
                JOIN pg_catalog.pg_attribute a
                    ON a.attrelid = con.conrelid
                   AND a.attnum = u.attnum
            ),
            'deferrable', con.condeferrable,
            'initially_deferred', con.condeferred
        ) AS primary_key
    FROM pg_catalog.pg_constraint con
    WHERE con.contype = 'p'
      AND con.conrelid IN (
          SELECT table_oid
          FROM selected_tables
      )
),

foreign_keys AS (
    SELECT
        con.conrelid AS table_oid,
        jsonb_agg(
            jsonb_build_object(
                'name', con.conname,

                'columns',
                (
                    SELECT jsonb_agg(
                        a.attname
                        ORDER BY u.ordinality
                    )
                    FROM unnest(con.conkey) WITH ORDINALITY AS u(attnum, ordinality)
                    JOIN pg_catalog.pg_attribute a
                        ON a.attrelid = con.conrelid
                       AND a.attnum = u.attnum
                ),

                'references',
                jsonb_build_object(
                    'table', ref_tbl.relname,

                    'columns',
                    (
                        SELECT jsonb_agg(
                            a.attname
                            ORDER BY u.ordinality
                        )
                        FROM unnest(con.confkey) WITH ORDINALITY AS u(attnum, ordinality)
                        JOIN pg_catalog.pg_attribute a
                            ON a.attrelid = con.confrelid
                           AND a.attnum = u.attnum
                    )
                ),

                'on_delete',
                CASE con.confdeltype
                    WHEN 'a' THEN 'NO ACTION'
                    WHEN 'r' THEN 'RESTRICT'
                    WHEN 'c' THEN 'CASCADE'
                    WHEN 'n' THEN 'SET NULL'
                    WHEN 'd' THEN 'SET DEFAULT'
                END,

                'on_update',
                CASE con.confupdtype
                    WHEN 'a' THEN 'NO ACTION'
                    WHEN 'r' THEN 'RESTRICT'
                    WHEN 'c' THEN 'CASCADE'
                    WHEN 'n' THEN 'SET NULL'
                    WHEN 'd' THEN 'SET DEFAULT'
                END,

                'deferrable', con.condeferrable,
                'initially_deferred', con.condeferred
            )
            ORDER BY con.conname
        ) AS foreign_keys
    FROM pg_catalog.pg_constraint con
    JOIN pg_catalog.pg_class ref_tbl
        ON ref_tbl.oid = con.confrelid
    JOIN pg_catalog.pg_namespace ref_ns
        ON ref_ns.oid = ref_tbl.relnamespace
    WHERE con.contype = 'f'
      AND con.conrelid IN (
          SELECT table_oid
          FROM selected_tables
      )
    GROUP BY con.conrelid
),

unique_constraints AS (
    SELECT
        con.conrelid AS table_oid,
        jsonb_agg(
            jsonb_build_object(
                'name', con.conname,

                'columns',
                (
                    SELECT jsonb_agg(
                        a.attname
                        ORDER BY u.ordinality
                    )
                    FROM unnest(con.conkey) WITH ORDINALITY AS u(attnum, ordinality)
                    JOIN pg_catalog.pg_attribute a
                        ON a.attrelid = con.conrelid
                       AND a.attnum = u.attnum
                ),

                'deferrable', con.condeferrable,
                'initially_deferred', con.condeferred
            )
            ORDER BY con.conname
        ) AS unique_constraints
    FROM pg_catalog.pg_constraint con
    WHERE con.contype = 'u'
      AND con.conrelid IN (
          SELECT table_oid
          FROM selected_tables
      )
    GROUP BY con.conrelid
),

check_constraints AS (
    SELECT
        con.conrelid AS table_oid,
        jsonb_agg(
            jsonb_build_object(
                'name', con.conname,
                'definition', pg_catalog.pg_get_constraintdef(con.oid),
                'deferrable', con.condeferrable,
                'initially_deferred', con.condeferred
            )
            ORDER BY con.conname
        ) AS check_constraints
    FROM pg_catalog.pg_constraint con
    WHERE con.contype = 'c'
      AND con.conrelid IN (
          SELECT table_oid
          FROM selected_tables
      )
    GROUP BY con.conrelid
),

indexes AS (
    SELECT
        i.indrelid AS table_oid,
        jsonb_agg(
            jsonb_build_object(
                'name', idx.relname,
                'unique', i.indisunique,
                'primary', i.indisprimary,
                'valid', i.indisvalid,
                'definition', pg_catalog.pg_get_indexdef(i.indexrelid)
            )
            ORDER BY idx.relname
        ) AS indexes
    FROM pg_catalog.pg_index i
    JOIN pg_catalog.pg_class idx
        ON idx.oid = i.indexrelid
    WHERE i.indrelid IN (
        SELECT table_oid
        FROM selected_tables
    )
    GROUP BY i.indrelid
)

SELECT jsonb_build_object(

    'schema', $1,

    'tables',
    COALESCE(
        jsonb_agg(
            jsonb_build_object(
                'name', t.table_name,

                'columns',
                COALESCE(tc.columns, '[]'::jsonb),

                'primary_key',
                COALESCE(
                    pk.primary_key,
                    '{}'::jsonb
                ),

                'foreign_keys',
                COALESCE(
                    fk.foreign_keys,
                    '[]'::jsonb
                ),

                'unique_constraints',
                COALESCE(
                    uq.unique_constraints,
                    '[]'::jsonb
                ),

                'check_constraints',
                COALESCE(
                    ck.check_constraints,
                    '[]'::jsonb
                ),

                'indexes',
                COALESCE(
                    ix.indexes,
                    '[]'::jsonb
                )
            )
            ORDER BY t.table_name
        ),
        '[]'::jsonb
    )

) AS database_schema

FROM selected_tables t
LEFT JOIN table_columns tc
    ON tc.table_oid = t.table_oid
LEFT JOIN primary_keys pk
    ON pk.table_oid = t.table_oid
LEFT JOIN foreign_keys fk
    ON fk.table_oid = t.table_oid
LEFT JOIN unique_constraints uq
    ON uq.table_oid = t.table_oid
LEFT JOIN check_constraints ck
    ON ck.table_oid = t.table_oid
LEFT JOIN indexes ix
    ON ix.table_oid = t.table_oid;