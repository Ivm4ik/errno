import time

from generator.live import LiveRig, wall_period, zone
from generator.signals import EVERY, METRICS, SCHEDULE


def test_live_tick_emits_enabled_channels():
    rig = LiveRig(astronaut_id="A1", seed=7, faults=False, time_scale=60)
    rig.enabled = {"HR", "SPO2"}
    first = rig.tick(now=1_000.0)
    assert {item["sensor_id"] for item in first} == {"hr", "spo2"}
    for item in first:
        assert item["quality"] == 1.0
        assert "ts_device" in item


def test_stress_moves_away_from_baseline():
    rig = LiveRig(astronaut_id="A1", seed=3, faults=False, stress=1.0, time_scale=60)
    rig.enabled = {"HR"}
    for t in range(20):
        rig.tick(now=2_000.0 + t)
    assert abs(rig.channels["HR"].value - 80) > 12


def test_schedule_covers_monitoring_table():
    assert "ACT" in EVERY and EVERY["ACT"] == 1
    assert EVERY["LAC"] == 1800
    assert EVERY["WELL"] == 86400
    assert EVERY["BP"] == 86400
    assert EVERY["WBC"] >= 604800
    assert EVERY["CREA"] >= 604800
    assert EVERY["US"] >= 1_209_600
    assert EVERY["ICP"] == 1
    assert "Постійний" in SCHEDULE["ICP"]
    assert "УЗД" in SCHEDULE["US"]
    assert set(METRICS) == set(EVERY)
    assert set(METRICS) >= {"US", "CREA", "ECG", "HR"}


def test_wall_period_caps_daily_for_demo():
    assert wall_period(1, 60) <= 2
    assert 8 <= wall_period(86400, 60) <= 90
    assert 45 <= wall_period(604800, 60) <= 90


def test_sim_timestamps_advance_with_time_scale():
    rig = LiveRig(astronaut_id="A1", seed=1, faults=False, time_scale=60)
    rig.enabled = {"HR"}
    a = rig.tick(now=rig.wall_started + 1)[0]["ts_device"]
    b = rig.tick(now=rig.wall_started + 2)[0]["ts_device"]
    assert b - a == 60


def test_burst_emits_all_enabled_ignoring_schedule():
    rig = LiveRig(astronaut_id="A1", seed=2, faults=False, time_scale=60)
    rig.enabled = {"HR", "GLU", "WELL"}
    first = rig.tick(now=rig.wall_started)
    assert {item["sensor_id"] for item in first} == {"hr", "glucose", "wellbeing"}
    # Immediate second tick would be gated; burst must still fire.
    burst = rig.burst(randomize=True)
    assert {item["sensor_id"] for item in burst} == {"hr", "glucose", "wellbeing"}
    assert abs(rig.channels["HR"].value - 80) <= 12.01


def test_push_now_single_sensor_ignores_schedule_and_dropout():
    rig = LiveRig(astronaut_id="A1", seed=2, faults=True, time_scale=60, auto=False)
    rig.enabled = {"HR", "GLU", "WELL"}
    rig.channels["HR"].dropout_until = time.time() + 60
    rig.manual["HR"] = 118
    rig.channels["HR"].value = 118
    # Schedule would gate a normal tick right after emit.
    rig.channels["HR"].last_emit_wall = time.time()
    out = rig.push_now(["HR"])
    assert len(out) == 1
    assert out[0]["sensor_id"] == "hr"
    assert out[0]["value"] == 118
    assert out[0]["quality"] == 1.0
    # Wall-clock stamp so crew panel ages / appears immediately (not sim×scale future).
    assert abs(out[0]["ts_device"] - time.time()) < 2


def test_push_now_all_enabled():
    rig = LiveRig(astronaut_id="A1", seed=1, faults=False, time_scale=60, auto=False)
    rig.enabled = {"HR", "SPO2"}
    rig.manual["HR"] = 90
    rig.manual["SPO2"] = 97
    out = rig.push_now()
    assert {item["sensor_id"] for item in out} == {"hr", "spo2"}


def test_burst_manual_uses_wall_timestamp():
    rig = LiveRig(astronaut_id="A1", seed=1, faults=False, time_scale=60, auto=False)
    rig.enabled = {"HR"}
    rig.manual["HR"] = 95
    out = rig.burst()
    assert len(out) == 1
    assert out[0]["value"] == 95
    assert abs(out[0]["ts_device"] - time.time()) < 2


def test_manual_jitter_band_temp():
    """TEMP 38 ±0.2 → stream samples stay in 37.8…38.2; center stays 38."""
    rig = LiveRig(astronaut_id="A1", seed=11, faults=False, time_scale=1, auto=False)
    rig.enabled = {"TEMP"}
    rig.manual["TEMP"] = 38.0
    rig.set_dev("TEMP", lo=0.2, hi=0.2, intensity=1.0)
    vals = []
    for i in range(40):
        out = rig.tick(now=rig.wall_started + i * 2, force=True)
        assert len(out) == 1
        vals.append(out[0]["value"])
        assert abs(out[0]["ts_device"] - (rig.wall_started + i * 2)) < 0.01
    assert min(vals) >= 37.8 - 1e-6
    assert max(vals) <= 38.2 + 1e-6
    assert abs(rig.manual["TEMP"] - 38.0) < 1e-9
    assert max(vals) - min(vals) > 0.05  # actually moves inside the band


def test_asymmetric_minus_plus_band():
    """TEMP 38 −0.1 / +0.4 → 37.9…38.4."""
    rig = LiveRig(astronaut_id="A1", seed=9, faults=False, time_scale=1, auto=False)
    rig.enabled = {"TEMP"}
    rig.manual["TEMP"] = 38.0
    rig.channels["TEMP"].value = 38.0
    rig.set_dev("TEMP", lo=0.1, hi=0.4, intensity=1.0)
    vals = [rig.tick(now=rig.wall_started + i * 2, force=True)[0]["value"] for i in range(60)]
    assert min(vals) >= 37.9 - 1e-6
    assert max(vals) <= 38.4 + 1e-6
    assert max(vals) > 38.15  # reaches into the + side


def test_low_intensity_stays_near_center():
    rig = LiveRig(astronaut_id="A1", seed=3, faults=False, time_scale=1, auto=False)
    rig.enabled = {"TEMP"}
    rig.manual["TEMP"] = 38.0
    rig.channels["TEMP"].value = 38.0
    rig.set_dev("TEMP", lo=0.5, hi=0.5, intensity=0.05)
    vals = [rig.tick(now=rig.wall_started + i * 2, force=True)[0]["value"] for i in range(30)]
    assert all(abs(v - 38.0) < 0.25 for v in vals)


def test_jitter_overrides_auto_for_channel():
    rig = LiveRig(astronaut_id="A1", seed=5, faults=False, time_scale=1, auto=True, stress=1.0)
    rig.enabled = {"TEMP"}
    rig.manual["TEMP"] = 38.0
    rig.set_dev("TEMP", lo=0.2, hi=0.2, intensity=1.0)
    for i in range(20):
        out = rig.tick(now=rig.wall_started + i * 2, force=True)
        assert 37.8 - 1e-6 <= out[0]["value"] <= 38.2 + 1e-6


def test_zone_thresholds():
    assert zone("HR", 80, "A1") == "green"
    assert zone("HR", 80 + 12.1, "A1") == "yellow"
    assert zone("HR", 80 + 25, "A1") == "red"


def test_ecg_chunk_emits_waveform_samples():
    from generator.ecg_wave import CHUNK

    rig = LiveRig(astronaut_id="A1", seed=1, faults=False, time_scale=1, auto=True)
    rig.enabled = {"HR", "ECG"}
    out = rig.tick(now=rig.wall_started, force=True)
    sensors = {item["sensor_id"] for item in out}
    assert "hr" in sensors
    assert "ecg" in sensors
    ecg = [item for item in out if item["sensor_id"] == "ecg"]
    assert len(ecg) == CHUNK
    assert all(item["unit"] == "mV" for item in ecg)
    assert all(-2.5 <= item["value"] <= 2.5 for item in ecg)
    # Timestamps advance within the chunk.
    assert ecg[-1]["ts_device"] > ecg[0]["ts_device"]


def test_ecg_push_now_with_hr_refreshes_strip():
    from generator.ecg_wave import CHUNK

    rig = LiveRig(astronaut_id="A1", seed=2, faults=False, time_scale=1, auto=False)
    rig.enabled = {"HR", "ECG"}
    rig.manual["HR"] = 120
    rig.channels["HR"].value = 120
    out = rig.push_now(["HR"])
    assert {item["sensor_id"] for item in out} == {"hr", "ecg"}
    assert sum(1 for item in out if item["sensor_id"] == "ecg") == CHUNK


def test_ecg_minus_plus_intensity_widens_noise():
    calm = LiveRig(astronaut_id="A1", seed=7, faults=False, time_scale=1, auto=False)
    calm.enabled = {"ECG", "HR"}
    calm.manual["ECG"] = 0.0
    calm.set_dev("ECG", lo=0.0, hi=0.0, intensity=0.1)
    wild = LiveRig(astronaut_id="A1", seed=7, faults=False, time_scale=1, auto=False)
    wild.enabled = {"ECG", "HR"}
    wild.manual["ECG"] = 0.0
    wild.set_dev("ECG", lo=0.35, hi=0.45, intensity=1.0)
    calm_vals = [v for _ in range(8) for v in (x["value"] for x in calm._ecg_chunk(calm.wall_started, force=True))]
    wild_vals = [v for _ in range(8) for v in (x["value"] for x in wild._ecg_chunk(wild.wall_started, force=True))]
    assert max(wild_vals) - min(wild_vals) > max(calm_vals) - min(calm_vals)


def test_ecg_center_shifts_baseline_like_other_channels():
    """Центр 0.4 → strip sits higher than центр 0 (same knobs as ACT/TEMP)."""
    low = LiveRig(astronaut_id="A1", seed=3, faults=False, time_scale=1, auto=False)
    low.enabled = {"ECG", "HR"}
    low.set_value("ECG", 0.0, hold=True)
    low.set_value("HR", 80, hold=True)
    low.set_dev("ECG", lo=0.0, hi=0.0, intensity=0.2)
    high = LiveRig(astronaut_id="A1", seed=3, faults=False, time_scale=1, auto=False)
    high.enabled = {"ECG", "HR"}
    high.set_value("ECG", 0.4, hold=True)
    high.set_value("HR", 80, hold=True)
    high.set_dev("ECG", lo=0.0, hi=0.0, intensity=0.2)
    a = [x["value"] for x in low._ecg_chunk(low.wall_started, force=True)]
    b = [x["value"] for x in high._ecg_chunk(high.wall_started, force=True)]
    assert sum(b) / len(b) > sum(a) / len(a) + 0.25


def test_ecg_sample_debt_ignores_wall_period_floor():
    """Δt=0.2 s @ 100 Hz → ~20 samples; two quick ticks are not stuck on 0.25 s gate."""
    from generator.ecg_wave import FS

    rig = LiveRig(astronaut_id="A1", seed=1, faults=False, time_scale=1, auto=True)
    rig.enabled = {"ECG", "HR"}
    t0 = rig.wall_started
    first = [x for x in rig.tick(now=t0) if x["sensor_id"] == "ecg"]
    assert len(first) >= 1
    mid = [x for x in rig.tick(now=t0 + 0.1) if x["sensor_id"] == "ecg"]
    assert 8 <= len(mid) <= 12
    second = [x for x in rig.tick(now=t0 + 0.3) if x["sensor_id"] == "ecg"]
    assert 18 <= len(second) <= 22
    assert abs((second[-1]["ts_device"] - second[0]["ts_device"]) - (len(second) - 1) / FS) < 1e-6
    # Phase continues (not a reset).
    assert rig.ecg_phase != 0.0


def test_ecg_hr_zero_is_flatline_asystole():
    """Пульс 0 → рівна лінія, без вигаданого QRS."""
    from generator.ecg_wave import advance_chunk

    samples, _ = advance_chunk(0.0, 0.0, n=50, center=0.0, lo=0.0, hi=0.0, intensity=0.5, rng=None)
    assert all(abs(v) < 1e-9 for v in samples)
    rig = LiveRig(astronaut_id="A1", seed=1, faults=False, time_scale=1, auto=False)
    rig.enabled = {"ECG", "HR"}
    rig.set_value("HR", 0, hold=True)
    rig.set_value("ECG", 0.0, hold=True)
    out = [x["value"] for x in rig._ecg_chunk(rig.wall_started, force=True)]
    assert out and max(abs(v) for v in out) < 0.05


def test_set_value_clips_and_holds_manual():
    rig = LiveRig(astronaut_id="A1", seed=1, faults=False, auto=True)
    out = rig.set_value("HR", 999)
    assert out == 300
    assert rig.manual["HR"] == 300
    assert rig.channels["HR"].value == 300
    assert rig.auto is False
    # Below old clip(35): demo can push into SIGNAL_LOST / critical territory.
    assert rig.set_value("HR", 12, hold=True) == 12
    assert rig.set_value("HR", float("nan")) == 0  # NaN → low bound, no crash


def test_apply_scene_yellow_is_outside_green():
    rig = LiveRig(astronaut_id="A1", seed=1, faults=False)
    rig.apply_scene("yellow")
    assert zone("HR", rig.channels["HR"].value, "A1") in {"yellow", "red"}
