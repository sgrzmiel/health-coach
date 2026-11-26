"""Settings - secrets in .env, config in SQLite."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import db

ENV_PATH = Path(__file__).parent.parent / ".env"

SECRET_KEYS = {
    "ANTHROPIC_API_KEY",
    "GARMIN_PASSWORD",
    "APP_PASSWORD",
    "WITHINGS_CLIENT_SECRET",
    "FITATU_PASSWORD",
}
PLAIN_KEYS = {
    "GARMIN_EMAIL",
    "WITHINGS_CLIENT_ID",
    "GARMIN_INITIAL_DAYS",
    "FITATU_EMAIL",
    "OLLAMA_BASE_URL",
}
ALL_ENV_KEYS = SECRET_KEYS | PLAIN_KEYS

CONFIG_KEYS = {
    "goal_weight_kg",
    "current_weight_kg",
    "goal_summary",
    "weekly_targets",
    "calorie_target",
    "protein_target_g",
    "sync_window_days",
    "claude_model",
    "ollama_model",
    "ollama_base_url",
    "llm_provider",
    "last_sync_at",
    "last_fitatu_sync_at",
}


def _parse_env_file() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    out: dict[str, str] = {}
    for raw in ENV_PATH.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _write_env_file(values: dict[str, str]) -> None:
    existing_lines: list[str] = []
    if ENV_PATH.exists():
        existing_lines = ENV_PATH.read_text().splitlines()

    written: set[str] = set()
    new_lines: list[str] = []
    for raw in existing_lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(raw)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in values:
            new_lines.append(f"{key}={values[key]}")
            written.add(key)
        else:
            new_lines.append(raw)

    for k, v in values.items():
        if k not in written:
            new_lines.append(f"{k}={v}")

    ENV_PATH.write_text("\n".join(new_lines) + "\n")


def _preview(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def sync_env_from_disk() -> None:
    file_values = _parse_env_file()
    for k, v in file_values.items():
        if k not in ALL_ENV_KEYS:
            continue
        if v.strip():
            os.environ[k] = v
        elif not os.environ.get(k, "").strip():
            os.environ[k] = ""


def get_status() -> dict[str, Any]:
    sync_env_from_disk()
    file_values = _parse_env_file()
    live = {k: os.environ[k] for k in ALL_ENV_KEYS if os.environ.get(k, "").strip()}
    merged = {**file_values, **live}

    env_out: dict[str, Any] = {}
    for k in PLAIN_KEYS:
        env_out[k] = merged.get(k, "")
    for k in SECRET_KEYS:
        val = merged.get(k, "")
        env_out[k] = {"set": bool(val), "preview": _preview(val)}

    cfg = db.all_config()
    config_out = {k: cfg.get(k, "") for k in CONFIG_KEYS}

    return {"env": env_out, "config": config_out}


def update_env(updates: dict[str, str]) -> dict[str, Any]:
    file_values = _parse_env_file()
    merged = dict(file_values)
    for k, v in updates.items():
        if k not in ALL_ENV_KEYS or v is None:
            continue
        v = v.strip()
        if v == "":
            continue
        merged[k] = v
        os.environ[k] = v
    _write_env_file(merged)
    return get_status()


def update_config(updates: dict[str, str]) -> dict[str, Any]:
    for k, v in updates.items():
        if k not in CONFIG_KEYS or v is None:
            continue
        db.set_config(k, str(v))
    return get_status()
