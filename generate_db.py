import json
import os
import re

import psycopg
from dotenv import load_dotenv
from llm_tools import *

load_dotenv()

N = 1

DB_URL = os.getenv("DATABASE_URL")
PROMPT_TEMPLATE_PATH = "generate_db_prompt.md"
OUTPUT_DIR = "test_db"
GENERATED_DB_OUTPUT_PATH = os.path.join(OUTPUT_DIR, f"generated_db_{N}.json")
SCHEMA_QUERY = """
WITH columns AS (
    SELECT
        n.nspname AS schema_name,
        c.relname AS table_name,
        c.oid AS table_oid,
        a.attnum,
        a.attname AS column_name,
        pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
        NOT a.attnotnull AS nullable,
        a.attidentity AS identity_type,
        EXISTS (
            SELECT 1
            FROM pg_catalog.pg_index i
            WHERE i.indrelid = c.oid
              AND i.indisprimary
              AND a.attnum = ANY(i.indkey)
        ) AS primary_key
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n
        ON n.oid = c.relnamespace
    JOIN pg_catalog.pg_attribute a
        ON a.attrelid = c.oid
    WHERE c.relkind = 'r'
      AND a.attnum > 0
      AND NOT a.attisdropped
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
)
SELECT jsonb_build_object(
    'tables',
    COALESCE(
        jsonb_agg(
            jsonb_build_object(
                'schema', schema_name,
                'name', table_name,
                'columns', columns
            )
            ORDER BY schema_name, table_name
        ),
        '[]'::jsonb
    )
) AS database_schema
FROM (
    SELECT
        col.schema_name AS schema_name,
        col.table_name AS table_name,
        jsonb_agg(
            jsonb_build_object(
                'name', col.column_name,
                'type', col.data_type,
                'nullable', col.nullable,
                'primary_key', col.primary_key,
                'identity', col.identity_type
            )
            ORDER BY col.attnum
        ) AS columns
    FROM columns col
    GROUP BY schema_name, table_name
) tables;
"""

if not DB_URL:
  raise RuntimeError("Missing required environment variable: DATABASE_URL")

def fetch_schema(db_url: str) -> dict:
  with psycopg.connect(db_url) as conn:
    with conn.cursor() as cur:
      cur.execute(SCHEMA_QUERY)
      (schema,) = cur.fetchone()
      return schema

def build_prompt(template_path: str, schema: dict) -> str:
  with open(template_path) as f:
    template = f.read()
  return template.replace("{DB_SCHEMA}", json.dumps(schema, indent=2))

def extract_json(content: str) -> dict:
  fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.DOTALL)
  raw = fenced.group(1) if fenced else content
  return json.loads(raw, strict=False)


def main() -> None:
  os.makedirs(OUTPUT_DIR, exist_ok=True)

  print("Fetching source schema...")
  schema = fetch_schema(DB_URL)

  prompt = build_prompt(PROMPT_TEMPLATE_PATH, schema)

  print("Querying model to design target database...")
  try:
    message = query_model(prompt)
  except e:
    print(e.message)
    return
    
  content = message.get("content", "")

  print("Parsing model output...")
  try:
    generated_db = extract_json(content)
  except json.JSONDecodeError:
    fallback_path = os.path.join(OUTPUT_DIR, "generated_db.raw.txt")
    with open(fallback_path, "w") as f:
      f.write(content)
    raise RuntimeError(
      f"Model did not return valid JSON. Raw response saved to {fallback_path!r} for inspection."
    )

  print(f"Writing generated database to {GENERATED_DB_OUTPUT_PATH}...")
  with open(GENERATED_DB_OUTPUT_PATH, "w") as f:
    json.dump(generated_db, f, indent=2)

  print("Done.")

if __name__ == "__main__":
  main()