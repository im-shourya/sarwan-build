import json
import os
from pathlib import Path

from sarvamai import SarvamAI

# Load KEY=VALUE pairs from .env without adding a dependency.
env_file = Path(__file__).with_name(".env")
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

MODEL = "sarvam-105b"
CHAT_MODEL = "sarvam-105b-conversations"

_client = None


def client():
    global _client
    if _client is None:
        api_key = os.environ.get("SARVAM_API_KEY")
        if not api_key:
            raise RuntimeError("SARVAM_API_KEY is not set. Add it to .env.")
        _client = SarvamAI(api_subscription_key=api_key, timeout=180)
    return _client


def chat(messages, model=MODEL, **kwargs):
    # Reasoning tokens count against max_tokens, so leave room for the answer.
    kwargs.setdefault("max_tokens", 8000)
    if model == MODEL:
        kwargs.setdefault("reasoning_effort", "low")
    response = client().chat.completions(model=model, messages=messages, **kwargs)
    return (response.choices[0].message.content or "").strip()


def ask(prompt, **kwargs):
    return chat([{"role": "user", "content": prompt}], **kwargs)


def parse_json(text):
    """Pull the outermost JSON object out of a model reply."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object in reply")
    return json.loads(text[start : end + 1])
