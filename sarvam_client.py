import json
import os
import tempfile
import zipfile
from pathlib import Path

from sarvamai import SarvamAI

# Load KEY=VALUE pairs from .env without adding a dependency.
env_file = Path(__file__).with_name(".env")
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

# The conversations model answers in seconds; the reasoning model takes minutes
# on long outputs, so it is used only where deeper analysis pays off.
MODEL = "sarvam-105b-conversations"
REASONING_MODEL = "sarvam-105b"

_client = None


class SarvamError(Exception):
    """A Sarvam call failed (network, rate limit, bad reply)."""


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
    if model == REASONING_MODEL:
        kwargs.setdefault("reasoning_effort", "low")
    try:
        response = client().chat.completions(model=model, messages=messages, **kwargs)
    except Exception as e:
        raise SarvamError(f"{type(e).__name__}: {e}") from e
    return (response.choices[0].message.content or "").strip()


def ask(prompt, **kwargs):
    return chat([{"role": "user", "content": prompt}], **kwargs)


def ask_json(prompt, validate=None, attempts=2, **kwargs):
    """Ask for JSON, parse it, and retry once if it is malformed or fails validation."""
    error = None
    for _ in range(attempts):
        try:
            data = parse_json(ask(prompt, **kwargs))
            if validate:
                validate(data)
            return data
        except (ValueError, KeyError, TypeError, AssertionError) as e:
            error = e
    raise SarvamError(f"Model returned unusable JSON: {error}")


def ocr_pdf(data):
    """Read a scanned PDF with Sarvam Document Intelligence; returns markdown text."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "resume.pdf")
            with open(path, "wb") as f:
                f.write(data)
            job = client().document_intelligence.create_job(language="en-IN", output_format="md")
            job.upload_file(path)
            job.start()
            job.wait_until_complete(poll_interval=2, timeout=120)
            out = job.download_output(os.path.join(tmp, "out"))
            with zipfile.ZipFile(out) as z:
                return "\n".join(z.read(n).decode() for n in z.namelist() if n.endswith(".md"))
    except Exception as e:
        raise SarvamError(f"OCR failed: {type(e).__name__}: {e}") from e


def parse_json(text):
    """Pull the outermost JSON object out of a model reply."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object in reply")
    return json.loads(text[start : end + 1])
