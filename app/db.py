"""SQLite storage for health-coach - single WAL-mode DB."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent.parent / "health.db"
ROOT = DB_PATH.parent

_conn: Optional[sqlite3.Connection] = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, isolation_level=None)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode = WAL")
        _conn.execute("PRAGMA foreign_keys = ON")
        _ensure_schema(_conn)
        _seed_defaults(_conn)
    return _conn


def _q(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    return conn().execute(sql, params)


def _qa(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return list(_q(sql, params).fetchall())


def _qone(sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    return _q(sql, params).fetchone()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    expires_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_config (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS equipment (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'other',
    detail      TEXT NOT NULL DEFAULT '',
    position    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_equipment_position ON equipment(position);

CREATE TABLE IF NOT EXISTS garmin_activities (
    activity_id             INTEGER PRIMARY KEY,
    start_time_local        TEXT NOT NULL,
    start_time_utc          TEXT NOT NULL,
    sport                   TEXT NOT NULL,
    sub_sport               TEXT,
    name                    TEXT,
    duration_s              REAL,
    distance_m              REAL,
    calories                REAL,
    avg_hr                  REAL,
    max_hr                  REAL,
    avg_pace_min_per_km     REAL,
    elevation_gain_m        REAL,
    training_effect_aerobic REAL,
    training_effect_anaerobic REAL,
    training_load           REAL,
    vo2max                  REAL,
    raw_path                TEXT
);
CREATE INDEX IF NOT EXISTS idx_activities_start ON garmin_activities(start_time_utc DESC);
CREATE INDEX IF NOT EXISTS idx_activities_sport ON garmin_activities(sport);

CREATE TABLE IF NOT EXISTS garmin_daily_stats (
    date                    TEXT PRIMARY KEY,
    body_battery_max        INTEGER,
    body_battery_min        INTEGER,
    hrv_avg                 REAL,
    hrv_status              TEXT,
    sleep_hours             REAL,
    sleep_score             INTEGER,
    training_readiness      INTEGER,
    resting_hr              INTEGER,
    steps                   INTEGER,
    stress_avg              INTEGER,
    weight_kg               REAL,
    raw_path                TEXT
);

CREATE TABLE IF NOT EXISTS gym_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT NOT NULL,
    duration_min    INTEGER,
    rpe             INTEGER,
    notes           TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gym_sessions_date ON gym_sessions(date DESC);

CREATE TABLE IF NOT EXISTS gym_sets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES gym_sessions(id) ON DELETE CASCADE,
    exercise        TEXT NOT NULL,
    set_idx         INTEGER NOT NULL,
    reps            INTEGER,
    weight_kg       REAL,
    rpe             REAL,
    notes           TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_gym_sets_session ON gym_sets(session_id);
CREATE INDEX IF NOT EXISTS idx_gym_sets_exercise ON gym_sets(exercise);

CREATE TABLE IF NOT EXISTS withings_weights (
    date            TEXT PRIMARY KEY,
    weight_kg       REAL NOT NULL,
    fat_mass_kg     REAL,
    muscle_mass_kg  REAL,
    water_pct       REAL,
    raw_json        TEXT
);

CREATE TABLE IF NOT EXISTS withings_tokens (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    access_token    TEXT NOT NULL,
    refresh_token   TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    userid          TEXT
);

CREATE TABLE IF NOT EXISTS fitatu_tokens (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    access_token    TEXT NOT NULL,
    refresh_token   TEXT,
    user_id         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fitatu_diary (
    date            TEXT PRIMARY KEY,
    calories        REAL,
    protein_g       REAL,
    carbs_g         REAL,
    fat_g           REAL,
    fiber_g         REAL,
    water_ml        REAL,
    raw_json        TEXT
);
CREATE INDEX IF NOT EXISTS idx_fitatu_diary_date ON fitatu_diary(date DESC);

CREATE TABLE IF NOT EXISTS coach_responses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    kind            TEXT NOT NULL,
    model           TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    text            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_coach_responses_created ON coach_responses(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_coach_responses_kind ON coach_responses(kind);
"""


_MIGRATIONS = [
    "ALTER TABLE garmin_daily_stats ADD COLUMN sleep_deep_s INTEGER",
    "ALTER TABLE garmin_daily_stats ADD COLUMN sleep_light_s INTEGER",
    "ALTER TABLE garmin_daily_stats ADD COLUMN sleep_rem_s INTEGER",
    "ALTER TABLE garmin_daily_stats ADD COLUMN sleep_awake_s INTEGER",
    "ALTER TABLE garmin_daily_stats ADD COLUMN sleep_spo2_avg REAL",
    "ALTER TABLE garmin_daily_stats ADD COLUMN sleep_respiration_avg REAL",
    "ALTER TABLE garmin_daily_stats ADD COLUMN sleep_stress_avg REAL",
    "ALTER TABLE garmin_daily_stats ADD COLUMN sleep_score_feedback TEXT",
    "ALTER TABLE garmin_activities ADD COLUMN exercise_sets_json TEXT",
]


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.executescript(_SCHEMA)
    for sql in _MIGRATIONS:
        try:
            c.execute(sql)
        except sqlite3.OperationalError:
            pass


_DEFAULT_EQUIPMENT = [
    ("Składany rack", "rack", ""),
    ("Ławka regulowana/łamana", "bench", ""),
    ("Sztanga prosta 10 kg", "barbell", "max ~80-90 kg na sztandze"),
    ("Krótkie gryfy do hantli", "dumbbell", "2 kg każdy"),
    ("Obciążenia", "plates", "4x1.25, 4x2.5, 8x5, 4x10 kg"),
    ("Kettlebell 6 kg", "kettlebell", ""),
    ("Wyciąg na talerze z linką", "cable", ""),
    ("Landmine", "landmine", ""),
    ("Kółka gimnastyczne", "rings", ""),
    ("Paski do martwego ciągu", "straps", ""),
    ("Gumy oporowe", "bands", ""),
    ("Mata", "mat", ""),
    ("Trenażer rowerowy", "bike", ""),
]

_DEFAULT_CONFIG = {
    "goal_weight_kg": "79",
    "current_weight_kg": "82",
    "goal_summary": "redukcja do ponizej 80 kg, trwala poprawa zdrowia i bazy tlenowej, zachowanie sily; brak celu startowego - dlugoterminowa sprawnosc",
    "weekly_targets": "2-3x silownia FBW, 2-3x rower/bieganie, codzienny spacer z psem w Morasko",
    "calorie_target": "2200",
    "protein_target_g": "125",
    "sync_window_days": "90",
    "claude_model": "claude-sonnet-4-6",
    "ollama_model": "qwen2.5:14b",
    "ollama_base_url": "http://localhost:11434",
    "llm_provider": "auto",
}


def _seed_defaults(c: sqlite3.Connection) -> None:
    cur = c.execute("SELECT COUNT(*) FROM equipment")
    if cur.fetchone()[0] == 0:
        for pos, (name, kind, detail) in enumerate(_DEFAULT_EQUIPMENT):
            c.execute(
                "INSERT INTO equipment (name, kind, detail, position) VALUES (?, ?, ?, ?)",
                (name, kind, detail, pos),
            )
    for k, v in _DEFAULT_CONFIG.items():
        c.execute(
            "INSERT OR IGNORE INTO app_config (key, value) VALUES (?, ?)",
            (k, v),
        )


def get_config(key: str, default: Optional[str] = None) -> Optional[str]:
    row = _qone("SELECT value FROM app_config WHERE key = ?", (key,))
    return row["value"] if row else default


def set_config(key: str, value: str) -> None:
    _q(
        "INSERT INTO app_config (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def all_config() -> dict[str, str]:
    return {row["key"]: row["value"] for row in _qa("SELECT key, value FROM app_config")}
