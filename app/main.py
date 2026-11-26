"""FastAPI entrypoint for health-coach."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from . import auth, coach, db, equipment, fitatu, gym, settings as settings_module, withings
from .garmin import auth as garmin_auth, sync as garmin_sync

db.conn()
settings_module.sync_env_from_disk()

app = FastAPI(title="health-coach")
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    password: str


class EnvUpdate(BaseModel):
    updates: dict[str, str]


class ConfigUpdate(BaseModel):
    updates: dict[str, str]


class EquipmentCreate(BaseModel):
    name: str
    kind: str = "other"
    detail: str = ""


class EquipmentUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    detail: Optional[str] = None


class GarminLogin(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None


class GarminMFA(BaseModel):
    code: str


class SyncRequest(BaseModel):
    days: Optional[int] = None


class GymSessionCreate(BaseModel):
    date: str
    duration_min: Optional[int] = None
    rpe: Optional[int] = None
    notes: str = ""


class GymSessionUpdate(BaseModel):
    date: Optional[str] = None
    duration_min: Optional[int] = None
    rpe: Optional[int] = None
    notes: Optional[str] = None


class GymSetPayload(BaseModel):
    exercise: str
    set_idx: int = 0
    reps: Optional[int] = None
    weight_kg: Optional[float] = None
    rpe: Optional[float] = None
    notes: str = ""


class GymSetsReplace(BaseModel):
    sets: list[GymSetPayload]


class FitatuLogin(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None


class FitatuSyncRequest(BaseModel):
    days: Optional[int] = None


class EvalRequest(BaseModel):
    kind: str  # "garmin" or "gym"
    id: int


# ---------------------------------------------------------------------------
# Index + auth
# ---------------------------------------------------------------------------


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/auth/status")
def auth_status(hc_session: Optional[str] = Cookie(default=None, alias=auth.COOKIE_NAME)) -> dict:
    return auth.current_status(hc_session)


@app.post("/api/auth/login")
def auth_login(req: LoginRequest, response: Response) -> dict:
    if not auth.login(req.password, response):
        raise HTTPException(status_code=401, detail="bad password")
    return {"ok": True}


@app.post("/api/auth/logout")
def auth_logout(response: Response, hc_session: Optional[str] = Cookie(default=None, alias=auth.COOKIE_NAME)) -> dict:
    auth.logout(hc_session, response)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@app.get("/api/settings")
def settings_get() -> dict:
    return settings_module.get_status()


@app.post("/api/settings/env", dependencies=[Depends(auth.require_auth)])
def settings_update_env(req: EnvUpdate) -> dict:
    return settings_module.update_env(req.updates)


@app.post("/api/settings/config", dependencies=[Depends(auth.require_auth)])
def settings_update_config(req: ConfigUpdate) -> dict:
    return settings_module.update_config(req.updates)


# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------


@app.get("/api/equipment")
def equipment_list() -> dict:
    return {"items": equipment.list_all()}


@app.post("/api/equipment", dependencies=[Depends(auth.require_auth)])
def equipment_add(req: EquipmentCreate) -> dict:
    return {"item": equipment.add(req.name, req.kind, req.detail)}


@app.patch("/api/equipment/{item_id}", dependencies=[Depends(auth.require_auth)])
def equipment_patch(item_id: int, req: EquipmentUpdate) -> dict:
    try:
        return {"item": equipment.update(item_id, req.name, req.kind, req.detail)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/api/equipment/{item_id}", dependencies=[Depends(auth.require_auth)])
def equipment_delete(item_id: int) -> dict:
    equipment.delete(item_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Garmin
# ---------------------------------------------------------------------------


@app.get("/api/garmin/status")
def garmin_status() -> dict:
    return garmin_auth.login_status()


@app.post("/api/garmin/login", dependencies=[Depends(auth.require_auth)])
def garmin_login(req: GarminLogin) -> dict:
    email = (req.email or os.environ.get("GARMIN_EMAIL") or "").strip()
    password = (req.password or os.environ.get("GARMIN_PASSWORD") or "").strip()
    if not email or not password:
        raise HTTPException(status_code=400, detail="Garmin email + password required")
    return garmin_auth.start_login(email, password)


@app.post("/api/garmin/mfa", dependencies=[Depends(auth.require_auth)])
def garmin_mfa(req: GarminMFA) -> dict:
    return garmin_auth.submit_mfa(req.code)


@app.post("/api/garmin/sync", dependencies=[Depends(auth.require_auth)])
def garmin_sync_endpoint(req: SyncRequest) -> dict:
    if not garmin_auth.is_logged_in():
        raise HTTPException(status_code=400, detail="Garmin not logged in")
    return garmin_sync.sync_all(days=req.days)


@app.get("/api/garmin/activities")
def garmin_activities(limit: int = 50) -> dict:
    return {"items": garmin_sync.recent_activities(limit=limit)}


@app.get("/api/garmin/daily")
def garmin_daily(limit: int = 14) -> dict:
    return {"items": garmin_sync.recent_daily(limit=limit)}


# ---------------------------------------------------------------------------
# Withings
# ---------------------------------------------------------------------------


@app.get("/api/withings/status")
def withings_status() -> dict:
    return withings.status()


@app.get("/api/withings/authorize", dependencies=[Depends(auth.require_auth)])
def withings_authorize() -> RedirectResponse:
    try:
        url = withings.authorize_url()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse(url=url, status_code=302)


@app.get("/api/withings/callback")
def withings_callback(code: str, state: str) -> RedirectResponse:
    try:
        withings.handle_callback(code, state)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse(url="/?withings=connected", status_code=302)


@app.post("/api/withings/sync", dependencies=[Depends(auth.require_auth)])
def withings_sync_endpoint(days: int = 180) -> dict:
    try:
        return withings.sync_measurements(days=days)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/withings/disconnect", dependencies=[Depends(auth.require_auth)])
def withings_disconnect() -> dict:
    withings.disconnect()
    return {"ok": True}


@app.get("/api/withings/weights")
def withings_weights(limit: int = 90) -> dict:
    return {"items": withings.recent_weights(limit=limit)}


# ---------------------------------------------------------------------------
# Fitatu
# ---------------------------------------------------------------------------


@app.get("/api/fitatu/status")
def fitatu_status() -> dict:
    return fitatu.status()


@app.post("/api/fitatu/login", dependencies=[Depends(auth.require_auth)])
def fitatu_login_endpoint(req: FitatuLogin) -> dict:
    email = (req.email or os.environ.get("FITATU_EMAIL") or "").strip()
    password = (req.password or os.environ.get("FITATU_PASSWORD") or "").strip()
    if not email or not password:
        raise HTTPException(status_code=400, detail="Fitatu email + password required")
    try:
        return fitatu.login(email, password)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/fitatu/sync", dependencies=[Depends(auth.require_auth)])
def fitatu_sync_endpoint(req: FitatuSyncRequest) -> dict:
    days = req.days or 30
    try:
        return fitatu.sync_diary(days=days)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/fitatu/disconnect", dependencies=[Depends(auth.require_auth)])
def fitatu_disconnect() -> dict:
    fitatu.disconnect()
    return {"ok": True}


@app.get("/api/fitatu/diary")
def fitatu_diary_endpoint(limit: int = 30) -> dict:
    return {"items": fitatu.recent_diary(limit=limit)}


@app.get("/api/fitatu/today")
def fitatu_today() -> dict:
    return {"item": fitatu.today_nutrition()}


# ---------------------------------------------------------------------------
# Gym
# ---------------------------------------------------------------------------


@app.get("/api/gym/sessions")
def gym_sessions(limit: int = 60) -> dict:
    return {"items": gym.list_sessions(limit=limit)}


@app.get("/api/gym/sessions/{sid}")
def gym_session_get(sid: int) -> dict:
    s = gym.get_session(sid)
    if not s:
        raise HTTPException(status_code=404, detail="not found")
    return {"item": s}


@app.post("/api/gym/sessions", dependencies=[Depends(auth.require_auth)])
def gym_session_create(req: GymSessionCreate) -> dict:
    return {"item": gym.create_session(req.date, req.duration_min, req.rpe, req.notes)}


@app.patch("/api/gym/sessions/{sid}", dependencies=[Depends(auth.require_auth)])
def gym_session_update(sid: int, req: GymSessionUpdate) -> dict:
    try:
        return {"item": gym.update_session(sid, **req.model_dump(exclude_none=True))}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/api/gym/sessions/{sid}", dependencies=[Depends(auth.require_auth)])
def gym_session_delete(sid: int) -> dict:
    gym.delete_session(sid)
    return {"ok": True}


@app.put("/api/gym/sessions/{sid}/sets", dependencies=[Depends(auth.require_auth)])
def gym_session_replace_sets(sid: int, req: GymSetsReplace) -> dict:
    try:
        return {"item": gym.replace_sets(sid, [s.model_dump() for s in req.sets])}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/gym/exercises")
def gym_exercises() -> dict:
    return {"items": gym.known_exercises()}


# ---------------------------------------------------------------------------
# Coach
# ---------------------------------------------------------------------------


@app.post("/api/coach/gym-session", dependencies=[Depends(auth.require_auth)])
def coach_gym_session() -> dict:
    try:
        return coach.generate_gym_session()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/coach/plan", dependencies=[Depends(auth.require_auth)])
def coach_plan() -> dict:
    try:
        return coach.generate_plan()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/coach/eval", dependencies=[Depends(auth.require_auth)])
def coach_eval(req: EvalRequest) -> dict:
    if req.kind not in ("garmin", "gym"):
        raise HTTPException(status_code=400, detail="kind must be 'garmin' or 'gym'")
    try:
        return coach.evaluate_workout(req.kind, req.id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/coach/recovery", dependencies=[Depends(auth.require_auth)])
def coach_recovery() -> dict:
    try:
        return coach.assess_recovery()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/coach/nutrition", dependencies=[Depends(auth.require_auth)])
def coach_nutrition() -> dict:
    try:
        return coach.analyze_nutrition()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/coach/history")
def coach_history(kind: Optional[str] = None, limit: int = 20) -> dict:
    return {"items": coach.history(kind=kind, limit=limit)}


@app.get("/api/coach/provider")
def coach_provider() -> dict:
    return coach.provider_info()
