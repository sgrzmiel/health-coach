"""Pull activities + daily stats from Garmin Connect and persist to SQLite."""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .. import db
from . import auth

RAW_DIR = db.ROOT / "data" / "raw"


def _raw_path(kind: str, name: str) -> Path:
    sub = RAW_DIR / kind / datetime.utcnow().strftime("%Y-%m")
    sub.mkdir(parents=True, exist_ok=True)
    return sub / name


def _dump_raw(kind: str, name: str, payload: Any) -> str:
    path = _raw_path(kind, name)
    path.write_text(json.dumps(payload, indent=2, default=str))
    return str(path.relative_to(db.ROOT))


def _as_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _pace_min_per_km(distance_m: Optional[float], duration_s: Optional[float]) -> Optional[float]:
    if not distance_m or not duration_s or distance_m <= 0:
        return None
    return (duration_s / 60.0) / (distance_m / 1000.0)


def _exercise_sets_json(a: dict) -> Optional[str]:
    sets = a.get("summarizedExerciseSets")
    if not sets:
        return None
    cleaned = []
    for s in sets:
        cat = s.get("category") or ""
        sub = s.get("subCategory") or ""
        name = sub if sub else cat
        weight_g = s.get("maxWeight") or 0
        vol_g = s.get("volume") or 0
        entry = {
            "name": name,
            "sets": s.get("sets") or 0,
            "reps": s.get("reps") or 0,
            "max_weight_kg": round(weight_g / 1000, 2) if weight_g else 0,
            "volume_kg": round(vol_g / 1000, 1) if vol_g else 0,
        }
        cleaned.append(entry)
    return json.dumps(cleaned, ensure_ascii=False)


def _persist_activity(a: dict) -> None:
    activity_id = int(a["activityId"])
    sport = (a.get("activityType") or {}).get("typeKey") or "unknown"
    sub_sport = ((a.get("eventType") or {}).get("typeKey")) or None
    start_local = a.get("startTimeLocal") or ""
    start_utc = a.get("startTimeGMT") or start_local
    distance_m = _as_float(a.get("distance"))
    duration_s = _as_float(a.get("duration"))
    raw_path = _dump_raw("activities", f"{activity_id}.json", a)
    ex_sets = _exercise_sets_json(a)

    db._q(
        """
        INSERT OR REPLACE INTO garmin_activities (
            activity_id, start_time_local, start_time_utc, sport, sub_sport,
            name, duration_s, distance_m, calories, avg_hr, max_hr,
            avg_pace_min_per_km, elevation_gain_m,
            training_effect_aerobic, training_effect_anaerobic, training_load,
            vo2max, exercise_sets_json, raw_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            activity_id, start_local, start_utc, sport, sub_sport,
            a.get("activityName"), duration_s, distance_m,
            _as_float(a.get("calories")), _as_float(a.get("averageHR")), _as_float(a.get("maxHR")),
            _pace_min_per_km(distance_m, duration_s), _as_float(a.get("elevationGain")),
            _as_float(a.get("aerobicTrainingEffect")), _as_float(a.get("anaerobicTrainingEffect")),
            _as_float(a.get("activityTrainingLoad")), _as_float(a.get("vO2MaxValue")),
            ex_sets, raw_path,
        ),
    )


def sync_activities(days: int = 90, limit: int = 200) -> dict:
    api = auth.resume_client()
    since = datetime.now(timezone.utc) - timedelta(days=days)
    fetched = 0
    inserted = 0
    start = 0
    while True:
        batch = api.get_activities(start, limit)
        if not batch:
            break
        for a in batch:
            fetched += 1
            try:
                start_local = datetime.fromisoformat((a.get("startTimeGMT") or a.get("startTimeLocal")).replace(" ", "T"))
            except Exception:
                start_local = None
            if start_local and start_local.replace(tzinfo=timezone.utc) < since:
                return {"fetched": fetched, "inserted": inserted}
            _persist_activity(a)
            inserted += 1
        if len(batch) < limit:
            break
        start += limit
        time.sleep(0.4)
    return {"fetched": fetched, "inserted": inserted}


def _safe_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        return None


def _persist_daily(d: date, api) -> bool:
    iso = d.isoformat()
    summary = _safe_call(api.get_user_summary, iso) or {}
    readiness = _safe_call(api.get_training_readiness, iso) or []
    sleep = _safe_call(api.get_sleep_data, iso) or {}
    hrv = _safe_call(api.get_hrv_data, iso) or {}

    raw_path = _dump_raw("daily", f"{iso}.json", {"summary": summary, "readiness": readiness, "sleep": sleep, "hrv": hrv})

    bb_max = _as_int(summary.get("bodyBatteryHighestValue"))
    bb_min = _as_int(summary.get("bodyBatteryLowestValue"))
    resting_hr = _as_int(summary.get("restingHeartRate"))
    steps = _as_int(summary.get("totalSteps"))
    stress_avg = _as_int(summary.get("averageStressLevel"))

    sleep_dto = (sleep or {}).get("dailySleepDTO") or {}
    sleep_seconds = _as_float(sleep_dto.get("sleepTimeSeconds"))
    sleep_hours = round(sleep_seconds / 3600.0, 2) if sleep_seconds else None
    sleep_scores = sleep_dto.get("sleepScores") or {}
    sleep_score = _as_int(sleep_scores.get("overall", {}).get("value")) if isinstance(sleep_scores, dict) else None
    sleep_deep_s = _as_int(sleep_dto.get("deepSleepSeconds"))
    sleep_light_s = _as_int(sleep_dto.get("lightSleepSeconds"))
    sleep_rem_s = _as_int(sleep_dto.get("remSleepSeconds"))
    sleep_awake_s = _as_int(sleep_dto.get("awakeSleepSeconds"))
    sleep_spo2 = _as_float(sleep_dto.get("averageSpO2Value"))
    sleep_resp = _as_float(sleep_dto.get("averageRespirationValue"))
    sleep_stress = _as_float(sleep_dto.get("avgSleepStress"))
    sleep_feedback = sleep_dto.get("sleepScoreFeedback") or None

    hrv_summary = (hrv or {}).get("hrvSummary") or {}
    hrv_avg = _as_float(hrv_summary.get("lastNightAvg") or hrv_summary.get("weeklyAvg"))
    hrv_status = hrv_summary.get("status")

    readiness_score = None
    if isinstance(readiness, list) and readiness:
        readiness_score = _as_int(readiness[0].get("score"))
    elif isinstance(readiness, dict):
        readiness_score = _as_int(readiness.get("score"))

    db._q(
        """
        INSERT OR REPLACE INTO garmin_daily_stats (
            date, body_battery_max, body_battery_min, hrv_avg, hrv_status,
            sleep_hours, sleep_score, sleep_deep_s, sleep_light_s, sleep_rem_s,
            sleep_awake_s, sleep_spo2_avg, sleep_respiration_avg, sleep_stress_avg,
            sleep_score_feedback, training_readiness, resting_hr, steps,
            stress_avg, weight_kg, raw_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  (SELECT weight_kg FROM garmin_daily_stats WHERE date = ?), ?)
        """,
        (
            iso, bb_max, bb_min, hrv_avg, hrv_status,
            sleep_hours, sleep_score, sleep_deep_s, sleep_light_s, sleep_rem_s,
            sleep_awake_s, sleep_spo2, sleep_resp, sleep_stress,
            sleep_feedback, readiness_score, resting_hr, steps,
            stress_avg, iso, raw_path,
        ),
    )
    return True


def sync_daily_stats(days: int = 90) -> dict:
    api = auth.resume_client()
    today = datetime.now(timezone.utc).date()
    count = 0
    for i in range(days):
        d = today - timedelta(days=i)
        try:
            _persist_daily(d, api)
            count += 1
        except Exception:
            continue
        time.sleep(0.25)
    return {"days": count}


def sync_all(days: Optional[int] = None) -> dict:
    if days is None:
        cfg = db.get_config("sync_window_days") or "90"
        days = int(cfg)
    act = sync_activities(days=days)
    daily = sync_daily_stats(days=days)
    ex_backfill = _backfill_exercise_sets(days=days)
    sleep_backfill = _backfill_sleep_components(days=days)
    db.set_config("last_sync_at", datetime.now(timezone.utc).isoformat())
    return {"activities": act, "daily": daily, "days": days, "ex_backfill": ex_backfill, "sleep_backfill": sleep_backfill}


def recent_activities(limit: int = 20) -> list[dict]:
    rows = db._qa("SELECT * FROM garmin_activities ORDER BY start_time_utc DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


def _backfill_exercise_sets(days: int = 90) -> dict:
    """Re-read raw activity JSON files and populate exercise_sets_json for existing rows."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date()
    rows = db._qa(
        "SELECT activity_id, start_time_local, raw_path FROM garmin_activities WHERE exercise_sets_json IS NULL AND raw_path IS NOT NULL"
    )
    updated = 0
    for r in rows:
        date_str = (r["start_time_local"] or "")[:10]
        try:
            if date_str and date_str < since.isoformat():
                continue
            raw_file = db.ROOT / r["raw_path"]
            if not raw_file.exists():
                continue
            a = json.loads(raw_file.read_text())
            ex_sets = _exercise_sets_json(a)
            if ex_sets:
                db._q("UPDATE garmin_activities SET exercise_sets_json = ? WHERE activity_id = ?", (ex_sets, r["activity_id"]))
                updated += 1
        except Exception:
            continue
    return {"updated": updated}


def recent_daily(limit: int = 14) -> list[dict]:
    rows = db._qa("SELECT * FROM garmin_daily_stats ORDER BY date DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


def _backfill_sleep_components(days: int = 90) -> dict:
    """Re-read raw daily JSON files and populate sleep component columns for existing rows."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    rows = db._qa(
        "SELECT date, raw_path FROM garmin_daily_stats WHERE sleep_deep_s IS NULL AND raw_path IS NOT NULL AND date >= ?",
        (since,),
    )
    updated = 0
    for r in rows:
        try:
            raw_file = db.ROOT / r["raw_path"]
            if not raw_file.exists():
                continue
            data = json.loads(raw_file.read_text())
            sleep_dto = (data.get("sleep") or {}).get("dailySleepDTO") or {}
            deep = _as_int(sleep_dto.get("deepSleepSeconds"))
            light = _as_int(sleep_dto.get("lightSleepSeconds"))
            rem = _as_int(sleep_dto.get("remSleepSeconds"))
            awake = _as_int(sleep_dto.get("awakeSleepSeconds"))
            spo2 = _as_float(sleep_dto.get("averageSpO2Value"))
            resp = _as_float(sleep_dto.get("averageRespirationValue"))
            stress = _as_float(sleep_dto.get("avgSleepStress"))
            feedback = sleep_dto.get("sleepScoreFeedback") or None
            if any(v is not None for v in [deep, light, rem, awake]):
                db._q(
                    "UPDATE garmin_daily_stats SET sleep_deep_s=?, sleep_light_s=?, sleep_rem_s=?, sleep_awake_s=?, sleep_spo2_avg=?, sleep_respiration_avg=?, sleep_stress_avg=?, sleep_score_feedback=? WHERE date=?",
                    (deep, light, rem, awake, spo2, resp, stress, feedback, r["date"]),
                )
                updated += 1
        except Exception:
            continue
    return {"updated": updated}
