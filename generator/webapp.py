"""Separate web UI for the sensor generator. Does not import backend."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from generator.client import post_envelope
from generator.engine import iter_batches, list_scenarios, load_scenario
from generator.live import CLIP, GROUP, GROUP_LABEL, TOLERANCE, LiveRig, wall_period, zone_bounds
from generator.signals import BASE, DELTA, EVERY, METRICS, SCHEDULE, SENSOR, UNIT

STATIC = Path(__file__).resolve().parent / "static"
PRESETS = Path(__file__).resolve().parent / "presets"
DEFAULT_BACKEND = os.environ.get("ERRNO_BACKEND", os.environ.get("VITA_BACKEND", "http://127.0.0.1:8000"))
DEFAULT_TOKEN = os.environ.get("DEVICE_TOKEN", os.environ.get("GENERATOR_DEVICE_TOKEN", ""))

CREW = {
    "A1": {"id": "A1", "name": "Олена Кравець", "role": "Командир", "baseline": "Astro1"},
    "A2": {"id": "A2", "name": "Тарас Бондар", "role": "Космонавт", "baseline": "Astro2"},
}
LABELS = {
    "ACT": "Активність",
    "HR": "Пульс",
    "ECG": "Кардіограма",
    "RR": "Дихання",
    "SPO2": "Кисень",
    "BP": "Тиск систол.",
    "BPD": "Тиск діаст.",
    "TEMP": "Температура",
    "EEG": "ЕЕГ мозку",
    "GLU": "Глюкоза",
    "K": "Калій",
    "NA": "Натрій",
    "CA": "Кальцій",
    "LAC": "Лактат",
    "ICP": "ВЧТ",
    "SLP": "Сон (години)",
    "SLQ": "Якість сну",
    "RAD": "Радіація (доза/доба)",
    "RADC": "Накопичена доза",
    "CO2": "CO₂ середовища",
    "WELL": "Самопочуття",
    "WBC": "Лейкоцити (імунітет)",
    "HCT": "Гематокрит",
    "CREA": "Креатинін",
    "US": "УЗД м'язів/кісток",
}
STEP = {
    "ECG": 0.01,
    "TEMP": 0.05,
    "K": 0.01,
    "NA": 0.1,
    "CA": 0.05,
    "LAC": 0.05,
    "ICP": 0.1,
    "SLP": 0.1,
    "SLQ": 0.5,
    "RAD": 0.01,
    "RADC": 0.5,
    "CO2": 0.01,
    "EEG": 0.5,
    "GLU": 0.5,
    "ACT": 5,
    "WELL": 0.5,
    "WBC": 0.1,
    "HCT": 0.5,
    "BPD": 1,
    "CREA": 1,
    "US": 0.5,
}

app = FastAPI(title="ERRNO Generator", version="1.0.0")
_jobs: dict[str, dict[str, Any]] = {}
_live: dict[str, dict[str, Any]] = {}
# Monotonic-ish across restarts so /ingest does not treat fresh packets as duplicates.
_seq = int(time.time() * 1000)
_lock = asyncio.Lock()
PRESETS.mkdir(exist_ok=True)


class RunIn(BaseModel):
    scenario: str = "nominal"
    astronaut: str | None = None
    backend: str = DEFAULT_BACKEND
    device_token: str = DEFAULT_TOKEN
    time_scale: float = 60
    seed: int = 1
    duration: float | None = None


class LiveStartIn(BaseModel):
    backend: str = DEFAULT_BACKEND
    device_token: str = DEFAULT_TOKEN
    astronaut_id: str = "A1"
    activity_mode: str = "rest"
    time_scale: float = 60
    auto: bool = False  # manual center ± jitter by default
    faults: bool = False
    fault_rate: float = 0.02
    stress: float = 0.0
    enabled: list[str] = Field(default_factory=lambda: list(METRICS))
    bias: dict[str, float] = Field(default_factory=dict)
    jitter: dict[str, float] = Field(default_factory=dict)
    jitter_lo: dict[str, float] = Field(default_factory=dict)
    jitter_hi: dict[str, float] = Field(default_factory=dict)
    intensity: dict[str, float] = Field(default_factory=dict)
    manual: dict[str, float] = Field(default_factory=dict)
    seed: int = 1


class LivePatchIn(BaseModel):
    activity_mode: str | None = None
    time_scale: float | None = None
    auto: bool | None = None
    faults: bool | None = None
    fault_rate: float | None = None
    stress: float | None = None
    enabled: list[str] | None = None
    bias: dict[str, float] | None = None
    jitter: dict[str, float] | None = None
    jitter_lo: dict[str, float] | None = None
    jitter_hi: dict[str, float] | None = None
    intensity: dict[str, float] | None = None
    manual: dict[str, float] | None = None


class PresetIn(BaseModel):
    name: str
    astronaut_id: str
    activity_mode: str = "rest"
    time_scale: float = 60
    auto: bool = True
    faults: bool = True
    fault_rate: float = 0.02
    stress: float = 0.0
    enabled: list[str] = Field(default_factory=list)
    bias: dict[str, float] = Field(default_factory=dict)
    jitter: dict[str, float] = Field(default_factory=dict)
    jitter_lo: dict[str, float] = Field(default_factory=dict)
    jitter_hi: dict[str, float] = Field(default_factory=dict)
    intensity: dict[str, float] = Field(default_factory=dict)
    manual: dict[str, float] = Field(default_factory=dict)


def _metric_meta(code: str) -> dict:
    low, high = CLIP[code]
    group = GROUP.get(code, "rare")
    return {
        "code": code,
        "sensor_id": SENSOR[code],
        "unit": UNIT[code],
        "label": LABELS[code],
        "schedule": SCHEDULE[code],
        "group": group,
        "group_label": GROUP_LABEL[group],
        "baseline_a1": BASE["A1"][code],
        "baseline_a2": BASE["A2"][code],
        "delta": DELTA[code],
        "tolerance": TOLERANCE[code],
        "every_sim_s": EVERY[code],
        "every_wall_s": wall_period(EVERY[code], 60),
        "every_s": wall_period(EVERY[code], 60),
        "min": low,
        "max": high,
        "step": STEP.get(code, 1),
        "waveform": code == "ECG",
        "zones_a1": zone_bounds(code, "A1"),
        "zones_a2": zone_bounds(code, "A2"),
    }


def _job_view(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job["id"],
        "scenario": job["scenario"],
        "astronaut": job.get("astronaut"),
        "running": job["running"],
        "sent": job["sent"],
        "errors": job["errors"],
        "last_error": job.get("last_error"),
        "started_at": job["started_at"],
        "finished_at": job.get("finished_at"),
        "time_scale": job["time_scale"],
        "backend": job["backend"],
    }


def _ingest_mode(mode: str) -> str:
    return mode if mode in {"rest", "exercise", "eva"} else "rest"


async def _next_seq() -> int:
    global _seq
    async with _lock:
        _seq += 1
        return _seq


async def _run_job(job_id: str) -> None:
    job = _jobs[job_id]
    try:
        scenario = load_scenario(job["scenario"])
        base = time.time()
        scale = float(job["time_scale"])
        sleep_for = max(scale, 1.0) / scale if scale else 1.0
        for envelope in iter_batches(scenario, job["seed"], scale, base, job.get("duration"), job.get("astronaut")):
            if job.get("stop"):
                break
            try:
                await asyncio.to_thread(post_envelope, job["backend"], job["device_token"], envelope)
                job["sent"] += 1
            except Exception as exc:  # noqa: BLE001
                job["errors"] += 1
                job["last_error"] = str(exc)
            await asyncio.sleep(sleep_for)
    except Exception as exc:  # noqa: BLE001
        job["errors"] += 1
        job["last_error"] = str(exc)
    finally:
        job["running"] = False
        job["finished_at"] = time.time()


async def _push_readings(session: dict[str, Any], readings: list[dict]) -> dict:
    if not readings:
        return {"ok": True, "accepted": 0, "n": 0}
    rig: LiveRig = session["rig"]
    seq = await _next_seq()
    envelope = {
        "device_id": "sim-gw-1",
        "astronaut_id": session["astronaut_id"],
        "seq": seq,
        "buffered": False,
        "time_scale": max(float(rig.time_scale), 1.0),
        "activity_mode": _ingest_mode(rig.activity_mode),
        "ts_device": readings[-1]["ts_device"],
        "readings": readings,
    }
    try:
        result = await asyncio.to_thread(post_envelope, session["backend"], session["device_token"], envelope)
        if result.get("duplicate"):
            session["errors"] = session.get("errors", 0) + 1
            session["last_error"] = f"duplicate seq {seq}"
            return {"ok": False, "error": session["last_error"], "seq": seq}
        if not result.get("accepted"):
            session["errors"] = session.get("errors", 0) + 1
            session["last_error"] = f"accepted=0 dropped={result.get('dropped')}"
            return {"ok": False, "error": session["last_error"], "seq": seq}
        session["sent"] = session.get("sent", 0) + 1
        session["last"] = {
            "seq": seq,
            "n": len(readings),
            "ts": readings[-1]["ts_device"],
            "wall": time.time(),
            "accepted": result.get("accepted"),
        }
        session["last_error"] = None
        return {"ok": True, "accepted": result.get("accepted"), "n": len(readings), "seq": seq}
    except Exception as exc:  # noqa: BLE001
        session["errors"] = session.get("errors", 0) + 1
        session["last_error"] = str(exc)
        return {"ok": False, "error": str(exc), "seq": seq}


async def _run_live(astronaut_id: str) -> None:
    session = _live[astronaut_id]
    rig: LiveRig = session["rig"]
    while session.get("running"):
        readings = await asyncio.to_thread(rig.tick)
        if readings:
            await _push_readings(session, readings)
        session["snapshot"] = rig.snapshot()
        # Snappy enough for cardiogram chunks (~4 Hz) + scalar vitals.
        await asyncio.sleep(0.1)
    session["running"] = False


@app.get("/api/meta")
def meta() -> dict:
    return {
        "backend": DEFAULT_BACKEND,
        "device_token_set": bool(DEFAULT_TOKEN),
        "device_token_default": DEFAULT_TOKEN,
        "scenarios": list_scenarios(),
        "crew": list(CREW.values()),
        "default_time_scale": 1,
        "groups": [{"id": key, "label": label} for key, label in GROUP_LABEL.items()],
        "scenes": ["nominal", "yellow", "red_high", "red_low", "random"],
        "metrics": [_metric_meta(code) for code in METRICS],
        "schedule_note": {
            "continuous": "Постійний моніторинг / безперервно",
            "chem": "Підшкірні хім датчики · кожні пів години",
            "daily": "Щовечора / щоранку / тиск і звірка дози раз на добу",
            "rare": "Аналізи й імунітет 1–2 тижні · УЗД 2–4 тижні",
        },
    }


@app.get("/api/live")
def live_status() -> dict:
    out = {}
    for key, session in _live.items():
        rig: LiveRig = session["rig"]
        out[key] = {
            "astronaut_id": key,
            "running": session.get("running", False),
            "sent": session.get("sent", 0),
            "errors": session.get("errors", 0),
            "last_error": session.get("last_error"),
            "last": session.get("last"),
            "snapshot": session.get("snapshot") or rig.snapshot(),
        }
    return out


@app.get("/api/live/{astronaut_id}")
def live_one(astronaut_id: str) -> dict:
    session = _live.get(astronaut_id)
    if session is None:
        rig = LiveRig(astronaut_id=astronaut_id)
        return {"astronaut_id": astronaut_id, "running": False, "sent": 0, "errors": 0, "snapshot": rig.snapshot()}
    return {
        "astronaut_id": astronaut_id,
        "running": session.get("running", False),
        "sent": session.get("sent", 0),
        "errors": session.get("errors", 0),
        "last_error": session.get("last_error"),
        "last": session.get("last"),
        "snapshot": session.get("snapshot") or session["rig"].snapshot(),
    }


@app.post("/api/live/start")
async def live_start(body: LiveStartIn) -> dict:
    if not body.device_token.strip():
        raise HTTPException(422, "Потрібен device token")
    if body.astronaut_id not in CREW:
        raise HTTPException(404, "Немає такого космонавта")
    session = _live.get(body.astronaut_id)
    if session and session.get("running"):
        rig: LiveRig = session["rig"]
        _apply_patch(
            rig,
            LivePatchIn(
                activity_mode=body.activity_mode,
                time_scale=body.time_scale,
                auto=body.auto,
                faults=body.faults,
                fault_rate=body.fault_rate,
                stress=body.stress,
                enabled=body.enabled,
                bias=body.bias,
                jitter=body.jitter,
                jitter_lo=body.jitter_lo,
                jitter_hi=body.jitter_hi,
                intensity=body.intensity,
                manual=body.manual,
            ),
        )
        session["backend"] = body.backend.rstrip("/")
        session["device_token"] = body.device_token.strip()
        return {"ok": True, "updated": True, "snapshot": rig.snapshot()}

    rig = LiveRig(
        astronaut_id=body.astronaut_id,
        seed=body.seed,
        activity_mode=body.activity_mode,
        time_scale=max(float(body.time_scale), 1.0),
        auto=body.auto,
        faults=body.faults,
        fault_rate=body.fault_rate,
        stress=body.stress,
        enabled=set(code.upper() for code in body.enabled) or set(METRICS),
    )
    for key, value in body.bias.items():
        rig.bias[key.upper()] = float(value)
    _apply_dev(rig, jitter=body.jitter, jitter_lo=body.jitter_lo, jitter_hi=body.jitter_hi, intensity=body.intensity)
    for key, value in body.manual.items():
        rig.manual[key.upper()] = float(value)
        rig.channels[key.upper()].value = float(value)

    _live[body.astronaut_id] = {
        "astronaut_id": body.astronaut_id,
        "running": True,
        "backend": body.backend.rstrip("/"),
        "device_token": body.device_token.strip(),
        "rig": rig,
        "sent": 0,
        "errors": 0,
        "last_error": None,
        "snapshot": rig.snapshot(),
    }
    asyncio.create_task(_run_live(body.astronaut_id))
    return {"ok": True, "started": True, "snapshot": rig.snapshot()}


def _norm_map(raw: dict[str, float] | None) -> dict[str, float]:
    return {k.upper(): float(v) for k, v in (raw or {}).items()}


def _apply_dev(
    rig: LiveRig,
    *,
    jitter: dict[str, float] | None = None,
    jitter_lo: dict[str, float] | None = None,
    jitter_hi: dict[str, float] | None = None,
    intensity: dict[str, float] | None = None,
) -> None:
    """Apply −/+ band + intensity. Legacy `jitter` sets both sides when lo/hi omitted."""
    j = _norm_map(jitter)
    lo_map = _norm_map(jitter_lo)
    hi_map = _norm_map(jitter_hi)
    inten_map = _norm_map(intensity)
    codes = set(j) | set(lo_map) | set(hi_map) | set(inten_map)
    for code in codes:
        lo = lo_map.get(code)
        hi = hi_map.get(code)
        if lo is None and hi is None and code in j:
            lo = hi = abs(j[code])
        elif lo is None and code in j and code not in hi_map:
            lo = abs(j[code])
        elif hi is None and code in j and code not in lo_map:
            hi = abs(j[code])
        rig.set_dev(
            code,
            lo=None if lo is None else abs(lo),
            hi=None if hi is None else abs(hi),
            intensity=inten_map.get(code),
        )


def _apply_patch(rig: LiveRig, body: LivePatchIn) -> None:
    if body.activity_mode is not None:
        rig.activity_mode = body.activity_mode
    if body.time_scale is not None:
        rig.time_scale = max(float(body.time_scale), 1.0)
    if body.auto is not None:
        rig.auto = body.auto
    if body.faults is not None:
        rig.faults = body.faults
    if body.fault_rate is not None:
        rig.fault_rate = float(body.fault_rate)
    if body.stress is not None:
        rig.stress = float(body.stress)
    if body.enabled is not None:
        rig.enabled = {code.upper() for code in body.enabled}
    if body.bias is not None:
        for key, value in body.bias.items():
            rig.bias[key.upper()] = float(value)
    _apply_dev(rig, jitter=body.jitter, jitter_lo=body.jitter_lo, jitter_hi=body.jitter_hi, intensity=body.intensity)
    if body.manual is not None:
        for key, value in body.manual.items():
            code = key.upper()
            rig.manual[code] = float(value)
            if code in rig.channels:
                rig.channels[code].value = float(value)


@app.post("/api/live/{astronaut_id}/patch")
async def live_patch(astronaut_id: str, body: LivePatchIn) -> dict:
    session = _live.get(astronaut_id)
    if session is None:
        raise HTTPException(404, "Спочатку запусти живий режим")
    rig: LiveRig = session["rig"]
    _apply_patch(rig, body)
    session["snapshot"] = rig.snapshot()
    return {"ok": True, "snapshot": session["snapshot"]}


@app.post("/api/live/{astronaut_id}/critical")
async def live_critical(astronaut_id: str, direction: str = "high", push: bool = False) -> dict:
    scene = "red_low" if direction == "low" else "red_high"
    return await live_scene(astronaut_id, SceneIn(scene=scene, push=push))


class BurstIn(BaseModel):
    randomize: bool = False
    backend: str = DEFAULT_BACKEND
    device_token: str = DEFAULT_TOKEN
    activity_mode: str = "rest"
    time_scale: float = 60
    auto: bool | None = None
    enabled: list[str] | None = None
    bias: dict[str, float] | None = None
    jitter: dict[str, float] | None = None
    jitter_lo: dict[str, float] | None = None
    jitter_hi: dict[str, float] | None = None
    intensity: dict[str, float] | None = None
    manual: dict[str, float] | None = None
    codes: list[str] | None = None  # if set — push only these (still immediate)


class SetIn(BaseModel):
    code: str
    value: float
    push: bool = True
    backend: str = DEFAULT_BACKEND
    device_token: str = DEFAULT_TOKEN
    activity_mode: str = "rest"
    time_scale: float = 60


class SceneIn(BaseModel):
    scene: str = "nominal"
    push: bool = True
    backend: str = DEFAULT_BACKEND
    device_token: str = DEFAULT_TOKEN
    activity_mode: str = "rest"
    time_scale: float = 60
    enabled: list[str] | None = None


def _ensure_live_session(
    astronaut_id: str,
    *,
    backend: str = DEFAULT_BACKEND,
    device_token: str = DEFAULT_TOKEN,
    activity_mode: str = "rest",
    time_scale: float = 60,
    auto: bool | None = None,
    enabled: list[str] | None = None,
    bias: dict[str, float] | None = None,
    jitter: dict[str, float] | None = None,
    jitter_lo: dict[str, float] | None = None,
    jitter_hi: dict[str, float] | None = None,
    intensity: dict[str, float] | None = None,
    manual: dict[str, float] | None = None,
) -> dict[str, Any]:
    if astronaut_id not in CREW:
        raise HTTPException(404, "Немає такого космонавта")
    token = device_token.strip() or (_live.get(astronaut_id) or {}).get("device_token", "")
    if not token:
        raise HTTPException(422, "Потрібен device token")

    session = _live.get(astronaut_id)
    if session is None:
        rig = LiveRig(
            astronaut_id=astronaut_id,
            activity_mode=activity_mode,
            time_scale=max(float(time_scale), 1.0),
            enabled=set(code.upper() for code in (enabled or METRICS)),
            auto=False if auto is None else auto,
            faults=False,
            bias={k.upper(): float(v) for k, v in (bias or {}).items()},
            manual={k.upper(): float(v) for k, v in (manual or {}).items()},
        )
        _apply_dev(rig, jitter=jitter, jitter_lo=jitter_lo, jitter_hi=jitter_hi, intensity=intensity)
        for code, value in list(rig.manual.items()):
            if code in rig.channels:
                rig.set_value(code, float(value), hold=True)
        session = {
            "astronaut_id": astronaut_id,
            "running": False,
            "backend": backend.rstrip("/"),
            "device_token": token,
            "rig": rig,
            "sent": 0,
            "errors": 0,
            "last_error": None,
            "snapshot": rig.snapshot(),
        }
        _live[astronaut_id] = session
        return session

    if device_token.strip():
        session["device_token"] = device_token.strip()
    if backend:
        session["backend"] = backend.rstrip("/")
    if enabled is not None:
        session["rig"].enabled = {code.upper() for code in enabled}
    session["rig"].time_scale = max(float(time_scale or session["rig"].time_scale), 1.0)
    session["rig"].activity_mode = activity_mode or session["rig"].activity_mode
    if auto is not None:
        session["rig"].auto = auto
    if bias is not None:
        for key, value in bias.items():
            session["rig"].bias[key.upper()] = float(value)
    _apply_dev(session["rig"], jitter=jitter, jitter_lo=jitter_lo, jitter_hi=jitter_hi, intensity=intensity)
    if manual is not None:
        for key, value in manual.items():
            session["rig"].set_value(key.upper(), float(value), hold=True)
    return session


@app.post("/api/live/{astronaut_id}/burst")
async def live_burst(astronaut_id: str, body: BurstIn | None = None) -> dict:
    """Send sensors right now (wall-clock ts). Optional codes= for a single/manual push."""
    body = body or BurstIn()
    session = _ensure_live_session(
        astronaut_id,
        backend=body.backend,
        device_token=body.device_token,
        activity_mode=body.activity_mode,
        time_scale=body.time_scale,
        auto=body.auto,
        enabled=body.enabled,
        bias=body.bias,
        jitter=body.jitter,
        jitter_lo=body.jitter_lo,
        jitter_hi=body.jitter_hi,
        intensity=body.intensity,
        manual=body.manual,
    )
    if body.auto is None and (body.codes or not body.randomize):
        session["rig"].auto = False
    only = {code.upper() for code in body.codes} if body.codes else None
    readings = await asyncio.to_thread(session["rig"].burst, randomize=body.randomize, codes=only)
    result = await _push_readings(session, readings)
    session["snapshot"] = session["rig"].snapshot()
    return {
        "ok": result.get("ok", False),
        "burst": True,
        "randomize": body.randomize,
        "codes": sorted(only) if only else None,
        **result,
        "snapshot": session["snapshot"],
    }


@app.post("/api/live/{astronaut_id}/push")
async def live_push(astronaut_id: str, body: BurstIn | None = None) -> dict:
    """Immediate push (all enabled or `codes`). Always ignores schedule; wall-clock ts."""
    body = body or BurstIn()
    session = _ensure_live_session(
        astronaut_id,
        backend=body.backend,
        device_token=body.device_token,
        activity_mode=body.activity_mode,
        time_scale=body.time_scale,
        auto=body.auto,
        enabled=body.enabled,
        bias=body.bias,
        jitter=body.jitter,
        jitter_lo=body.jitter_lo,
        jitter_hi=body.jitter_hi,
        intensity=body.intensity,
        manual=body.manual,
    )
    if body.auto is None:
        session["rig"].auto = False
    readings = await asyncio.to_thread(session["rig"].push_now, body.codes)
    result = await _push_readings(session, readings)
    session["snapshot"] = session["rig"].snapshot()
    return {"ok": result.get("ok", False), "push": True, **result, "snapshot": session["snapshot"]}


@app.post("/api/live/{astronaut_id}/set")
async def live_set(astronaut_id: str, body: SetIn) -> dict:
    """Set one sensor value; optionally push immediately to the panel."""
    session = _ensure_live_session(
        astronaut_id,
        backend=body.backend,
        device_token=body.device_token,
        activity_mode=body.activity_mode,
        time_scale=body.time_scale,
        auto=False,
    )
    code = body.code.upper()
    if code not in METRICS:
        raise HTTPException(404, f"Немає датчика {code}")
    value = await asyncio.to_thread(session["rig"].set_value, code, body.value, hold=True)
    result: dict[str, Any] = {"ok": True, "code": code, "value": value}
    if body.push:
        if code not in session["rig"].enabled:
            session["rig"].enabled.add(code)
        readings = await asyncio.to_thread(session["rig"].push_now, [code])
        result.update(await _push_readings(session, readings))
    session["snapshot"] = session["rig"].snapshot()
    result["snapshot"] = session["snapshot"]
    return result


@app.post("/api/live/{astronaut_id}/scene")
async def live_scene(astronaut_id: str, body: SceneIn) -> dict:
    """Apply a demo scene (nominal / yellow / red_high / red_low / random)."""
    session = _ensure_live_session(
        astronaut_id,
        backend=body.backend,
        device_token=body.device_token,
        activity_mode=body.activity_mode,
        time_scale=body.time_scale,
        enabled=body.enabled,
    )
    await asyncio.to_thread(session["rig"].apply_scene, body.scene)
    result: dict[str, Any] = {"ok": True, "scene": body.scene}
    if body.push:
        readings = await asyncio.to_thread(session["rig"].push_now)
        result.update(await _push_readings(session, readings))
    session["snapshot"] = session["rig"].snapshot()
    result["snapshot"] = session["snapshot"]
    return result

@app.post("/api/live/{astronaut_id}/nominal")
async def live_nominal(astronaut_id: str, push: bool = False) -> dict:
    return await live_scene(astronaut_id, SceneIn(scene="nominal", push=push))


@app.post("/api/live/{astronaut_id}/stop")
async def live_stop(astronaut_id: str) -> dict:
    session = _live.get(astronaut_id)
    if session is None:
        return {"ok": True, "stopped": False}
    session["running"] = False
    return {"ok": True, "stopped": True}


@app.get("/api/jobs")
def jobs() -> list[dict]:
    return [_job_view(job) for job in sorted(_jobs.values(), key=lambda item: item["started_at"], reverse=True)]


@app.post("/api/run")
async def run(body: RunIn) -> dict:
    if not body.device_token.strip():
        raise HTTPException(422, "Потрібен device token")
    if body.scenario not in list_scenarios():
        raise HTTPException(404, f"Немає сценарію {body.scenario}")
    job_id = f"job-{await _next_seq()}"
    job = {
        "id": job_id,
        "scenario": body.scenario,
        "astronaut": body.astronaut,
        "backend": body.backend.rstrip("/"),
        "device_token": body.device_token.strip(),
        "time_scale": body.time_scale,
        "seed": body.seed,
        "duration": body.duration,
        "running": True,
        "stop": False,
        "sent": 0,
        "errors": 0,
        "started_at": time.time(),
        "finished_at": None,
        "last_error": None,
    }
    _jobs[job_id] = job
    asyncio.create_task(_run_job(job_id))
    return _job_view(job)


@app.post("/api/jobs/{job_id}/stop")
async def stop(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Немає такого job")
    job["stop"] = True
    return _job_view(job)


@app.get("/api/presets")
def presets() -> list[dict]:
    out = []
    for path in sorted(PRESETS.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out.append({"id": path.stem, "file": path.name, **data})
        except Exception:  # noqa: BLE001
            continue
    return out


@app.post("/api/presets")
def save_preset(body: PresetIn) -> dict:
    name = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in body.name.strip())[:48] or "preset"
    payload = body.model_dump()
    payload["name"] = body.name.strip() or name
    payload["saved_at"] = time.time()
    path = PRESETS / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "id": name, **payload}


@app.delete("/api/presets/{preset_id}")
def delete_preset(preset_id: str) -> dict:
    path = PRESETS / f"{preset_id}.json"
    if not path.exists():
        raise HTTPException(404, "Немає такого пресета")
    path.unlink()
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


if STATIC.exists():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")


def main() -> None:
    import uvicorn

    host = os.environ.get("GENERATOR_HOST", "127.0.0.1")
    port = int(os.environ.get("GENERATOR_PORT", "8100"))
    uvicorn.run("generator.webapp:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
