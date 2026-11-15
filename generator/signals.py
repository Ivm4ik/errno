"""Nominal signals. Numbers match monitoring tables; this package does not import backend."""

import math

import numpy as np

# A1 = Astro1, A2 = Astro2. Anyone else uses Astro1.
BASE = {
    "A1": {
        "HR": 80, "RR": 16, "SPO2": 98, "BP": 110, "BPD": 70, "TEMP": 36.6, "EEG": 20, "ECG": 0.0,
        "GLU": 85, "K": 4.2, "NA": 140, "CA": 9.4, "LAC": 1.2, "ICP": 11, "SLP": 7.5, "SLQ": 7,
        "RAD": 0.2, "RADC": 80, "CO2": 0.3, "ACT": 220, "WELL": 7, "WBC": 6.5, "HCT": 42,
        "CREA": 80, "US": 92,
    },
    "A2": {
        "HR": 78, "RR": 15, "SPO2": 97, "BP": 108, "BPD": 68, "TEMP": 36.7, "EEG": 18, "ECG": 0.0,
        "GLU": 88, "K": 4.18, "NA": 138, "CA": 9.2, "LAC": 1.0, "ICP": 10, "SLP": 7.2, "SLQ": 7,
        "RAD": 0.25, "RADC": 75, "CO2": 0.28, "ACT": 200, "WELL": 7, "WBC": 6.2, "HCT": 41,
        "CREA": 78, "US": 90,
    },
}
DELTA = {
    "HR": 12, "RR": 3, "SPO2": 2, "BP": 10, "BPD": 8, "TEMP": 0.4, "EEG": 10, "ECG": 0.4,
    "GLU": 10, "K": 0.4, "NA": 3, "CA": 0.5, "LAC": 0.6, "ICP": 2.5, "SLP": 0.8, "SLQ": 1.5,
    "RAD": 0.15, "RADC": 5, "CO2": 0.15, "ACT": 40, "WELL": 1.5, "WBC": 1.0, "HCT": 2.0,
    "CREA": 8, "US": 6,
}

# Simulated-second periods from the monitoring table (ship time).
EVERY = {
    "ACT": 1,          # активність — постійний моніторинг
    "HR": 1,           # пульс — безперервно
    "ECG": 0.1,        # ADC-борг; еміт не через wall_period
    "SPO2": 1,         # кисень — безперервно
    "RR": 1,           # дихання — постійний моніторинг
    "EEG": 1,          # ЕЕГ мозку — постійний моніторинг
    "TEMP": 1,         # температура — постійний моніторинг
    "CO2": 1,          # середовище корабля/скафандра — постійно
    "RAD": 1,          # дозиметрія — безперервно
    "ICP": 1,          # внутрішньочерепний тиск — постійний моніторинг
    "LAC": 1800,       # підшкірні хім — кожні 30 хв
    "GLU": 1800,
    "K": 1800,
    "NA": 1800,
    "CA": 1800,
    "BP": 86400,       # тиск — раз на день (пульс/spo2 вище безперервно)
    "BPD": 86400,
    "WELL": 86400,     # загальне самопочуття — щовечора
    "SLP": 86400,      # режим/якість сну — щоранку
    "SLQ": 86400,
    "RADC": 86400,     # звірка накопиченої дози — раз на добу
    "WBC": 604800,     # імунітет / аналізи — раз на 1–2 тижні
    "HCT": 604800,
    "CREA": 604800,    # аналізи крові/сечі — раз на 1–2 тижні
    "US": 1814400,     # УЗД м'язів/кісток — раз на 2–4 тижні (~21 доба)
}

SENSOR = {
    "HR": "hr", "ECG": "ecg", "RR": "resp", "SPO2": "spo2", "BP": "bp_sys", "BPD": "bp_dia", "TEMP": "temp",
    "EEG": "eeg", "GLU": "glucose", "K": "k", "NA": "na", "CA": "ca", "LAC": "lactate",
    "ICP": "icp", "SLP": "sleep_hours", "SLQ": "sleep_quality", "RAD": "radiation_dose_rate",
    "RADC": "radiation_career", "CO2": "co2", "ACT": "activity", "WELL": "wellbeing",
    "WBC": "wbc", "HCT": "hematocrit", "CREA": "creatinine", "US": "ultrasound",
}
UNIT = {
    "HR": "bpm", "ECG": "mV", "RR": "breaths/min", "SPO2": "%", "BP": "mmHg", "BPD": "mmHg", "TEMP": "C",
    "EEG": "index", "GLU": "mg/dL", "K": "mmol/L", "NA": "mmol/L", "CA": "mg/dL", "LAC": "mmol/L",
    "ICP": "mmHg", "SLP": "h", "SLQ": "1-10", "RAD": "mSv/day", "RADC": "mSv", "CO2": "%",
    "ACT": "counts/min", "WELL": "1-10", "WBC": "10^9/L", "HCT": "%", "CREA": "umol/L", "US": "index",
}
METRICS = list(EVERY)

SCHEDULE = {
    "ACT": "Постійний моніторинг",
    "HR": "Безперервно",
    "ECG": "Безперервно · кардіограма Lead II",
    "SPO2": "Безперервно",
    "BP": "Раз на день",
    "BPD": "Раз на день",
    "RR": "Постійний моніторинг",
    "EEG": "Постійний моніторинг",
    "TEMP": "Постійний моніторинг",
    "CO2": "Постійний моніторинг (корабель/скафандр)",
    "RAD": "Безперервно",
    "RADC": "Звірка загальної дози раз на добу",
    "LAC": "Кожні пів години (підшкірні)",
    "GLU": "Кожні пів години (підшкірні)",
    "K": "Кожні пів години (підшкірні)",
    "NA": "Кожні пів години (підшкірні)",
    "CA": "Кожні пів години (підшкірні)",
    "WELL": "Щовечора",
    "SLP": "Щоранку",
    "SLQ": "Щоранку",
    "ICP": "Постійний моніторинг",
    "WBC": "Раз на 1–2 тижні",
    "HCT": "Раз на 1–2 тижні",
    "CREA": "Раз на 1–2 тижні (кров/сеча)",
    "US": "Раз на 2–4 тижні (УЗД)",
}

# Physiological offsets. Exercise raises HR, RR and LAC; the backend zeros those penalties.
ACTIVITY = {
    "sleep": {"HR": -8, "RR": -2, "TEMP": -0.1, "ACT": -150},
    "rest": {},
    "work": {"ACT": 80},
    "exercise": {"HR": 45, "RR": 8, "LAC": 1.4, "ACT": 400},
    "eva": {"HR": 12, "RR": 2, "CO2": 0.04, "ACT": 180},
}


def baseline(astronaut: str, metric: str) -> float:
    table = BASE["A2"] if astronaut == "A2" else BASE["A1"]
    return table[metric]


def nominal(astronaut: str, metric: str, t: float, rng: np.random.Generator) -> float:
    delta = DELTA[metric]
    noise = float(rng.normal(0, 0.12 * delta))
    circ = 0.05 * delta * math.sin(2 * math.pi * t / 86400)
    return baseline(astronaut, metric) + noise + circ
