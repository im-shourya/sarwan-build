"""Persistence: Supabase (PostgREST) when configured, in-memory otherwise."""
import os
import uuid

import httpx

import sarvam_client  # noqa: F401  (loads .env)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
ENABLED = bool(SUPABASE_URL and SUPABASE_KEY)

_memory = {"profiles": {}, "interviews": {}}


def _http():
    return httpx.Client(
        base_url=f"{SUPABASE_URL}/rest/v1",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Prefer": "return=representation",
        },
        timeout=15,
    )


def insert(table, row):
    if not ENABLED:
        row = {"id": str(uuid.uuid4()), **row}
        _memory[table][row["id"]] = row
        return row
    with _http() as http:
        r = http.post(f"/{table}", json=row)
        r.raise_for_status()
        return r.json()[0]


def get(table, row_id):
    try:
        uuid.UUID(str(row_id))
    except ValueError:
        return None
    if not ENABLED:
        return _memory[table].get(row_id)
    with _http() as http:
        r = http.get(f"/{table}", params={"id": f"eq.{row_id}", "select": "*"})
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None


def update(table, row_id, fields):
    if not ENABLED:
        _memory[table][row_id].update(fields)
        return _memory[table][row_id]
    with _http() as http:
        r = http.patch(f"/{table}", params={"id": f"eq.{row_id}"}, json=fields)
        r.raise_for_status()
        return r.json()[0]
