"""POST envelopes. websockets is available for a live stream; the demo uses HTTP."""

import json

import httpx
import websockets


def ws_supported() -> bool:
    return websockets is not None


def post_envelope(url: str, token: str, envelope: dict) -> dict:
    response = httpx.post(
        url.rstrip("/") + "/ingest",
        headers={"X-Device-Token": token, "content-type": "application/json"},
        content=json.dumps(envelope),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()
