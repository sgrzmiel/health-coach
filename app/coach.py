"""AI coaching - 4 modes: plan, eval, recovery, nutrition-training analysis.

Providers (auto-detected):
  Anthropic - when ANTHROPIC_API_KEY is set in .env / env
  Ollama    - fallback, runs locally (http://localhost:11434 by default)
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Type, TypeVar

import httpx
from pydantic import BaseModel, Field

from . import db, equipment, gym, fitatu
from .garmin import sync as garmin_sync

PROMPT_DIR = Path(__file__).parent.parent / "prompts"
DAY_NAMES_PL = ["Pn", "Wt", "Sr", "Cz", "Pt", "So", "Nd"]

_PROFILE: str = ""
_PROFILE_MTIME: float = 0.0


def _profile() -> str:
    global _PROFILE, _PROFILE_MTIME
    p = PROMPT_DIR / "profile.md"
    if p.exists():
        mtime = p.stat().st_mtime
        if mtime != _PROFILE_MTIME:
            _PROFILE = p.read_text()
            _PROFILE_MTIME = mtime
    return _PROFILE


def _system(prompt_file: str) -> str:
    base = (PROMPT_DIR / prompt_file).read_text()
    profile = _profile()
    if profile:
        return f"{profile}\n\n---\n\n{base}"
    return base

T = TypeVar("T", bound=BaseModel)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PlannedExercise(BaseModel):
    name: str = Field(description="Nazwa cwiczenia, np. 'BSS lewe/prawe', 'Wyciskanie ze sztanga'")
    sets: int = Field(description="Liczba serii")
    reps: str = Field(description="Zakres powtozen np. '8-10' lub '5' lub 'do upadku'")
    weight_kg: Optional[float] = Field(default=None, description="Ciezar w kg; null dla cwiczen BW lub gdy nie dotyczy")
    notes: Optional[str] = Field(default=None, description="RPE, wskazowka techniczna lub progresja")


class GymSessionPlan(BaseModel):
    rationale: str = Field(description="1-2 zdania: dlaczego taki dobor cwiczen i obciazen dzisiaj")
    warmup: str = Field(description="Opis rozgrzewki, 2-3 minuty")
    exercises: list[PlannedExercise] = Field(min_length=8, max_length=12, description="Pelna lista cwiczen FBW - MINIMUM 8 cwiczen, maksymalnie 12")
    cooldown: str = Field(description="Schlodzenie i rozciaganie po sesji, 2-3 minuty")


class CoachDay(BaseModel):
    day: str = Field(description="Np. 'Pn 2026-06-02'")
    focus: str = Field(description="Krotki opis np. 'Silka FBW' / 'Rower Z2 45 min' / 'Rest'")
    intent: str = Field(description="1-2 zdania uzasadniajace wybor")
    session: str = Field(description="Opis sesji: dla dni cardio/rest - konkretna recepta; dla silki - krotkie zdanie uzupelniajace liste cwiczen")
    exercises: list[PlannedExercise] = Field(default=[], description="Dla dni silowych: MINIMUM 8 cwiczen z seriami, powt. i ciezarem. Dla cardio i rest: pusta lista [].")


class PlanResponse(BaseModel):
    diagnosis: list[str] = Field(description="3-6 bulletek: obserwacje co dziala, co sie pogarsza")
    issues: list[str] = Field(description="0-5 bulletek: bledy treningowe / ryzyka")
    plan: list[CoachDay] = Field(description="Dokladnie 7 dni poczawszy od PLAN_START_DATE")


class WorkoutEval(BaseModel):
    score: int = Field(description="Ocena jakosci sesji 1-10")
    summary: str = Field(description="2-3 zdania oceny sesji")
    positives: list[str] = Field(description="2-4 bullety: co poszlo dobrze")
    concerns: list[str] = Field(description="0-3 bullety: cos do obserwacji/poprawy")
    next_session: str = Field(description="1-2 zdania: rekomendacja na nastepna podobna sesje")


class RecoveryAssessment(BaseModel):
    score: int = Field(description="Ocena regeneracji 1-10 (10=pelna gotowsc)")
    status: str = Field(description="ready | moderate | fatigued | overreached")
    summary: str = Field(description="2-3 zdania o stanie regeneracji")
    signals: list[str] = Field(description="3-5 bulletek: sygnaly ktore decyduja o ocenie")
    recommendation: str = Field(description="1-2 zdania: co robic dzisiaj/jutro")


class NutritionAnalysis(BaseModel):
    summary: str = Field(description="2-3 zdania o wzorcach zywieniowych")
    patterns: list[str] = Field(description="3-5 bulletek: zaobserwowane wzorce")
    correlations: list[str] = Field(description="2-4 bulletek: zwiazki zywienie-wydolnosc")
    recommendations: list[str] = Field(description="3-5 konkretnych rekomendacji")


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------


def _use_anthropic() -> bool:
    provider = db.get_config("llm_provider") or "auto"
    if provider == "ollama":
        return False
    if provider == "anthropic":
        return True
    # auto: use anthropic only if key is set
    return bool((os.environ.get("ANTHROPIC_API_KEY") or "").strip())


def _get_model() -> str:
    cfg_model = db.get_config("claude_model") or "claude-sonnet-4-6"
    if _use_anthropic():
        return cfg_model
    # Ollama model from config (separate key) or default
    return db.get_config("ollama_model") or "qwen2.5:14b"


def _ollama_base() -> str:
    return (os.environ.get("OLLAMA_BASE_URL") or db.get_config("ollama_base_url") or "http://localhost:11434").rstrip("/")


# ---------------------------------------------------------------------------
# LLM call - unified interface
# ---------------------------------------------------------------------------


def _chat(system: str, user: str, schema: Type[T], max_tokens: int = 4096, high_effort: bool = False) -> T:
    if _use_anthropic():
        return _chat_anthropic(system, user, schema, max_tokens, high_effort)
    return _chat_ollama(system, user, schema, max_tokens)


def _chat_anthropic(system: str, user: str, schema: Type[T], max_tokens: int, high_effort: bool) -> T:
    import anthropic as _anthropic

    key = os.environ["ANTHROPIC_API_KEY"].strip()
    client = _anthropic.Anthropic(api_key=key)
    model = db.get_config("claude_model") or "claude-sonnet-4-6"

    kwargs: dict = dict(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_format=schema,
    )
    if high_effort:
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"] = {"effort": "high"}

    response = client.messages.parse(**kwargs)
    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError(f"Anthropic: no structured output. stop_reason={response.stop_reason}")
    return parsed


def _compact_schema_hint(schema: Type[BaseModel]) -> str:
    """Build a short JSON example from model fields to guide Ollama output."""
    props = schema.model_json_schema().get("properties", {})
    lines = []
    for name, info in props.items():
        t = info.get("type", "")
        desc = info.get("description", "")
        if t == "array":
            lines.append(f'  "{name}": ["..."]')
        elif t == "integer":
            lines.append(f'  "{name}": 0')
        elif t == "number":
            lines.append(f'  "{name}": 0.0')
        else:
            lines.append(f'  "{name}": "..."')
        if desc:
            lines[-1] += f"  // {desc}"
    return "{\n" + ",\n".join(lines) + "\n}"


def _chat_ollama(system: str, user: str, schema: Type[T], max_tokens: int = 4096) -> T:
    model = db.get_config("ollama_model") or "qwen2.5:14b"
    base = _ollama_base()

    schema_hint = _compact_schema_hint(schema)
    user_with_hint = f"{user}\n\nOdpowiedz WYLACZNIE poprawnym JSON (bez komentarzy, bez markdown):\n{schema_hint}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_with_hint},
        ],
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.3, "num_ctx": 12288, "num_predict": max_tokens},
    }

    try:
        r = httpx.post(f"{base}/api/chat", json=payload, timeout=300.0)
        r.raise_for_status()
    except httpx.TimeoutException:
        raise RuntimeError(
            f"Ollama timeout (300s) — model {model} nie odpowiada. "
            "Sprawdz 'ollama ps', jesli wisi: zrestartuj Ollama."
        )
    except httpx.ConnectError:
        raise RuntimeError(f"Ollama nie odpowiada pod {base} — czy serwer jest uruchomiony? (ollama serve)")
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"Ollama HTTP {exc.response.status_code}: {exc.response.text[:300]}")

    data = r.json()
    content = (data.get("message") or {}).get("content", "")
    if not content:
        raise RuntimeError(f"Ollama: pusta odpowiedz. done_reason={data.get('done_reason')}")

    # Strip markdown fences if model wrapped output
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        raw = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ollama: niepoprawny JSON: {exc}\n{stripped[:400]}")

    return schema.model_validate(raw)


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------


def _activities_ctx(days: int = 28) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = db._qa("SELECT * FROM garmin_activities WHERE start_time_utc >= ? ORDER BY start_time_utc DESC", (since,))
    result = []
    for r in rows:
        entry: dict = {
            "date": (r["start_time_local"] or "")[:10],
            "sport": r["sport"],
            "name": r["name"],
            "duration_min": round((r["duration_s"] or 0) / 60.0, 1) if r["duration_s"] else None,
            "distance_km": round((r["distance_m"] or 0) / 1000.0, 2) if r["distance_m"] else None,
            "avg_hr": int(r["avg_hr"]) if r["avg_hr"] else None,
            "max_hr": int(r["max_hr"]) if r["max_hr"] else None,
            "training_load": r["training_load"],
            "calories": int(r["calories"]) if r["calories"] else None,
        }
        if r["exercise_sets_json"]:
            try:
                entry["exercise_sets"] = json.loads(r["exercise_sets_json"])
            except Exception:
                pass
        result.append(entry)
    return result


def _daily_ctx(days: int = 14) -> list[dict]:
    rows = db._qa("SELECT * FROM garmin_daily_stats ORDER BY date DESC LIMIT ?", (days,))
    return [dict(r) for r in rows]


def _gym_ctx(days: int = 28) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    sessions = db._qa("SELECT * FROM gym_sessions WHERE date >= ? ORDER BY date DESC", (since,))
    out = []
    for s in sessions:
        sets = db._qa("SELECT * FROM gym_sets WHERE session_id = ? ORDER BY exercise, set_idx", (s["id"],))
        out.append({
            "date": s["date"],
            "duration_min": s["duration_min"],
            "rpe": s["rpe"],
            "notes": s["notes"],
            "sets": [{"exercise": x["exercise"], "set_idx": x["set_idx"], "reps": x["reps"], "weight_kg": x["weight_kg"], "rpe": x["rpe"]} for x in sets],
        })
    return out


def _weight_ctx(days: int = 60) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = db._qa("SELECT date, weight_kg, fat_mass_kg, muscle_mass_kg FROM withings_weights WHERE date >= ? ORDER BY date DESC", (since,))
    return [dict(r) for r in rows]


def _nutrition_ctx(days: int = 30) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = db._qa("SELECT date, calories, protein_g, carbs_g, fat_g, fiber_g FROM fitatu_diary WHERE date >= ? ORDER BY date DESC", (since,))
    return [dict(r) for r in rows]


def _equipment_lines() -> list[str]:
    return [f"- {e['name']}" + (f" ({e['detail']})" if e["detail"] else "") for e in equipment.list_all()]


def _save_response(kind: str, model: str, payload: dict, text: str) -> None:
    db._q(
        "INSERT INTO coach_responses (created_at, kind, model, payload_json, text) VALUES (?, ?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), kind, model, json.dumps(payload, ensure_ascii=False), text),
    )


# ---------------------------------------------------------------------------
# Mode 1: 7-day training plan
# ---------------------------------------------------------------------------


def generate_plan() -> dict:
    cfg = db.all_config()
    plan_start = date.today() + timedelta(days=1)
    day_labels = [
        f"{DAY_NAMES_PL[(plan_start + timedelta(days=i)).weekday()]} {(plan_start + timedelta(days=i)).isoformat()}"
        for i in range(7)
    ]

    system = _system("plan.md")
    user_msg = "\n".join([
        f"DZIS: {date.today().isoformat()} ({DAY_NAMES_PL[date.today().weekday()]})",
        f"PLAN_START_DATE: {plan_start.isoformat()}",
        f"7 dni planu: {', '.join(day_labels)}",
        "",
        f"CEL OGOLNY: {cfg.get('goal_summary', '')}",
        f"WAGA: aktualna {cfg.get('current_weight_kg', '?')} kg -> cel {cfg.get('goal_weight_kg', '?')} kg",
        f"CELE TYGODNIOWE: {cfg.get('weekly_targets', '')}",
        f"CEL KALORYCZNY: {cfg.get('calorie_target', '?')} kcal/dzien, bialko: {cfg.get('protein_target_g', '?')} g",
        "",
        "SPRZET:",
        *_equipment_lines(),
        "",
        "HISTORIA WAGI (60 dni):",
        json.dumps(_weight_ctx(60), indent=2, ensure_ascii=False),
        "",
        "OSTATNIE 14 DNI - DZIENNE METRYKI GARMIN:",
        json.dumps(_daily_ctx(14), indent=2, ensure_ascii=False),
        "",
        "OSTATNIE 28 DNI - AKTYWNOSCI:",
        json.dumps(_activities_ctx(28), indent=2, ensure_ascii=False),
        "",
        "OSTATNIE 28 DNI - SESJE SILOWE:",
        json.dumps(_gym_ctx(28), indent=2, ensure_ascii=False),
        "",
        "OSTATNIE 30 DNI - ZYWIENIE (Fitatu):",
        json.dumps(_nutrition_ctx(30), indent=2, ensure_ascii=False),
        "",
        "CWICZENIA Z HISTORII (progresja ciezarow - z logu silowni w aplikacji):",
        json.dumps(gym.known_exercises(), indent=2, ensure_ascii=False),
        "",
        "Wykryj bledy. Zaproponuj plan 7 dni. Uwzglednij dane zywieniowe.",
        "WAZNE - dni silowe: pole 'exercises' MUSI zawierac pelna liste cwiczen FBW (8-12 cwiczen) z seriami, powt. i ciezarem.",
        "Jesli 'CWICZENIA Z HISTORII' sa puste - dobierz ciazary startowe na podstawie wagi ciala uzytkownika i dostepnego sprzetu. Nie zglaszaj braku historii jako bledu.",
        "BSS zawsze pierwsze. Cardio i rest: pole 'exercises' = [].",
    ])

    parsed = _chat(system, user_msg, PlanResponse, max_tokens=8000, high_effort=True)
    model = _get_model()
    text = _render_plan(parsed)
    payload = parsed.model_dump()
    _save_response("plan", model, payload, text)
    return payload


def _render_plan(p: PlanResponse) -> str:
    lines = []
    if p.diagnosis:
        lines += ["== DIAGNOZA ==", *[f"- {d}" for d in p.diagnosis], ""]
    if p.issues:
        lines += ["== BLEDY / RYZYKA ==", *[f"- {d}" for d in p.issues], ""]
    lines.append("== PLAN 7 DNI ==")
    for day in p.plan:
        lines.append(f"\n[{day.day}] {day.focus}")
        if day.intent:
            lines.append(f"  {day.intent}")
        for s in day.session.splitlines():
            lines.append(f"    {s}")
        for ex in day.exercises:
            w = f" @ {ex.weight_kg} kg" if ex.weight_kg else ""
            note = f"  ({ex.notes})" if ex.notes else ""
            lines.append(f"    • {ex.name}: {ex.sets}×{ex.reps}{w}{note}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mode 1b: Single gym session generator
# ---------------------------------------------------------------------------


def generate_gym_session() -> dict:
    cfg = db.all_config()
    today = date.today()

    system = _system("gym_session.md")
    user_msg = "\n".join([
        f"DZIS: {today.isoformat()} ({DAY_NAMES_PL[today.weekday()]})",
        "",
        f"CEL OGOLNY: {cfg.get('goal_summary', '')}",
        f"WAGA: {cfg.get('current_weight_kg', '?')} kg",
        "",
        "SPRZET:",
        *_equipment_lines(),
        "",
        "DZISIEJSZE METRYKI GARMIN (regeneracja):",
        json.dumps(dict(db._qone("SELECT * FROM garmin_daily_stats WHERE date = ?", (today.isoformat(),)) or {}), indent=2, ensure_ascii=False),
        "",
        "OSTATNIE 7 DNI - AKTYWNOSCI (kontekst obciazenia):",
        json.dumps(_activities_ctx(7), indent=2, ensure_ascii=False),
        "",
        "OSTATNIE 28 DNI - SESJE SILOWE (progresja):",
        json.dumps(_gym_ctx(28), indent=2, ensure_ascii=False),
        "",
        "CWICZENIA Z HISTORII (ostatnie ciazary):",
        json.dumps(gym.known_exercises(), indent=2, ensure_ascii=False),
        "",
        "Wygeneruj sesje silowni na dzis. Jesli brak historii - dobierz ciazary startowe na podstawie wagi ciala i sprzetu.",
        "Pole 'exercises' MUSI miec 8-12 cwiczen z seriami, powt. i ciezarem. BSS zawsze pierwsze.",
    ])

    parsed = _chat(system, user_msg, GymSessionPlan, max_tokens=3000, high_effort=True)
    model = _get_model()
    lines = [parsed.rationale, "", "== ROZGRZEWKA ==", parsed.warmup, "", "== CWICZENIA =="]
    for ex in parsed.exercises:
        w = f" @ {ex.weight_kg} kg" if ex.weight_kg else " (BW)"
        note = f"  ({ex.notes})" if ex.notes else ""
        lines.append(f"• {ex.name}: {ex.sets}×{ex.reps}{w}{note}")
    lines += ["", "== SCHLODZENIE ==", parsed.cooldown]
    text = "\n".join(lines)
    payload = parsed.model_dump()
    _save_response("gym-session", model, payload, text)
    return payload


# ---------------------------------------------------------------------------
# Mode 2: Post-workout evaluation
# ---------------------------------------------------------------------------


def evaluate_workout(kind: str, item_id: int) -> dict:
    cfg = db.all_config()

    gym_history: list[dict] = []
    _DAILY_EVAL_KEYS = {
        "date", "sleep_hours", "sleep_score", "sleep_deep_s", "sleep_rem_s",
        "body_battery_max", "body_battery_min", "hrv_avg", "hrv_status",
        "resting_hr", "training_readiness", "stress_avg",
    }
    _NUTRITION_EVAL_KEYS = {"date", "calories", "protein_g", "carbs_g", "fat_g"}

    if kind == "garmin":
        row = db._qone("SELECT * FROM garmin_activities WHERE activity_id = ?", (item_id,))
        if not row:
            raise ValueError(f"Activity {item_id} not found")
        raw = dict(row)
        date_str = (raw.get("start_time_local") or "")[:10]
        daily = db._qone("SELECT * FROM garmin_daily_stats WHERE date = ?", (date_str,))
        nutrition = db._qone("SELECT * FROM fitatu_diary WHERE date = ?", (date_str,))
        activity: dict = {
            "date": date_str,
            "sport": raw.get("sport"),
            "name": raw.get("name"),
            "duration_min": round((raw["duration_s"] or 0) / 60.0, 1) if raw.get("duration_s") else None,
            "distance_km": round((raw["distance_m"] or 0) / 1000.0, 2) if raw.get("distance_m") else None,
            "avg_hr": int(raw["avg_hr"]) if raw.get("avg_hr") else None,
            "max_hr": int(raw["max_hr"]) if raw.get("max_hr") else None,
            "training_load": raw.get("training_load"),
            "calories": int(raw["calories"]) if raw.get("calories") else None,
            "training_effect_aerobic": raw.get("training_effect_aerobic"),
            "training_effect_anaerobic": raw.get("training_effect_anaerobic"),
        }
        if raw.get("exercise_sets_json"):
            try:
                activity["exercise_sets"] = json.loads(raw["exercise_sets_json"])
            except Exception:
                pass
        session_desc = json.dumps(activity, indent=2, ensure_ascii=False)
    else:
        session = gym.get_session(item_id)
        if not session:
            raise ValueError(f"Gym session {item_id} not found")
        date_str = session["date"]
        daily = db._qone("SELECT * FROM garmin_daily_stats WHERE date = ?", (date_str,))
        nutrition = db._qone("SELECT * FROM fitatu_diary WHERE date = ?", (date_str,))
        session_desc = json.dumps(session, indent=2, ensure_ascii=False)
        gym_history = _gym_ctx(42)
        gym_history = [s for s in gym_history if s.get("date") != date_str][:5]

    daily_trimmed = {k: v for k, v in dict(daily).items() if k in _DAILY_EVAL_KEYS} if daily else {}
    nutrition_trimmed = {k: v for k, v in dict(nutrition).items() if k in _NUTRITION_EVAL_KEYS} if nutrition else None

    system = _system("eval.md")
    parts = [
        f"SESJA ({kind.upper()}) - {date_str}:",
        session_desc,
        "",
        "METRYKI DNIA (Garmin):",
        json.dumps(daily_trimmed, indent=2, ensure_ascii=False),
    ]
    if nutrition_trimmed:
        parts += ["", "ZYWIENIE TEGO DNIA:", json.dumps(nutrition_trimmed, indent=2, ensure_ascii=False)]
    if gym_history:
        parts += ["", "POPRZEDNIE SESJE SILOWNI (do 5, do oceny progresji):", json.dumps(gym_history, indent=2, ensure_ascii=False)]
    parts += ["", f"CEL OGOLNY: {cfg.get('goal_summary', '')}", "Oceń tę sesję."]
    user_msg = "\n".join(parts)

    parsed = _chat(system, user_msg, WorkoutEval, max_tokens=2000)
    model = _get_model()
    payload = parsed.model_dump()
    text = f"[{kind.upper()} {item_id} - {date_str}] Ocena: {parsed.score}/10\n{parsed.summary}"
    _save_response("eval", model, payload, text)
    return payload


# ---------------------------------------------------------------------------
# Mode 3: Recovery assessment
# ---------------------------------------------------------------------------


def assess_recovery() -> dict:
    cfg = db.all_config()

    system = _system("recovery.md")
    user_msg = "\n".join([
        f"DZIS: {date.today().isoformat()} ({DAY_NAMES_PL[date.today().weekday()]})",
        f"CEL OGOLNY: {cfg.get('goal_summary', '')}",
        "",
        "OSTATNIE 7 DNI - METRYKI GARMIN:",
        json.dumps(_daily_ctx(7), indent=2, ensure_ascii=False),
        "",
        "OSTATNIE 7 DNI - AKTYWNOSCI:",
        json.dumps(_activities_ctx(7), indent=2, ensure_ascii=False),
        "",
        "OSTATNIE 14 DNI - WAGA:",
        json.dumps(_weight_ctx(14), indent=2, ensure_ascii=False),
        "",
        "OSTATNIE 7 DNI - ZYWIENIE:",
        json.dumps(_nutrition_ctx(7), indent=2, ensure_ascii=False),
        "",
        "Oceń aktualny stan regeneracji.",
    ])

    parsed = _chat(system, user_msg, RecoveryAssessment, max_tokens=1500)
    model = _get_model()
    payload = parsed.model_dump()
    text = f"[Regeneracja {date.today().isoformat()}] {parsed.status} ({parsed.score}/10)\n{parsed.summary}"
    _save_response("recovery", model, payload, text)
    return payload


# ---------------------------------------------------------------------------
# Mode 4: Nutrition-training correlation
# ---------------------------------------------------------------------------


def analyze_nutrition() -> dict:
    cfg = db.all_config()

    system = _system("nutrition.md")
    user_msg = "\n".join([
        f"DZIS: {date.today().isoformat()}",
        f"CEL OGOLNY: {cfg.get('goal_summary', '')}",
        f"CEL KALORYCZNY: {cfg.get('calorie_target', '?')} kcal, bialko: {cfg.get('protein_target_g', '?')} g",
        "",
        "OSTATNIE 30 DNI - ZYWIENIE DZIENNE (Fitatu):",
        json.dumps(_nutrition_ctx(30), indent=2, ensure_ascii=False),
        "",
        "OSTATNIE 30 DNI - AKTYWNOSCI:",
        json.dumps(_activities_ctx(30), indent=2, ensure_ascii=False),
        "",
        "OSTATNIE 30 DNI - METRYKI DZIENNE (HRV, sen, body battery):",
        json.dumps(_daily_ctx(30), indent=2, ensure_ascii=False),
        "",
        "OSTATNIE 30 DNI - ZMIANY WAGI / SKLADOWEJ:",
        json.dumps(_weight_ctx(30), indent=2, ensure_ascii=False),
        "",
        "Przeanalizuj zaleznosc miedzy zywienia a treningiem i regeneracja.",
    ])

    parsed = _chat(system, user_msg, NutritionAnalysis, max_tokens=2500)
    model = _get_model()
    payload = parsed.model_dump()
    text = f"[Analiza zywieniowa {date.today().isoformat()}]\n{parsed.summary}"
    _save_response("nutrition", model, payload, text)
    return payload


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


def history(kind: Optional[str] = None, limit: int = 10) -> list[dict]:
    if kind:
        rows = db._qa(
            "SELECT id, created_at, kind, model, text FROM coach_responses WHERE kind = ? ORDER BY created_at DESC LIMIT ?",
            (kind, limit),
        )
    else:
        rows = db._qa(
            "SELECT id, created_at, kind, model, text FROM coach_responses ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Provider info (for settings UI)
# ---------------------------------------------------------------------------


def provider_info() -> dict:
    if _use_anthropic():
        return {"provider": "anthropic", "model": db.get_config("claude_model") or "claude-sonnet-4-6"}
    return {
        "provider": "ollama",
        "model": db.get_config("ollama_model") or "qwen2.5:14b",
        "base_url": _ollama_base(),
    }
