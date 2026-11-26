"""Manual gym session log."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from . import db


def list_sessions(limit: int = 60) -> list[dict]:
    rows = db._qa(
        """
        SELECT s.*,
               (SELECT COUNT(*) FROM gym_sets WHERE session_id = s.id) AS sets_count,
               (SELECT GROUP_CONCAT(DISTINCT exercise) FROM gym_sets WHERE session_id = s.id) AS exercises
        FROM gym_sessions s
        ORDER BY s.date DESC, s.id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [dict(r) for r in rows]


def get_session(session_id: int) -> Optional[dict]:
    s = db._qone("SELECT * FROM gym_sessions WHERE id = ?", (session_id,))
    if not s:
        return None
    sets = db._qa("SELECT * FROM gym_sets WHERE session_id = ? ORDER BY exercise, set_idx", (session_id,))
    out = dict(s)
    out["sets"] = [dict(x) for x in sets]
    return out


def create_session(date: str, duration_min: Optional[int] = None, rpe: Optional[int] = None, notes: str = "") -> dict:
    cur = db._q(
        "INSERT INTO gym_sessions (date, duration_min, rpe, notes, created_at) VALUES (?, ?, ?, ?, ?)",
        (date, duration_min, rpe, notes, datetime.now(timezone.utc).isoformat()),
    )
    return get_session(cur.lastrowid)


def update_session(session_id: int, **fields) -> dict:
    cur = get_session(session_id)
    if not cur:
        raise ValueError("not found")
    allowed = {"date", "duration_min", "rpe", "notes"}
    payload = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if payload:
        sets_sql = ", ".join(f"{k} = ?" for k in payload)
        db._q(f"UPDATE gym_sessions SET {sets_sql} WHERE id = ?", (*payload.values(), session_id))
    return get_session(session_id)


def delete_session(session_id: int) -> None:
    db._q("DELETE FROM gym_sessions WHERE id = ?", (session_id,))


def replace_sets(session_id: int, sets: list[dict]) -> dict:
    if not get_session(session_id):
        raise ValueError("session not found")
    db._q("DELETE FROM gym_sets WHERE session_id = ?", (session_id,))
    for s in sets:
        db._q(
            "INSERT INTO gym_sets (session_id, exercise, set_idx, reps, weight_kg, rpe, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                (s.get("exercise") or "").strip(),
                int(s.get("set_idx") or 0),
                _opt_int(s.get("reps")),
                _opt_float(s.get("weight_kg")),
                _opt_float(s.get("rpe")),
                (s.get("notes") or "").strip(),
            ),
        )
    return get_session(session_id)


def known_exercises() -> list[dict]:
    rows = db._qa(
        """
        SELECT exercise,
               COUNT(*) AS sets_done,
               MAX(weight_kg) AS top_weight,
               (SELECT weight_kg FROM gym_sets s2 WHERE s2.exercise = s.exercise ORDER BY id DESC LIMIT 1) AS last_weight,
               (SELECT reps FROM gym_sets s2 WHERE s2.exercise = s.exercise ORDER BY id DESC LIMIT 1) AS last_reps
        FROM gym_sets s
        GROUP BY exercise
        ORDER BY sets_done DESC
        """
    )
    return [dict(r) for r in rows]


def _opt_int(v) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _opt_float(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
