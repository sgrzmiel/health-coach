"""Withings OAuth 2 + measurements sync."""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from . import db

AUTHORIZE_URL = "https://account.withings.com/oauth2_user/authorize2"
TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"
MEASURE_URL = "https://wbsapi.withings.net/measure"
REDIRECT_URI = "http://localhost:8001/api/withings/callback"
SCOPE = "user.metrics"

MEASURE_TYPES = "1,6,8,76,77"
TYPE_NAMES = {1: "weight_kg", 6: "fat_pct", 8: "fat_mass_kg", 76: "muscle_mass_kg", 77: "water_pct"}

_state_token: Optional[str] = None


def _creds() -> tuple[str, str]:
    cid = (os.environ.get("WITHINGS_CLIENT_ID") or "").strip()
    sec = (os.environ.get("WITHINGS_CLIENT_SECRET") or "").strip()
    if not cid or not sec:
        raise RuntimeError("Withings client_id / client_secret missing in .env")
    return cid, sec


def authorize_url() -> str:
    global _state_token
    cid, _ = _creds()
    _state_token = secrets.token_urlsafe(16)
    params = {"response_type": "code", "client_id": cid, "state": _state_token, "scope": SCOPE, "redirect_uri": REDIRECT_URI}
    return str(httpx.URL(AUTHORIZE_URL).copy_with(params=params))


def handle_callback(code: str, state: str) -> dict:
    global _state_token
    if not _state_token or state != _state_token:
        raise RuntimeError("Invalid OAuth state (CSRF check). Restart the connection.")
    _state_token = None
    cid, sec = _creds()
    r = httpx.post(TOKEN_URL, data={"action": "requesttoken", "grant_type": "authorization_code", "client_id": cid, "client_secret": sec, "code": code, "redirect_uri": REDIRECT_URI}, timeout=30.0)
    payload = r.json()
    if payload.get("status") != 0:
        raise RuntimeError(f"Withings token exchange failed: {payload}")
    _save_tokens(payload["body"])
    return {"ok": True, "userid": payload["body"].get("userid")}


def _save_tokens(body: dict) -> None:
    access = body["access_token"]
    refresh = body["refresh_token"]
    expires_in = int(body["expires_in"])
    userid = str(body.get("userid", ""))
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)).isoformat()
    db._q(
        "INSERT INTO withings_tokens (id, access_token, refresh_token, expires_at, userid) VALUES (1, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET access_token=excluded.access_token, refresh_token=excluded.refresh_token, expires_at=excluded.expires_at, userid=excluded.userid",
        (access, refresh, expires_at, userid),
    )


def _load_tokens() -> Optional[dict]:
    row = db._qone("SELECT * FROM withings_tokens WHERE id = 1")
    return dict(row) if row else None


def is_connected() -> bool:
    return _load_tokens() is not None


def _refresh_tokens() -> dict:
    tokens = _load_tokens()
    if not tokens:
        raise RuntimeError("Not connected to Withings")
    cid, sec = _creds()
    r = httpx.post(TOKEN_URL, data={"action": "requesttoken", "grant_type": "refresh_token", "client_id": cid, "client_secret": sec, "refresh_token": tokens["refresh_token"]}, timeout=30.0)
    payload = r.json()
    if payload.get("status") != 0:
        raise RuntimeError(f"Withings refresh failed: {payload}")
    _save_tokens(payload["body"])
    return payload["body"]


def _ensure_fresh_token() -> str:
    tokens = _load_tokens()
    if not tokens:
        raise RuntimeError("Not connected to Withings")
    expires_at = datetime.fromisoformat(tokens["expires_at"])
    if datetime.now(timezone.utc) >= expires_at:
        tokens = _refresh_tokens()
        return tokens["access_token"]
    return tokens["access_token"]


def _decode_measure(m: dict) -> Optional[float]:
    try:
        return float(m["value"]) * (10 ** int(m["unit"]))
    except (KeyError, TypeError, ValueError):
        return None


def sync_measurements(days: int = 180) -> dict:
    access = _ensure_fresh_token()
    start = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    end = int(datetime.now(timezone.utc).timestamp())
    r = httpx.post(MEASURE_URL, headers={"Authorization": f"Bearer {access}"}, data={"action": "getmeas", "meastypes": MEASURE_TYPES, "startdate": start, "enddate": end}, timeout=60.0)
    payload = r.json()
    if payload.get("status") != 0:
        raise RuntimeError(f"Withings getmeas failed: {payload}")

    grps = payload.get("body", {}).get("measuregrps", [])
    daily: dict[str, dict] = {}
    for g in grps:
        d = datetime.fromtimestamp(g["date"], tz=timezone.utc).date().isoformat()
        slot = daily.setdefault(d, {})
        for m in g.get("measures", []):
            name = TYPE_NAMES.get(m["type"])
            if not name:
                continue
            val = _decode_measure(m)
            if val is None:
                continue
            slot[name] = val

    inserted = 0
    for d, vals in daily.items():
        if "weight_kg" not in vals:
            continue
        db._q(
            "INSERT OR REPLACE INTO withings_weights (date, weight_kg, fat_mass_kg, muscle_mass_kg, water_pct, raw_json) VALUES (?, ?, ?, ?, ?, ?)",
            (d, vals.get("weight_kg"), vals.get("fat_mass_kg"), vals.get("muscle_mass_kg"), vals.get("water_pct"), None),
        )
        inserted += 1

    if daily:
        latest = max(daily.keys())
        if "weight_kg" in daily[latest]:
            db.set_config("current_weight_kg", f"{daily[latest]['weight_kg']:.1f}")

    return {"inserted_days": inserted, "raw_groups": len(grps)}


def recent_weights(limit: int = 60) -> list[dict]:
    rows = db._qa("SELECT * FROM withings_weights ORDER BY date DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


def status() -> dict:
    tokens = _load_tokens()
    if not tokens:
        return {"connected": False}
    return {"connected": True, "userid": tokens.get("userid"), "expires_at": tokens.get("expires_at")}


def disconnect() -> None:
    db._q("DELETE FROM withings_tokens WHERE id = 1")
