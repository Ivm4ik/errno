"""Replay generator envelopes through the API. The backend never imports the generator."""

import os
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from generator.engine import iter_batches, load_scenario
from main import app


def _login(client: TestClient, login: str) -> str:
    response = client.post(
        "/auth/login",
        json={"login": login, "password": os.environ[f"SEED_PASSWORD_{login.upper()}"]},
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _play(client: TestClient, name: str, base: float, seq: int) -> int:
    scenario = load_scenario(name)
    for envelope in iter_batches(scenario, seed=1, time_scale=60, base_ts=base):
        envelope = dict(envelope)
        envelope["seq"] = seq
        seq += 1
        response = client.post("/ingest", json=envelope)
        assert response.status_code == 200, response.text
    time.sleep(0.6)
    return seq


def _get(client: TestClient, path: str, token: str, **params):
    last = ""
    for _ in range(30):
        try:
            response = client.get(path, params=params, headers={"Authorization": f"Bearer {token}"})
        except Exception as exc:
            last = str(exc)
            time.sleep(0.3)
            continue
        if response.status_code == 200:
            return response
        last = response.text
        time.sleep(0.3)
    raise AssertionError(last)


def _status(client: TestClient, token: str) -> int:
    return int(_get(client, "/status", token, astronaut_id="A1").json()["status"])


def test_key_scenarios_against_the_api():
    with TestClient(app) as client:
        token = _login(client, "astronaut")
        officer = _login(client, "officer")
        base = time.time() + 800
        seq = _play(client, "nominal", base, 1)
        assert _status(client, token) == 0
        seq = _play(client, "exercise_false_alarm", base + 120, seq)
        assert _status(client, token) == 0
        seq = _play(client, "mild_warning", base + 250, seq)
        assert _status(client, token) == 1
        seq = _play(client, "sensor_fault", base + 300, seq)
        assert _status(client, token) == 0
        alerts = _get(client, "/alerts", token, astronaut_id="A1").json()
        assert any(item["category"] == "equipment" for item in alerts)
        _play(client, "cardiac_stress", base + 400, seq)
        assert _status(client, token) == 2
        blocked = client.get("/emergency/A1", headers={"Authorization": f"Bearer {token}"})
        assert blocked.status_code == 403
        opened = _get(client, "/emergency/A1", officer)
        assert opened.json()["rows"]
