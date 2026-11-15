"""Synthetic Lead-II cardiogram samples (mV) paced by bpm — training strip, not clinical."""

from __future__ import annotations

import math

# Demo sample rate pushed to the panel (Hz).
FS = 100
# Chunk length per live push (~0.25 s of strip).
CHUNK = 25


def sample_mv(phase: float, bpm: float) -> float:
    """One sample at normalized beat phase in [0, 1) — clear P–QRS–T morphology."""
    del bpm  # rate is applied by phase step in advance_chunk
    u = phase % 1.0
    y = 0.02 * math.sin(phase * 2 * math.pi * 0.25)  # soft baseline wander

    def bump(u0: float, width: float, amp: float) -> float:
        if width <= 0:
            return 0.0
        t = (u - u0) / width
        if 0.0 <= t <= 1.0:
            return amp * math.sin(t * math.pi)
        return 0.0

    y += bump(0.10, 0.07, 0.16)  # P
    if 0.22 <= u < 0.248:
        y -= 0.14 * ((u - 0.22) / 0.028)  # Q
    y += bump(0.248, 0.032, 1.35)  # R
    y += bump(0.282, 0.04, -0.34)  # S
    y += bump(0.40, 0.18, 0.30)  # T
    return y


def advance_chunk(
    phase: float,
    bpm: float,
    *,
    n: int = CHUNK,
    fs: float = FS,
    noise: float = 0.01,
    center: float = 0.0,
    lo: float = 0.0,
    hi: float = 0.0,
    intensity: float = 0.55,
    rng=None,
) -> tuple[list[float], float]:
    """Return (samples_mV, new_phase).

    bpm ≤ 0 → asystole (flat line at center). Otherwise morphology around center
    with −lo…+hi wander controlled by intensity (same knobs as scalar channels).
    """
    inten = max(0.0, min(1.0, float(intensity)))
    lo = max(0.0, float(lo))
    hi = max(0.0, float(hi))
    mid = float(center)
    try:
        bpm_f = float(bpm)
    except (TypeError, ValueError):
        bpm_f = 0.0
    if bpm_f != bpm_f:  # NaN
        bpm_f = 0.0

    # Asystole / no pulse — do not invent a 72 bpm rhythm.
    if bpm_f <= 0.0:
        out: list[float] = []
        for _ in range(n):
            v = mid
            if rng is not None:
                v += float(rng.normal(0, noise * 0.08 * (0.2 + 0.8 * inten)))
                if lo > 0 or hi > 0:
                    a = 1.0 + 14.0 * (1.0 - inten)
                    t = float(rng.beta(a, a))
                    target = (mid - lo) + t * (lo + hi)
                    mix = 0.12 + 0.88 * inten
                    v = mid + mix * (target - mid)
            out.append(round(v, 4))
        return out, float(phase)

    rate = max(1.0, min(220.0, bpm_f))
    step = (rate / 60.0) / max(fs, 1.0)
    out = []
    p = float(phase)
    for _ in range(n):
        v = mid + sample_mv(p, rate)
        if rng is not None:
            v += float(rng.normal(0, noise * (0.25 + 0.75 * inten)))
            if lo > 0 or hi > 0:
                a = 1.0 + 14.0 * (1.0 - inten)
                t = float(rng.beta(a, a))
                target = (mid - lo) + t * (lo + hi)
                mix = 0.12 + 0.88 * inten
                baseline = mid + mix * (target - mid)
                v = v - mid + baseline
        out.append(round(v, 4))
        p = (p + step) % 1.0
    return out, p
