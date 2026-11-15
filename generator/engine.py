"""Turn a scenario file into ingest envelopes. No backend imports."""

from pathlib import Path

import numpy as np
import yaml

from generator.scheduler import due as due_times, effects_at, mode_at
from generator.signals import ACTIVITY, EVERY, METRICS, SENSOR, UNIT, nominal

ROOT = Path(__file__).resolve().parent
SCENARIOS = ROOT / "scenarios"


def _wire_mode(mode: str) -> str:
    """Ingest accepts rest, exercise, eva. Sleep and work stay in the signal, not on the wire."""
    key = mode.lower()
    if key in {"exercise", "eva"}:
        return key
    return "rest"


def list_scenarios() -> list[str]:
    return sorted(path.stem for path in SCENARIOS.glob("*.yaml"))


def load_scenario(name: str | None = None, path: str | None = None) -> dict:
    if path:
        file = Path(path)
    elif name == "multi_astronaut" or name is None:
        file = SCENARIOS / f"{name or 'nominal'}.yaml"
    else:
        file = SCENARIOS / f"{name}.yaml"
    data = yaml.safe_load(file.read_text(encoding="utf-8"))
    data["_file"] = str(file)
    return data


def _crews(scenario: dict, astronaut: str | None) -> list[dict]:
    if scenario.get("astronauts"):
        return scenario["astronauts"]
    return [
        {
            "id": astronaut or scenario.get("astronaut", "A1"),
            "timeline": scenario.get("timeline") or [],
            "activity_schedule": scenario.get("activity_schedule") or [],
        }
    ]


def iter_batches(scenario: dict, seed: int, time_scale: float, base_ts: float, duration: float | None = None, astronaut: str | None = None):
    rng = np.random.default_rng(seed)
    span = float(duration if duration is not None else scenario.get("duration", 60))
    step = max(float(time_scale), 1.0)
    jumps = [(float(item["at"]), int(item["seq"])) for item in scenario.get("seq_jumps") or []]
    buffered_from = scenario.get("buffered_from")
    seq = 0
    crews = _crews(scenario, astronaut)
    t = 0.0
    while t < span - 1e-9:
        end = min(span, t + step)
        forced = next((value for at, value in jumps if abs(at - t) < 1e-6), None)
        first = True
        for crew in crews:
            buckets: dict[str, list] = {}
            who = crew["id"]
            for metric in METRICS:
                if metric == "ECG":
                    # LiveRig owns the Lead-II waveform; scenario batches stay scalar vitals.
                    continue
                for moment in due_times(t, end, EVERY[metric]):
                    mode = mode_at(crew.get("activity_schedule") or [], moment)
                    added, hold, dropout = effects_at(crew.get("timeline") or [], metric, moment)
                    value = hold if hold is not None else nominal(who, metric, moment, rng) + added
                    value += ACTIVITY.get(mode, {}).get(metric, 0)
                    quality = 0.2 if dropout else 1.0
                    buckets.setdefault(mode, []).append(
                        {
                            "sensor_id": SENSOR[metric],
                            "value": round(float(value), 4),
                            "unit": UNIT[metric],
                            "quality": quality,
                            "ts_device": base_ts + moment,
                        }
                    )
            for mode, readings in buckets.items():
                for chunk_start in range(0, len(readings), 500):
                    if first and forced is not None:
                        seq = forced
                        first = False
                    else:
                        seq += 1
                    chunk = readings[chunk_start : chunk_start + 500]
                    yield {
                        "device_id": "sim-gw-1",
                        "astronaut_id": who,
                        "seq": seq,
                        "buffered": buffered_from is not None and t >= float(buffered_from),
                        "time_scale": time_scale,
                        "activity_mode": _wire_mode(mode),
                        "ts_device": chunk[-1]["ts_device"],
                        "readings": chunk,
                    }
        t = end
