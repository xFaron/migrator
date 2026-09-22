import requests
import os
from dotenv import load_dotenv
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

load_dotenv()

def _is_retryable_error(exception: BaseException) -> bool:
  return (
    isinstance(exception, requests.exceptions.HTTPError)
    and exception.response is not None
    and (exception.response.status_code >= 500 or exception.response.status_code == 429)
  )

# Honors a Retry-After header (seconds, sent by rate-limited APIs like
# Google's) when present, falling back to the usual exponential backoff.
def _wait_retry_after_or_exponential(retry_state):
  exception = retry_state.outcome.exception()
  if isinstance(exception, requests.exceptions.HTTPError) and exception.response is not None:
    retry_after = exception.response.headers.get("Retry-After")
    if retry_after is not None:
      try:
        return float(retry_after)
      except ValueError:
        pass
  return wait_exponential(multiplier=1, min=2, max=30)(retry_state)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_API_URL = os.getenv("OPENROUTER_API_URL")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
OPENROUTER_HEADERS = {
  "Authorization": f"Bearer {OPENROUTER_API_KEY}",
  "Content-Type": "application/json",
}

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_API_URL = os.getenv("GOOGLE_API_URL", "https://generativelanguage.googleapis.com/v1beta/interactions")
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "models/gemma-4-31b-it")
GOOGLE_HEADERS = {
  "Content-Type": "application/json",
}
GOOGLE_REASONING = os.getenv("GOOGLE_REASONING", "minimal")

DEFAULT_PROVIDER = "google"

@retry(
  retry=retry_if_exception(_is_retryable_error),
  wait=_wait_retry_after_or_exponential,
  stop=stop_after_attempt(8),
  reraise=True,
)
def query_model(prompt: str, reasoning: bool = True, provider: str = DEFAULT_PROVIDER) -> dict:
  if provider == "google":
    body = {
      "model": GOOGLE_MODEL,
      "input": prompt,
      "tools": [],
      "generation_config": {
        "temperature": 1,
        "max_output_tokens": 65536,
        "top_p": 0.95,
        "thinking_level": GOOGLE_REASONING,
      },
    }
    resp = requests.post(
      f"{GOOGLE_API_URL}?key={GOOGLE_API_KEY}",
      headers=GOOGLE_HEADERS,
      json=body,
      timeout=120,
    )
    print("STATUS:", resp.status_code)
    if (resp.status_code != 200):
      print("RESPONSE:", resp.text)

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
    resp = requests.post(OPENROUTER_API_URL, headers=OPENROUTER_HEADERS, json=body, timeout=120)

    print("STATUS:", resp.status_code)
    if (resp.status_code != 200):
      print("RESPONSE:", resp.text)

    resp.raise_for_status()
    
    try:
      return (resp.json())["choices"][0]["message"]
    except Exception:
      raise RuntimeError(f"Invalid Response. Status Code: {resp.status_code}, Text: {resp.text}")
