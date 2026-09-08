import requests
import os
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_API_URL = os.getenv("OPENROUTER_API_URL")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
OPENROUTER_HEADERS = {
  "Authorization": f"Bearer {OPENROUTER_API_KEY}",
  "Content-Type": "application/json",
}

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_API_URL = os.getenv("GOOGLE_API_URL", "https://generativelanguage.googleapis.com/v1beta/interactions")
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemma-4-27b-it")
GOOGLE_HEADERS = {
  "x-goog-api-key": GOOGLE_API_KEY,
  "Content-Type": "application/json",
  "Api-Revision": "2026-05-20",
}

DEFAULT_PROVIDER = "openrouter"

def query_model(prompt: str, reasoning: bool = False, provider: str = DEFAULT_PROVIDER) -> dict:
  if provider == "google":
    body = {
      "model": GOOGLE_MODEL,
      "input": prompt,
    }
    resp = requests.post(GOOGLE_API_URL, headers=GOOGLE_HEADERS, json=body)
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
  elif provider == "openrouter":
    body = {
      "model": OPENROUTER_MODEL,
      "messages": [{"role": "user", "content": prompt}],
    }
    if reasoning:
      body["reasoning"] = {"enabled": True}
    resp = requests.post(OPENROUTER_API_URL, headers=OPENROUTER_HEADERS, json=body)
    resp.raise_for_status()
    try:
      return (resp.json())["choices"][0]["message"]
    except Exception:
      raise RuntimeError(f"Invalid Response. Status Code: {resp.status_code}, Text: {resp.text}")
