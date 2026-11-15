import json
import subprocess
import sys
from pathlib import Path

from generator.engine import iter_batches, list_scenarios, load_scenario
from generator.signals import DELTA, baseline

ROOT = Path(__file__).resolve().parents[2]


def test_fifteen_scenarios_exist():
    names = list_scenarios()
    assert len(names) == 15
    assert "solar_storm" in names and "multi_astronaut" in names


def test_nominal_stays_inside_tolerance():
    scenario = load_scenario("nominal")
    batches = list(iter_batches(scenario, seed=2, time_scale=60, base_ts=1_700_000_000))
    assert batches
    for envelope in batches:
        assert envelope["device_id"] == "sim-gw-1"
        watched = {"hr": "HR", "resp": "RR", "spo2": "SPO2", "temp": "TEMP", "radiation_dose_rate": "RAD", "co2": "CO2"}
        for reading in envelope["readings"]:
            metric = watched.get(reading["sensor_id"])
            if metric is None:
                continue
            assert abs(reading["value"] - baseline("A1", metric)) <= DELTA[metric]


def test_exercise_raises_hr_but_marks_the_mode():
    scenario = load_scenario("exercise_false_alarm")
    batches = list(iter_batches(scenario, seed=1, time_scale=60, base_ts=0))
    hearts = [reading["value"] for env in batches for reading in env["readings"] if reading["sensor_id"] == "hr"]
    assert hearts and min(hearts) > baseline("A1", "HR") + 30
    assert all(env["activity_mode"] == "exercise" for env in batches)


def test_duplicate_seq_and_gap_and_offline_cli():
    scenario = load_scenario("duplicate_and_gap")
    seqs = [env["seq"] for env in iter_batches(scenario, seed=1, time_scale=60, base_ts=0)]
    assert seqs[0] == 1
    assert seqs.count(1) >= 2
    assert 8 in seqs
    proc = subprocess.run(
        [sys.executable, "-m", "generator", "run", "--scenario", "nominal", "--no-network", "--time-scale", "60", "--duration", "60"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    line = json.loads(proc.stdout.splitlines()[0])
    assert line["readings"] and line["time_scale"] == 60
