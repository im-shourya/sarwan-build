"""Email/password accounts backed by Supabase Auth."""
import time

import httpx
from fastapi import Header, HTTPException

import db

_cache = {}  # access token -> (user, expires_at)
CACHE_SECONDS = 60


def _auth(path, **kwargs):
    if not db.ENABLED:
        raise HTTPException(503, "Accounts need Supabase. Set SUPABASE_URL and SUPABASE_SERVICE_KEY.")
    headers = {"apikey": db.SUPABASE_KEY, **kwargs.pop("headers", {})}
    with httpx.Client(base_url=f"{db.SUPABASE_URL}/auth/v1", timeout=15) as http:
        return http.request(kwargs.pop("method", "POST"), path, headers=headers, **kwargs)


def _session(r):
    if r.status_code >= 400:
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        msg = data.get("msg") or data.get("error_description") or data.get("message") or "Authentication failed"
        raise HTTPException(401 if r.status_code in (400, 401) else r.status_code, msg)
    d = r.json()
    return {
        "access_token": d["access_token"],
        "refresh_token": d["refresh_token"],
        "expires_at": d.get("expires_at"),
        "user": {"id": d["user"]["id"], "email": d["user"]["email"]},
    }


def sign_up(email, password):
    # Admin create skips the confirmation email so the account works immediately.
    r = _auth(
        "/admin/users",
        headers={"Authorization": f"Bearer {db.SUPABASE_KEY}"},
        json={"email": email, "password": password, "email_confirm": True},
    )
    if r.status_code == 422 or "already" in r.text.lower():
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    if r.status_code >= 400:
        raise HTTPException(400, r.json().get("msg") or r.json().get("message") or "Sign-up failed")
    return sign_in(email, password)


def sign_in(email, password):
    return _session(_auth("/token", params={"grant_type": "password"}, json={"email": email, "password": password}))


def refresh(refresh_token):
    return _session(_auth("/token", params={"grant_type": "refresh_token"}, json={"refresh_token": refresh_token}))


def current_user(authorization: str = Header(None)):
    """FastAPI dependency: the signed-in Supabase user, or 401."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in required")
    token = authorization[7:]
    hit = _cache.get(token)
    if hit and hit[1] > time.time():
        return hit[0]
    r = _auth("/user", method="GET", headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        _cache.pop(token, None)
        raise HTTPException(401, "Session expired")
    user = {"id": r.json()["id"], "email": r.json()["email"]}
    _cache[token] = (user, time.time() + CACHE_SECONDS)
    return user
