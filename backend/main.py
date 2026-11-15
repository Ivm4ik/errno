import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from access import load_limits, seed_accounts
from api import alerts, audit, auth, forms, ingest, live, mission, readings, sensors, status
from api.ingest import Gate
from api.live import hub
from clock import now
from config_loader import env_bool, env_float, load_yaml
from db import connect, run_writer, seed_devices
from earth_link import SimClock, delay_seconds
from audit import load_key
from scoring.clinical import Clinical
from scoring.engine import Engine
from sensors.eeg import BrainflowEEGDriver
from sensors.esp32 import Esp32Driver
from sensors.polar import PolarDriver
from sensors.push import PushDriver
from sensors.registry import resolve
from timesync import TimeSync

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("errno")


async def _hydrate(cx, engine: Engine, gate: Gate) -> None:
    for row in await (await cx.execute("SELECT * FROM baselines")).fetchall():
        st = engine.state(row["astronaut_id"], row["sensor_id"])
        st.mean, st.var, st.n, st.updated = row["mean"], row["var"], row["n"], row["updated_ts"]
    for row in await (await cx.execute("SELECT * FROM alerts ORDER BY id")).fetchall():
        engine.alerts.append(
            {
                "id": row["id"],
                "ts": row["ts"],
                "astronaut_id": row["astronaut_id"],
                "sensor_id": row["sensor_id"],
                "category": row["category"],
                "level": row["level"],
                "message": row["message"],
                "explanation": row["explanation"],
                "acknowledged": row["acknowledged"],
                "open": not row["acknowledged"],
            }
        )
    if engine.alerts:
        engine._seq = max(item["id"] for item in engine.alerts)
    for row in await (await cx.execute("SELECT astronaut_id, help_needed FROM status ORDER BY ts")).fetchall():
        engine.help[row["astronaut_id"]] = bool(row["help_needed"])
    for row in await (await cx.execute("SELECT device_id, seq FROM ingest_seen")).fetchall():
        gate.seen.add((row["device_id"], row["seq"]))
    for row in await (await cx.execute("SELECT device_id, last_seq FROM device_state")).fetchall():
        if row["last_seq"] is not None:
            gate.last_seq[row["device_id"]] = row["last_seq"]


def _mqtt_task(url: str, queue, metrics_by_id: dict):
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        log.warning("paho-mqtt is not installed; MQTT bridge is off")
        return None

    def on_message(_client, _userdata, msg):
        parts = msg.topic.split("/")
        if len(parts) != 3 or parts[0] != "health":
            return
        _, astronaut, sensor = parts
        metric = metrics_by_id.get(sensor)
        if metric is None:
            return
        try:
            value = float(msg.payload)
        except ValueError:
            return
        from models import Reading

        queue.put_nowait(
            Reading(
                sensor_id=sensor,
                astronaut_id=astronaut,
                value=value,
                unit=metric["unit"],
                ts=now(),
                source="esp32",
            )
        )

    client = mqtt.Client()
    client.on_message = on_message
    client.connect(url.split("://")[-1].split(":")[0], int(url.rsplit(":", 1)[-1]) if ":" in url.split("://")[-1] else 1883)
    client.subscribe("health/+/+")
    client.loop_start()
    return client


@asynccontextmanager
async def lifespan(app: FastAPI):
    if env_bool("DEV_NO_AUTH", False):
        log.warning("DEV_NO_AUTH is on. Ingest accepts requests with no device token.")
    cx = await connect()
    await seed_devices(cx, os.environ.get("DEVICE_TOKENS", ""))
    metrics = load_yaml("metrics.yaml")["metrics"]
    for metric in metrics:
        metric["_source"] = resolve(metric)
    scoring = load_yaml("scoring.yaml")
    engine = Engine({item["id"]: item for item in metrics}, scoring, load_yaml("actions.yaml"))
    gate = Gate()
    await _hydrate(cx, engine, gate)
    queue: asyncio.Queue = asyncio.Queue()
    crew = load_yaml("crew.yaml")["astronauts"]
    await seed_accounts(cx, [item["id"] for item in crew])
    app.state.limits = await load_limits(cx)
    app.state.cx = cx
    app.state.queue = queue
    app.state.engine = engine
    app.state.gate = gate
    app.state.sync = TimeSync()
    app.state.metrics = metrics
    app.state.metrics_by_id = {item["id"]: item for item in metrics}
    app.state.crew = crew
    app.state.astronaut_ids = [item["id"] for item in crew]
    app.state.key = load_key()
    app.state.no_auth = env_bool("DEV_NO_AUTH", False)
    app.state.demo = env_bool("DEMO_MODE", True)
    app.state.clock = SimClock()
    app.state.delay = delay_seconds()
    clinical = Clinical(metrics, app.state.astronaut_ids, load_yaml("penalty.yaml"), load_yaml("status.yaml"), app.state.delay)
    await clinical.hydrate(cx)
    app.state.clinical = clinical
    live.hub.clock = app.state.clock
    live.hub.delay = app.state.delay
    writer = asyncio.create_task(
        run_writer(
            queue,
            cx,
            engine,
            app.state.key,
            live.hub.publish,
            env_float("FLUSH_SECONDS", 0.25),
            gate.push_seen,
            clinical,
            app.state.clock,
        )
    )
    tasks = []
    if env_bool("RUN_DRIVERS", True):
        if any(item["_source"] == "polar" for item in metrics):
            tasks.append(asyncio.create_task(PolarDriver(metrics[0], "A1", queue).run()))
        if any(item["_source"] == "brainflow" for item in metrics):
            tasks.append(asyncio.create_task(BrainflowEEGDriver(metrics[0], "A1", queue).run()))
        esp = [item for item in metrics if item["_source"] == "esp32"]
        port = os.environ.get("ESP32_PORT", "")
        if esp and port:
            tasks.append(asyncio.create_task(Esp32Driver(esp[0], os.environ.get("ESP32_ASTRONAUT", "A1"), queue, port).run()))
        else:
            for metric in esp:
                for astronaut in app.state.astronaut_ids:
                    tasks.append(asyncio.create_task(PushDriver(metric, astronaut, queue, gate.push_seen).run()))
    mqtt = _mqtt_task(os.environ.get("MQTT_URL", ""), queue, app.state.metrics_by_id) if os.environ.get("MQTT_URL") else None
    try:
        yield
    finally:
        writer.cancel()
        for task in tasks:
            task.cancel()
        for task in [writer, *tasks]:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if mqtt is not None:
            mqtt.loop_stop()
        await cx.close()


app = FastAPI(title="ERRNO", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        *[o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()],
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
for piece in (auth.router, ingest.router, forms.router, readings.router, status.router, alerts.router, audit.router, live.router, mission.router, sensors.router):
    app.include_router(piece)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
