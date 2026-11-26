"""Garmin Connect login with web-friendly 2FA via threading.Event bridge.

garminconnect 0.3.x API:
  - api.login(tokenstore=path)  saves tokens automatically
  - api.client.load(path)       loads tokens for subsequent calls
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

GARTH_TOKEN_DIR = Path.home() / ".garminconnect"


@dataclass
class LoginState:
    thread: threading.Thread
    mfa_event: threading.Event = field(default_factory=threading.Event)
    mfa_code: Optional[str] = None
    status: str = "in_progress"
    error: Optional[str] = None
    needs_mfa: bool = False


_state: Optional[LoginState] = None
_lock = threading.Lock()


def tokens_exist() -> bool:
    token_file = GARTH_TOKEN_DIR / "garmin_tokens.json"
    return token_file.exists() and token_file.stat().st_size > 0


def is_logged_in() -> bool:
    import json
    token_file = GARTH_TOKEN_DIR / "garmin_tokens.json"
    if not token_file.exists():
        return False
    try:
        d = json.loads(token_file.read_text())
        return bool(d.get("di_token"))
    except Exception:
        return False


def _do_login(email: str, password: str, st: LoginState) -> None:
    try:
        from garminconnect import Garmin

        def prompt_mfa() -> str:
            st.status = "mfa_pending"
            st.needs_mfa = True
            st.mfa_event.wait(timeout=300)
            if not st.mfa_code:
                raise RuntimeError("MFA code not provided in time")
            return st.mfa_code

        api = Garmin(email=email, password=password, prompt_mfa=prompt_mfa)
        GARTH_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        api.login(tokenstore=str(GARTH_TOKEN_DIR))
        st.status = "success"
    except Exception as exc:
        st.status = "error"
        st.error = f"{type(exc).__name__}: {exc}"


def start_login(email: str, password: str) -> dict:
    global _state
    with _lock:
        if _state and _state.thread.is_alive():
            return {"status": _state.status, "needs_mfa": _state.needs_mfa, "error": _state.error}
        st = LoginState(thread=None)  # type: ignore[arg-type]
        t = threading.Thread(target=_do_login, args=(email, password, st), daemon=True)
        st.thread = t
        _state = st
        t.start()
        t.join(timeout=5.0)
        return {"status": st.status, "needs_mfa": st.needs_mfa, "error": st.error}


def submit_mfa(code: str) -> dict:
    with _lock:
        st = _state
    if not st:
        return {"status": "error", "error": "no login in progress"}
    if st.status not in {"mfa_pending", "in_progress"}:
        return {"status": st.status, "error": st.error}
    st.mfa_code = code.strip()
    st.mfa_event.set()
    st.thread.join(timeout=20.0)
    return {"status": st.status, "error": st.error}


def login_status() -> dict:
    with _lock:
        st = _state
    if not st:
        return {"status": "idle", "logged_in": is_logged_in()}
    return {
        "status": st.status,
        "needs_mfa": st.needs_mfa,
        "error": st.error,
        "logged_in": st.status == "success" or is_logged_in(),
    }


def resume_client():
    """Return a logged-in Garmin client using saved tokens."""
    from garminconnect import Garmin
    api = Garmin()
    api.client.load(str(GARTH_TOKEN_DIR))
    return api


def env_credentials() -> tuple[Optional[str], Optional[str]]:
    email = (os.environ.get("GARMIN_EMAIL") or "").strip() or None
    password = (os.environ.get("GARMIN_PASSWORD") or "").strip() or None
    return email, password
