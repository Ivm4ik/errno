"""Which samples fall inside a simulated window, and what the timeline does to them."""


def mode_at(schedule: list[dict], t: float) -> str:
    for item in schedule or []:
        if item["at"] <= t < item["at"] + item["duration"]:
            return item.get("mode", "rest")
    return "rest"


def effects_at(timeline: list[dict], metric: str, t: float) -> tuple[float, float | None, bool]:
    """Return (added, absolute hold or None, dropout)."""
    added = 0.0
    hold = None
    dropout = False
    for item in timeline or []:
        if item.get("metric") != metric:
            continue
        if not item["at"] <= t < item["at"] + item["duration"]:
            continue
        effect = item.get("effect", "step")
        magnitude = float(item.get("magnitude", 0))
        span = max(float(item["duration"]), 1e-9)
        phase = (t - item["at"]) / span
        if effect == "dropout":
            dropout = True
        elif effect == "hold":
            hold = magnitude
        elif effect in {"ramp", "drift"}:
            added += magnitude * phase
        elif effect == "spike":
            added += magnitude if t < item["at"] + min(15, item["duration"]) else 0
        else:
            added += magnitude
    return added, hold, dropout


def due(start: float, end: float, every: float) -> list[float]:
    if end <= start or every <= 0:
        return []
    if start <= 0:
        t = 0.0
    else:
        t = int((start + every - 1e-9) // every) * every
        if t < start:
            t += every
    times = []
    while t < end - 1e-9:
        times.append(t)
        t += every
    return times
