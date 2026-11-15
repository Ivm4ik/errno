"""Live sensor rig: schedule, zones, auto noise, manual set, instant push."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np

from generator.ecg_wave import CHUNK, FS, advance_chunk
from generator.signals import ACTIVITY, DELTA, EVERY, METRICS, SCHEDULE, SENSOR, UNIT, baseline

TOLERANCE = {code: float(DELTA[code]) for code in METRICS}

# Yellow when |v-base| > tol; red when > tol * RED_MULT.
YELLOW_MULT = 1.0
RED_MULT = 2.0

# Demo clip window — wide enough to reach clinical red AND SIGNAL_LOST edges
# (e.g. HR < 20). Tighter clinical bands live in the panel, not here.
CLIP = {
    "HR": (0, 300), "ECG": (-2.5, 2.5), "RR": (0, 80), "SPO2": (0, 100), "BP": (40, 260), "BPD": (20, 160),
    "TEMP": (25.0, 48.0), "EEG": (0, 100), "GLU": (10, 540), "K": (1.0, 9.0), "NA": (100, 180),
    "CA": (4.0, 16.0), "LAC": (0.0, 20.0), "ICP": (0, 40), "SLP": (0, 16), "SLQ": (1, 10),
    "RAD": (0, 50), "RADC": (0, 800), "CO2": (0.0, 10.0), "ACT": (0, 5000), "WELL": (1, 10),
    "WBC": (0.5, 50), "HCT": (10, 70), "CREA": (20, 400), "US": (0, 100),
}

# UI / meta grouping by ship schedule.
GROUP = {
    "ACT": "continuous", "HR": "continuous", "ECG": "continuous", "RR": "continuous", "SPO2": "continuous",
    "TEMP": "continuous", "EEG": "continuous", "CO2": "continuous", "RAD": "continuous",
    "ICP": "continuous",
    "LAC": "chem", "GLU": "chem", "K": "chem", "NA": "chem", "CA": "chem",
    "BP": "daily", "BPD": "daily", "WELL": "daily", "SLP": "daily", "SLQ": "daily", "RADC": "daily",
    "WBC": "rare", "HCT": "rare", "CREA": "rare", "US": "rare",
}
GROUP_LABEL = {
    "continuous": "Постійно",
    "chem": "Хімія · 30 хв",
    "daily": "Щодня",
    "rare": "Рідко · кров/УЗД",
}


def wall_period(sim_period: float, time_scale: float) -> float:
    """Map ship-seconds to wall seconds. Cap rare labs so demos stay usable."""
    scale = max(float(time_scale), 1.0)
    raw = float(sim_period) / scale
    if sim_period >= 86400:
        return max(45.0, min(raw, 90.0))
    if sim_period >= 3600:
        return max(8.0, min(raw, 40.0))
    if sim_period >= 1800:
        return max(5.0, min(raw, 30.0))
    # Continuous vitals: snappy demo uplink to the crew panel.
    return max(0.25, raw)


def _clip(metric: str, value: float) -> float:
    low, high = CLIP[metric]
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(low)
    if number != number:  # NaN — keep channel alive, park at low bound
        return float(low)
    return float(min(high, max(low, number)))


def zone(code: str, value: float, astronaut_id: str = "A1") -> str:
    """green / yellow / red from baseline ± tolerance."""
    base = baseline(astronaut_id, code)
    tol = TOLERANCE[code]
    delta = abs(float(value) - base)
    if delta > tol * RED_MULT:
        return "red"
    if delta > tol * YELLOW_MULT:
        return "yellow"
    return "green"


def zone_bounds(code: str, astronaut_id: str = "A1") -> dict:
    base = baseline(astronaut_id, code)
    tol = TOLERANCE[code]
    return {
        "baseline": base,
        "tolerance": tol,
        "yellow_lo": base - tol * YELLOW_MULT,
        "yellow_hi": base + tol * YELLOW_MULT,
        "red_lo": base - tol * RED_MULT,
        "red_hi": base + tol * RED_MULT,
    }


@dataclass
class ChannelState:
    value: float
    stuck_until: float = 0.0
    stuck_value: float | None = None
    dropout_until: float = 0.0
    last_emit_wall: float = 0.0


@dataclass
class LiveRig:
    astronaut_id: str
    seed: int = 1
    activity_mode: str = "rest"
    time_scale: float = 60.0
    stress: float = 0.0
    bias: dict[str, float] = field(default_factory=dict)
    jitter: dict[str, float] = field(default_factory=dict)  # legacy ± span; mirrored from lo/hi
    jitter_lo: dict[str, float] = field(default_factory=dict)  # how far below center
    jitter_hi: dict[str, float] = field(default_factory=dict)  # how far above center
    intensity: dict[str, float] = field(default_factory=dict)  # 0..1 chaos inside the band
    enabled: set[str] = field(default_factory=lambda: set(METRICS))
    faults: bool = True
    fault_rate: float = 0.02
    auto: bool = True
    manual: dict[str, float] = field(default_factory=dict)
    channels: dict[str, ChannelState] = field(default_factory=dict)
    wall_started: float = field(default_factory=time.time)
    sim_started: float = field(default_factory=time.time)
    ecg_phase: float = 0.0
    last_ecg_sample_wall: float = 0.0

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)
        now = time.time()
        self.wall_started = now
        self.sim_started = now
        self.ecg_phase = 0.0
        self.last_ecg_sample_wall = 0.0
        for code in METRICS:
            base = baseline(self.astronaut_id, code)
            self.channels[code] = ChannelState(value=base)
            self.manual.setdefault(code, base)
            self.bias.setdefault(code, 0.0)
            self.jitter.setdefault(code, 0.0)
            self.jitter_lo.setdefault(code, float(self.jitter.get(code, 0.0) or 0.0))
            self.jitter_hi.setdefault(code, float(self.jitter.get(code, 0.0) or 0.0))
            self.intensity.setdefault(code, 0.55)

    def _dev_band(self, code: str) -> tuple[float, float]:
        """Return (minus, plus) distances from center. Falls back to legacy ±jitter."""
        lo = abs(float(self.jitter_lo.get(code, 0.0) or 0.0))
        hi = abs(float(self.jitter_hi.get(code, 0.0) or 0.0))
        if lo == 0.0 and hi == 0.0:
            j = abs(float(self.jitter.get(code, 0.0) or 0.0))
            return j, j
        return lo, hi

    def set_dev(self, code: str, *, lo: float | None = None, hi: float | None = None, intensity: float | None = None) -> None:
        code = code.upper()
        if lo is not None:
            self.jitter_lo[code] = max(0.0, float(lo))
        if hi is not None:
            self.jitter_hi[code] = max(0.0, float(hi))
        if intensity is not None:
            self.intensity[code] = float(np.clip(intensity, 0.0, 1.0))
        self.jitter[code] = max(self.jitter_lo.get(code, 0.0), self.jitter_hi.get(code, 0.0))

    def sim_now(self, now: float | None = None) -> float:
        wall = time.time() if now is None else now
        return self.sim_started + (wall - self.wall_started) * max(self.time_scale, 1.0)

    def clear_faults(self, code: str | None = None) -> None:
        codes = [code] if code else list(METRICS)
        for c in codes:
            ch = self.channels[c]
            ch.stuck_until = 0.0
            ch.stuck_value = None
            ch.dropout_until = 0.0

    def set_value(self, code: str, value: float, *, hold: bool = True) -> float:
        """Clip + write channel/manual. hold=True → leave auto off path for this value.

        Does not raise on bad input — clamps/NaN-guards so the generator UI never dies
        when an operator types an empty or extreme value.
        """
        code = code.upper()
        if code not in self.channels:
            raise KeyError(code)
        clipped = _clip(code, value)
        self.channels[code].value = clipped
        self.manual[code] = clipped
        self.clear_faults(code)
        if hold:
            self.auto = False
        return clipped

    def reset_to_baseline(self) -> None:
        for code in METRICS:
            base = baseline(self.astronaut_id, code)
            ch = self.channels[code]
            ch.value = base
            self.manual[code] = base
            self.bias[code] = 0.0
            self.jitter[code] = 0.0
            self.jitter_lo[code] = 0.0
            self.jitter_hi[code] = 0.0
            self.intensity[code] = 0.55
            self.clear_faults(code)
        self.ecg_phase = 0.0
        self.last_ecg_sample_wall = 0.0
        self.stress = 0.0

    def apply_scene(self, scene: str) -> None:
        """Demo scenes: nominal | yellow | red_high | red_low | random."""
        scene = (scene or "nominal").lower().strip()
        if scene in {"nominal", "norma", "ok", "green"}:
            self.auto = True
            self.reset_to_baseline()
            return
        if scene in {"random", "shuffle", "rand"}:
            self.auto = False
            self.randomize_in_band()
            return

        sign = -1.0 if scene in {"red_low", "crit_low", "low"} else 1.0
        if scene in {"yellow", "caution", "warn"}:
            pull = 1.15  # just past yellow threshold
            self.auto = False
            for code in METRICS:
                base = baseline(self.astronaut_id, code)
                tol = TOLERANCE[code]
                self.set_value(code, base + sign * tol * pull, hold=True)
            self.stress = 0.0
            return

        # red / critical
        self.auto = True
        self.stress = sign * 1.0
        for code in METRICS:
            self.bias[code] = sign * 0.85
            base = baseline(self.astronaut_id, code)
            tol = TOLERANCE[code]
            # seed channel into red so UI shows immediately before auto catches up
            self.set_value(code, base + sign * tol * 2.4, hold=False)
        self.auto = True

    def snapshot(self) -> dict:
        now = time.time()
        out = []
        for code in METRICS:
            ch = self.channels[code]
            bounds = zone_bounds(code, self.astronaut_id)
            value = ch.value
            group = GROUP.get(code, "rare")
            age = None if not ch.last_emit_wall else max(0.0, now - ch.last_emit_wall)
            out.append(
                {
                    "code": code,
                    "sensor_id": SENSOR[code],
                    "unit": UNIT[code],
                    "label_schedule": SCHEDULE[code],
                    "group": group,
                    "group_label": GROUP_LABEL[group],
                    "value": round(value, 4),
                    "baseline": bounds["baseline"],
                    "tolerance": bounds["tolerance"],
                    "yellow_lo": round(bounds["yellow_lo"], 4),
                    "yellow_hi": round(bounds["yellow_hi"], 4),
                    "red_lo": round(bounds["red_lo"], 4),
                    "red_hi": round(bounds["red_hi"], 4),
                    "every_sim_s": EVERY[code],
                    "every_wall_s": round(wall_period(EVERY[code], self.time_scale), 2),
                    "enabled": code in self.enabled,
                    # Waveform amplitude is not a clinical band — follow HR zone when present.
                    "band": (
                        zone("HR", self.channels["HR"].value, self.astronaut_id)
                        if code == "ECG" and "HR" in self.channels
                        else zone(code, value, self.astronaut_id)
                    ),
                    "fault": "dropout" if now < ch.dropout_until else ("stuck" if now < ch.stuck_until else None),
                    "bias": self.bias.get(code, 0.0),
                    "jitter": self.jitter.get(code, 0.0),
                    "jitter_lo": round(self._dev_band(code)[0], 6),
                    "jitter_hi": round(self._dev_band(code)[1], 6),
                    "intensity": round(float(self.intensity.get(code, 0.55)), 4),
                    "age_sec": None if age is None else round(age, 2),
                }
            )
        bands = {"green": 0, "yellow": 0, "red": 0, "off": 0}
        for ch in out:
            if not ch["enabled"]:
                bands["off"] += 1
            else:
                bands[ch["band"]] += 1
        return {
            "astronaut_id": self.astronaut_id,
            "activity_mode": self.activity_mode,
            "time_scale": self.time_scale,
            "sim_now": self.sim_now(now),
            "auto": self.auto,
            "faults": self.faults,
            "fault_rate": self.fault_rate,
            "stress": self.stress,
            "summary": bands,
            "channels": out,
        }

    def _target(self, code: str) -> float:
        base = baseline(self.astronaut_id, code)
        tol = TOLERANCE[code]
        pull = float(np.clip(self.stress + self.bias.get(code, 0.0), -1.5, 1.5))
        return base + pull * tol * 2.5 + ACTIVITY.get(self.activity_mode, {}).get(code, 0)

    def _sample(self, code: str, sim: float, *, force: bool = False) -> tuple[float, float] | None:
        """Return (value, quality) or None when channel is in dropout (unless force)."""
        ch = self.channels[code]
        wall = time.time()
        if not force and self.faults and wall >= ch.stuck_until and wall >= ch.dropout_until:
            if self.rng.random() < self.fault_rate:
                if self.rng.random() < 0.45:
                    ch.dropout_until = wall + float(self.rng.uniform(2.0, 8.0))
                else:
                    ch.stuck_until = wall + float(self.rng.uniform(3.0, 12.0))
                    ch.stuck_value = ch.value

        if not force and wall < ch.dropout_until:
            return None

        if not force and wall < ch.stuck_until and ch.stuck_value is not None:
            return float(ch.stuck_value), 0.25

        # Manual band: center −lo … +hi (e.g. 38 −0.2 / +0.3). Intensity = chaos inside.
        lo, hi = self._dev_band(code)
        if code in self.manual and (not self.auto or lo > 0 or hi > 0):
            center = float(self.manual[code])
            if lo > 0 or hi > 0:
                inten = float(np.clip(self.intensity.get(code, 0.55), 0.0, 1.0))
                # Beta peaks at center when calm; flattens to uniform when intensity→1.
                a = 1.0 + 14.0 * (1.0 - inten)
                t = float(self.rng.beta(a, a))  # 0..1
                target = (center - lo) + t * (lo + hi)
                mix = 0.12 + 0.88 * inten  # calm = soft walk, wild = hard jump
                value = float(ch.value) + mix * (target - float(ch.value))
            else:
                value = center + float(self.rng.normal(0, 0.02 * TOLERANCE[code]))
            value = _clip(code, value)
            ch.value = value
            return value, 1.0

        target = self._target(code)
        tol = TOLERANCE[code]
        noise = float(self.rng.normal(0, 0.25 * tol))
        circ = 0.08 * tol * math.sin(2 * math.pi * (sim - self.sim_started) / 600.0 + hash(code) % 7)
        if code == "EEG":
            # Fatigue index: slow circadian drift + ~10 Hz alpha wobble (demo-scale).
            alpha = 1.6 * math.sin(2 * math.pi * 10.0 * (sim - self.sim_started))
            slow = 3.0 * math.sin(2 * math.pi * (sim - self.sim_started) / 3600.0)
            noise = float(self.rng.normal(0, 0.35)) + alpha * 0.15
            circ = slow
        elif code == "HR":
            # Sinus arrhythmia + soft respiratory coupling (~0.2 Hz).
            resp = 1.8 * math.sin(2 * math.pi * 0.2 * (sim - self.sim_started))
            noise = float(self.rng.normal(0, 0.45)) + resp
        if self.rng.random() < 0.03:
            noise += float(self.rng.choice([-1, 1])) * tol * float(self.rng.uniform(0.6, 1.3))
        value = ch.value + 0.35 * (target - ch.value) + noise + circ
        value = _clip(code, value)
        quality = 1.0
        if self.faults and not force and self.rng.random() < self.fault_rate * 0.5:
            quality = 0.2
        if code == "RADC":
            value = _clip(code, value + abs(float(self.rng.normal(0, 0.002))))
        ch.value = value
        return value, quality

    def randomize_in_band(self) -> None:
        """Scatter each enabled channel inside −lo…+hi (or ±Δ if unset)."""
        for code in METRICS:
            if code not in self.enabled:
                continue
            center = float(self.manual.get(code, baseline(self.astronaut_id, code)))
            lo, hi = self._dev_band(code)
            if lo == 0 and hi == 0:
                lo = hi = TOLERANCE[code]
            value = _clip(code, center - lo + float(self.rng.random()) * (lo + hi))
            self.channels[code].value = value
            self.manual[code] = value
            self.clear_faults(code)

    def _ecg_chunk(self, wall: float, *, force: bool = False) -> list[dict]:
        """ADC sample-debt: emit floor(Δt × FS) Lead-II samples — not wall_period-gated."""
        if "ECG" not in self.enabled:
            return []
        ch = self.channels["ECG"]
        if self.last_ecg_sample_wall <= 0:
            self.last_ecg_sample_wall = wall - (CHUNK / FS)
        owed = int((wall - self.last_ecg_sample_wall) * FS)
        if force:
            n = max(owed, CHUNK)
        else:
            n = owed
        if n < 1:
            return []
        n = min(n, 50)
        bpm = float(self.channels["HR"].value if "HR" in self.channels else baseline(self.astronaut_id, "HR"))
        if "HR" in self.manual and (not self.auto or self._dev_band("HR") != (0.0, 0.0)):
            bpm = float(self.manual["HR"])
        if "ECG" in self.manual and (not self.auto or self._dev_band("ECG") != (0.0, 0.0)):
            center = float(self.manual["ECG"])
        else:
            center = float(ch.value if ch.value == ch.value else baseline(self.astronaut_id, "ECG"))
        lo, hi = self._dev_band("ECG")
        inten = float(self.intensity.get("ECG", 0.55))
        samples, self.ecg_phase = advance_chunk(
            self.ecg_phase,
            bpm,
            n=n,
            rng=self.rng,
            center=center,
            lo=lo,
            hi=hi,
            intensity=inten,
        )
        samples = [_clip("ECG", v) for v in samples]
        dt = 1.0 / FS
        start = self.last_ecg_sample_wall
        self.last_ecg_sample_wall = start + n * dt
        ch.last_emit_wall = wall
        ch.value = samples[-1] if samples else center
        out: list[dict] = []
        for i, value in enumerate(samples):
            out.append(
                {
                    "sensor_id": "ecg",
                    "value": value,
                    "unit": "mV",
                    "quality": 1.0,
                    "ts_device": start + (i + 1) * dt,
                }
            )
        return out

    def tick(self, now: float | None = None, *, force: bool = False) -> list[dict]:
        wall = time.time() if now is None else now
        sim = self.sim_now(wall)
        # Manual / ± band: wall clock so the crew panel ages in realtime.
        has_band = any(self._dev_band(c) != (0.0, 0.0) for c in METRICS)
        stamp = wall if (not self.auto or has_band) else sim
        readings: list[dict] = []

        for code in METRICS:
            if code == "ECG":
                continue
            if code not in self.enabled:
                continue
            ch = self.channels[code]
            if not force:
                period = wall_period(EVERY[code], self.time_scale)
                if ch.last_emit_wall and wall - ch.last_emit_wall < period * 0.92:
                    continue

            sampled = self._sample(code, sim, force=force)
            if sampled is None:
                ch.last_emit_wall = wall
                continue
            value, quality = sampled
            ch.last_emit_wall = wall
            readings.append(
                {
                    "sensor_id": SENSOR[code],
                    "value": round(float(value), 4),
                    "unit": UNIT[code],
                    "quality": quality,
                    "ts_device": stamp,
                }
            )
        readings.extend(self._ecg_chunk(wall, force=force))
        return readings

    def _want_ecg(self, codes: set[str] | None) -> bool:
        if "ECG" not in self.enabled:
            return False
        if codes is None:
            return True
        return "ECG" in codes or "HR" in codes

    def _emit_channels(self, codes: set[str] | None = None, *, wall_ts: bool = False) -> list[dict]:
        """Push current channel values as-is (no resample). wall_ts=True → panel ages in realtime."""
        wall = time.time()
        stamp = wall if wall_ts else self.sim_now(wall)
        wanted = codes if codes is not None else self.enabled
        readings: list[dict] = []
        for code in METRICS:
            if code == "ECG":
                continue
            if code not in wanted or code not in self.enabled:
                continue
            ch = self.channels[code]
            ch.last_emit_wall = wall
            self.clear_faults(code)
            readings.append(
                {
                    "sensor_id": SENSOR[code],
                    "value": round(float(ch.value), 4),
                    "unit": UNIT[code],
                    "quality": 1.0,
                    "ts_device": stamp,
                }
            )
        if self._want_ecg(codes):
            readings.extend(self._ecg_chunk(wall, force=True))
        return readings

    def burst(self, *, randomize: bool = False, codes: set[str] | None = None) -> list[dict]:
        """Immediate push for demos: ignore schedule, stamp with wall clock so the panel updates now."""
        if randomize:
            self.randomize_in_band()
            return self._emit_channels(codes, wall_ts=True)
        for code in METRICS:
            if codes is not None and code not in codes:
                continue
            if code not in self.enabled:
                continue
            if code == "ECG":
                continue  # strip rebuilt in _emit_channels from center/−/+/intensity
            if code in self.manual:
                self.set_value(code, float(self.manual[code]), hold=True)
        return self._emit_channels(codes, wall_ts=True)

    def push_now(self, codes: list[str] | None = None) -> list[dict]:
        """Immediate ingest — ignores schedule/dropout. Wall-clock ts so the panel updates now."""
        wanted = {c.upper() for c in codes} if codes else None
        for code in METRICS:
            if wanted is not None and code not in wanted:
                continue
            if code not in self.enabled:
                continue
            if code == "ECG":
                continue  # strip rebuilt in _emit_channels from center/−/+/intensity
            if code in self.manual:
                self.channels[code].value = _clip(code, float(self.manual[code]))
        return self._emit_channels(wanted, wall_ts=True)
