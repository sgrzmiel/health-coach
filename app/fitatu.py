"""Fitatu unofficial API client.

API reverse-engineered from the mobile app (Dart/Flutter).
Base: https://fitatu.com/api
Auth: POST /login  body: {"_username": email, "_password": password}
      Response token is a JWT; user_id extracted from payload.
Day plan: GET /diet-and-activity-plan/{userId}/day/{date}
          Returns dietPlan with meals -> items (energy, protein, fat, carbohydrate, fiber).
"""

from __future__ import annotations

import base64
import json
import os
import time
from datetime import date, timedelta
from typing import Any, Optional

import httpx

from . import db

BASE_URL = "https://pl-pl.fitatu.com/api"

_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "content-type": "application/json;charset=UTF-8",
    "api-key": "FITATU-MOBILE-APP",
    "api-secret": "PYRXtfs88UDJMuCCrNpLV",
    "app-uuid": "64c2d1b0-c8ad-11e8-8956-0242ac120008",
    "api-cluster": "pl-pl0",
    "app-locale": "pl_PL",
    "app-searchlocale": "pl_PL",
    "app-storagelocale": "pl_PL",
    "app-timezone": "Europe/Warsaw",
    "app-os": "WEB",
    "app-version": "4.13.1",
    "user-agent": "Mozilla/5.0",
}


# ---------------------------------------------------------------------------
# Token storage
# ---------------------------------------------------------------------------


def _save_tokens(access_token: str, user_id: str, refresh_token: Optional[str] = None) -> None:
    db._q(
        "INSERT INTO fitatu_tokens (id, access_token, refresh_token, user_id) VALUES (1, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET access_token=excluded.access_token, refresh_token=excluded.refresh_token, user_id=excluded.user_id",
        (access_token, refresh_token, user_id),
    )


def _load_tokens() -> Optional[dict]:
    row = db._qone("SELECT * FROM fitatu_tokens WHERE id = 1")
    return dict(row) if row else None


def is_connected() -> bool:
    return _load_tokens() is not None


def disconnect() -> None:
    db._q("DELETE FROM fitatu_tokens WHERE id = 1")


def status() -> dict:
    tokens = _load_tokens()
    if not tokens:
        return {"connected": False}
    return {"connected": True, "user_id": tokens.get("user_id")}


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _extract_user_id_from_jwt(token: str) -> Optional[str]:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1]
        padded = payload_b64 + "=" * ((4 - len(payload_b64) % 4) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        for key in ("user_id", "uid", "id", "sub"):
            val = payload.get(key)
            if val:
                return str(val)
    except Exception:
        pass
    return None


def login(email: str, password: str) -> dict:
    r = httpx.post(
        f"{BASE_URL}/login",
        headers=_HEADERS,
        content=json.dumps({"_username": email, "_password": password}),
        timeout=30.0,
    )
    r.raise_for_status()
    data = r.json()
    token = data.get("token") or data.get("access_token")
    if not token:
        raise RuntimeError(f"Fitatu login: no token in response: {data}")
    refresh = data.get("refresh_token") or data.get("refreshToken")
    user_id = _extract_user_id_from_jwt(token)
    if not user_id:
        raise RuntimeError("Fitatu login: could not extract user_id from JWT")
    _save_tokens(token, user_id, refresh)
    return {"ok": True, "user_id": user_id}


def _refresh_token() -> dict:
    tokens = _load_tokens()
    if not tokens or not tokens.get("refresh_token"):
        raise RuntimeError("No refresh token available - please log in again")
    for body in [
        {"refresh_token": tokens["refresh_token"]},
        {"refreshToken": tokens["refresh_token"]},
        {"token": tokens["refresh_token"]},
    ]:
        try:
            r = httpx.post(
                f"{BASE_URL}/token/refresh",
                headers=_HEADERS,
                content=json.dumps(body),
                timeout=30.0,
            )
            if r.status_code not in (400, 401, 404, 415, 422):
                r.raise_for_status()
                data = r.json()
                new_token = data.get("token") or data.get("access_token")
                if new_token:
                    new_refresh = data.get("refresh_token") or data.get("refreshToken") or tokens["refresh_token"]
                    user_id = _extract_user_id_from_jwt(new_token) or tokens["user_id"]
                    _save_tokens(new_token, user_id, new_refresh)
                    return {"ok": True}
        except Exception:
            continue
    raise RuntimeError("Token refresh failed - please log in again")


def _authed_get(path: str, params: Optional[dict] = None) -> Any:
    tokens = _load_tokens()
    if not tokens:
        raise RuntimeError("Fitatu not connected - use /api/fitatu/login first")

    headers = {**_HEADERS, "authorization": f"Bearer {tokens['access_token']}"}
    r = httpx.get(f"{BASE_URL}{path}", headers=headers, params=params, timeout=30.0)

    if r.status_code == 401:
        _refresh_token()
        tokens = _load_tokens()
        headers = {**_HEADERS, "authorization": f"Bearer {tokens['access_token']}"}
        r = httpx.get(f"{BASE_URL}{path}", headers=headers, params=params, timeout=30.0)

    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Day plan
# ---------------------------------------------------------------------------


def _sum_day_nutrition(day_data: dict) -> dict:
    """Sum calories + macros across all meals and all items in a day plan response."""
    calories = 0.0
    protein = 0.0
    carbs = 0.0
    fat = 0.0
    fiber = 0.0
    water = 0.0
    count = 0

    diet_plan = day_data.get("dietPlan") or {}
    for meal_data in diet_plan.values():
        if not isinstance(meal_data, dict):
            continue
        for item in meal_data.get("items") or []:
            if not isinstance(item, dict):
                continue
            if item.get("deletedAt"):
                continue
            calories += item.get("energy") or 0
            protein += item.get("protein") or 0
            carbs += item.get("carbohydrate") or 0
            fat += item.get("fat") or 0
            fiber += item.get("fiber") or 0
            water += item.get("water") or 0
            count += 1

    return {
        "calories": round(calories, 1),
        "protein_g": round(protein, 1),
        "carbs_g": round(carbs, 1),
        "fat_g": round(fat, 1),
        "fiber_g": round(fiber, 1),
        "water_ml": round(water, 1),
        "items_count": count,
    }


def sync_diary(days: int = 30) -> dict:
    tokens = _load_tokens()
    if not tokens:
        raise RuntimeError("Fitatu not connected")
    user_id = tokens["user_id"]

    today = date.today()
    inserted = 0
    errors = 0

    for i in range(days):
        d = today - timedelta(days=i)
        iso = d.isoformat()
        try:
            data = _authed_get(f"/diet-and-activity-plan/{user_id}/day/{iso}")
            totals = _sum_day_nutrition(data)
            db._q(
                "INSERT OR REPLACE INTO fitatu_diary (date, calories, protein_g, carbs_g, fat_g, fiber_g, water_ml, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (iso, totals["calories"], totals["protein_g"], totals["carbs_g"], totals["fat_g"], totals["fiber_g"], totals["water_ml"] or None, None),
            )
            inserted += 1
        except Exception as exc:
            errors += 1
            if errors > 5:
                break
        time.sleep(0.3)

    from datetime import datetime, timezone
    db.set_config("last_fitatu_sync_at", datetime.now(timezone.utc).isoformat())
    return {"synced_days": inserted, "errors": errors}


def recent_diary(limit: int = 30) -> list[dict]:
    rows = db._qa("SELECT * FROM fitatu_diary ORDER BY date DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


def today_nutrition() -> Optional[dict]:
    row = db._qone("SELECT * FROM fitatu_diary WHERE date = ?", (date.today().isoformat(),))
    return dict(row) if row else None
