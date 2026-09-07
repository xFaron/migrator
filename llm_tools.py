import requests
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("LLM_API_KEY")
API_URL = os.getenv("API_URL")
MODEL = os.getenv("LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
HEADERS = {
  "Authorization": f"Bearer {API_KEY}",
  "Content-Type": "application/json",
}

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", API_KEY)
GOOGLE_API_URL = os.getenv("GOOGLE_API_URL", "https://generativelanguage.googleapis.com/v1beta/interactions")
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemma-4-27b-it")

if not all([API_KEY, API_URL]):
  raise RuntimeError(
    "Missing one or more required environment variables: LLM_API_KEY, API_URL"
  )


def query_model(prompt: str, reasoning: bool = False, provider: str = "google") -> dict:
  if provider == "google":
    headers = {
      "x-goog-api-key": GOOGLE_API_KEY,
      "Content-Type": "application/json",
      "Api-Revision": "2026-05-20",
    }
    body = {
      "model": GOOGLE_MODEL,
      "input": prompt,
    }
    resp = requests.post(GOOGLE_API_URL, headers=headers, json=body)
    resp.raise_for_status()
    try:
      data = resp.json()
      text = ""
      for step in data.get("steps", []):
        if step.get("type") == "model_output":
          for block in step.get("content", []):
            if block.get("type") == "text":
              text += block.get("text", "")
      return {"role": "assistant", "content": text}
    except Exception:
      raise RuntimeError(f"Invalid Response. Status Code: {resp.status_code}, Text: {resp.text}")
  else:
    body = {
      "model": MODEL,
      "messages": [{"role": "user", "content": prompt}],
    }
    if reasoning:
      body["reasoning"] = {"enabled": True}
    resp = requests.post(API_URL, headers=HEADERS, json=body)
    resp.raise_for_status()
    try:
      return (resp.json())["choices"][0]["message"]
    except Exception:
      raise RuntimeError(f"Invalid Response. Status Code: {resp.status_code}, Text: {resp.text}")
