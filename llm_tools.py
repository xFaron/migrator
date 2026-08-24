import requests
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("LLM_API_KEY")
API_URL = os.getenv("API_URL")
MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
HEADERS = {
  "Authorization": f"Bearer {API_KEY}",
  "Content-Type": "application/json",
}

if not all([API_KEY, API_URL]):
  raise RuntimeError(
    "Missing one or more required environment variables: OPENROUTER_API_KEY, OPENROUTER_URL, DATABASE_URL"
  )


def query_model(prompt: str) -> dict:
  resp = requests.post(
    API_URL,
    headers=HEADERS,
    json={
      "model": MODEL,
      "messages": [{"role": "user", "content": prompt}],
      "reasoning": {"enabled": False},
    },
  )
  resp.raise_for_status()
  try:
    msg = (resp.json())["choices"][0]["message"]
  except:
    raise RuntimeError(f"Invalid Respone. Status Code: {resp.status_code}, Text: {resp.text}")

  return msg