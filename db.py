"""Persistence: Supabase (PostgREST) when configured, in-memory otherwise."""
import os
import uuid
from datetime import datetime, timezone

import httpx

import sarvam_client  # noqa: F401  (loads .env)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
ENABLED = bool(SUPABASE_URL and SUPABASE_KEY)

TABLES = ("profiles", "interviews", "problems", "submissions", "quizzes")
_memory = {t: {} for t in TABLES}


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


def _valid_id(row_id):
    try:
        uuid.UUID(str(row_id))
        return True
    except ValueError:
        return False


def insert(table, row):
    if not ENABLED:
        row = {"id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc).isoformat(), **row}
        _memory[table][row["id"]] = row
        return row
    with _http() as http:
        r = http.post(f"/{table}", json=row)
        r.raise_for_status()
        return r.json()[0]


def get(table, row_id):
    if not _valid_id(row_id):
        return None
    if not ENABLED:
        return _memory[table].get(row_id)
    with _http() as http:
        r = http.get(f"/{table}", params={"id": f"eq.{row_id}", "select": "*"})
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None


def select(table, columns="*", limit=50, **filters):
    """Rows matching equality filters, newest first."""
    if not ENABLED:
        rows = [r for r in _memory[table].values() if all(r.get(k) == v for k, v in filters.items())]
        return sorted(rows, key=lambda r: r["created_at"], reverse=True)[:limit]
    params = {"select": columns, "order": "created_at.desc", "limit": str(limit)}
    params.update({k: f"eq.{v}" for k, v in filters.items()})
    with _http() as http:
        r = http.get(f"/{table}", params=params)
        r.raise_for_status()
        return r.json()


def update(table, row_id, fields):
    if not ENABLED:
        _memory[table][row_id].update(fields)
        return _memory[table][row_id]
    with _http() as http:
        r = http.patch(f"/{table}", params={"id": f"eq.{row_id}"}, json=fields)
        r.raise_for_status()
        return r.json()[0]
