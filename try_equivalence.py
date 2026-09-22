import os

import psycopg
from dotenv import load_dotenv

from db_tools import check_env
from db_tools.correctness.equivalence import sqlsolver_logical_equivalence

load_dotenv()
check_env()

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
  raise RuntimeError("Missing required environment variable: DATABASE_URL")


def read_multiline(prompt: str) -> str:
  print(prompt + " (end with a blank line):")
  lines = []
  while True:
    line = input()
    if line == "":
      break
    lines.append(line)
  return "\n".join(lines)


def read_statements(prompt: str) -> list[str]:
  text = read_multiline(prompt)
  return [line.strip().rstrip(";") for line in text.splitlines() if line.strip()]


def main() -> None:
  query_a = read_multiline("Query A")
  query_b = read_multiline("Query B")
  schema = read_statements("Schema (one CREATE/ALTER statement per line)")

  with psycopg.connect(DB_URL, autocommit=True) as conn:
    with conn.cursor() as curr:
      print(query_a, query_b)
      print(schema)
      result = sqlsolver_logical_equivalence([query_a], [query_b], schema)

  print(f"\nResult: {result}")


if __name__ == "__main__":
  main()
