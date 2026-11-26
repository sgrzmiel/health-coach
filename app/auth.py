"""Password-based session auth."""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Cookie, HTTPException, Response

COOKIE_NAME = "hc_session"
SESSION_TTL = timedelta(days=7)


def _password_configured() -> bool:
    return bool((os.environ.get("APP_PASSWORD") or "").strip())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _prune() -> None:
    from .db import _q
    _q("DELETE FROM sessions WHERE expires_at < ?", (_now().isoformat(),))


def is_open_mode() -> bool:
    return not _password_configured()


def is_token_valid(token: Optional[str]) -> bool:
    if is_open_mode():
        return True
    if not token:
        return False
    from .db import _qone
    _prune()
    row = _qone("SELECT expires_at FROM sessions WHERE token = ?", (token,))
    return row is not None


def login(password: str, response: Response) -> bool:
    if not _password_configured():
        return True
    expected = (os.environ.get("APP_PASSWORD") or "").strip()
    if not secrets.compare_digest(password.strip(), expected):
        return False
    from .db import _q
    token = secrets.token_urlsafe(32)
    expires_at = (_now() + SESSION_TTL).isoformat()
    _q("INSERT INTO sessions(token, expires_at) VALUES (?, ?)", (token, expires_at))
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=int(SESSION_TTL.total_seconds()),
    )
    return True


def logout(token: Optional[str], response: Response) -> None:
    if token:
        from .db import _q
        _q("DELETE FROM sessions WHERE token = ?", (token,))
    response.delete_cookie(COOKIE_NAME)


def current_status(token: Optional[str]) -> dict:
    if is_open_mode():
        return {"authenticated": True, "mode": "open"}
    return {"authenticated": is_token_valid(token), "mode": "password"}


def require_auth(hc_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME)) -> None:
    if is_open_mode():
        return
    if not is_token_valid(hc_session):
        raise HTTPException(status_code=401, detail="authentication required")
