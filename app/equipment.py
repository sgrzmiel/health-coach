"""Equipment list."""

from __future__ import annotations

from typing import Optional
from . import db


def list_all() -> list[dict]:
    rows = db._qa("SELECT * FROM equipment ORDER BY position, id")
    return [dict(r) for r in rows]


def add(name: str, kind: str = "other", detail: str = "") -> dict:
    max_pos = db._qone("SELECT MAX(position) AS m FROM equipment")
    pos = (max_pos["m"] or 0) + 1 if max_pos else 0
    cur = db._q(
        "INSERT INTO equipment (name, kind, detail, position) VALUES (?, ?, ?, ?)",
        (name.strip(), kind.strip(), detail.strip(), pos),
    )
    row = db._qone("SELECT * FROM equipment WHERE id = ?", (cur.lastrowid,))
    return dict(row)


def update(item_id: int, name: Optional[str], kind: Optional[str], detail: Optional[str]) -> dict:
    row = db._qone("SELECT * FROM equipment WHERE id = ?", (item_id,))
    if not row:
        raise ValueError("not found")
    updates = {}
    if name is not None:
        updates["name"] = name.strip()
    if kind is not None:
        updates["kind"] = kind.strip()
    if detail is not None:
        updates["detail"] = detail.strip()
    if updates:
        sets = ", ".join(f"{k} = ?" for k in updates)
        db._q(f"UPDATE equipment SET {sets} WHERE id = ?", (*updates.values(), item_id))
    return dict(db._qone("SELECT * FROM equipment WHERE id = ?", (item_id,)))


def delete(item_id: int) -> None:
    db._q("DELETE FROM equipment WHERE id = ?", (item_id,))
