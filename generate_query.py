import argparse
import json
import os
import re

from dotenv import load_dotenv
from llm_tools import *

load_dotenv()

N = 1

PROMPT_QUERY_GEN = "generate_query_prompt.md"
OUTPUT_DIR = "test_db"
GENERATED_DB_INPUT_PATH = os.path.join(OUTPUT_DIR, f"generated_db_{N}.json")
QUERIES_OUTPUT_PATH = os.path.join(OUTPUT_DIR, "queries.json")
DEFAULT_K = 5
HEADERS = {
  "Authorization": f"Bearer {API_KEY}",
  "Content-Type": "application/json",
}

def load_target_schema(generated_db_path: str) -> str:
  if not os.path.exists(generated_db_path):
    raise FileNotFoundError(
      f"Could not find {generated_db_path!r}. Run generate_db.py first to produce it."
    )
  with open(generated_db_path) as f:
    generated_db = json.load(f)

  schema = generated_db.get("target_database_schema")
  if not schema:
    raise KeyError(
      f"{generated_db_path!r} has no 'target_database_schema' field. "
      "Was it produced by the current version of generate_db.py?"
    )
  return schema

def build_prompt(template_path: str, db_schema: str, k: int) -> str:
  with open(template_path) as f:
    template = f.read()
  return template.replace("{DB_SCHEMA}", db_schema).replace("{K}", str(k))

def extract_json(content: str) -> dict:
  fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.DOTALL)
  raw = fenced.group(1) if fenced else content
  return json.loads(raw, strict=False)

def main() -> None:  
  os.makedirs(os.path.dirname(OUTPUT_DIR) or ".", exist_ok=True)

  print(f"Loading generated target schema from {GENERATED_DB_INPUT_PATH}...")
  db_schema = load_target_schema(GENERATED_DB_INPUT_PATH)

  prompt = build_prompt(PROMPT_QUERY_GEN, db_schema, DEFAULT_K)

  print(f"Querying model for {DEFAULT_K} queries...")
  try:
    message = query_model(prompt)
  except e:
    print(e.message)
    return
    
  content = message.get("content", "")

  print("Parsing model output...")
  try:
    queries = extract_json(content)
  except json.JSONDecodeError:
    fallback_path = os.path.splitext(OUTPUT_DIR)[0] + ".raw.txt"
    with open(fallback_path, "w") as f:
      f.write(content)
    raise RuntimeError(
      f"Model did not return valid JSON. Raw response saved to {fallback_path!r} for inspection."
    )

  print(f"Writing queries to {OUTPUT_DIR}...")
  with open(QUERIES_OUTPUT_PATH, "w") as f:
    json.dump(queries, f, indent=2)

  print("Done.")


if __name__ == "__main__":
  main()