"""Telemetry tap + flight payload generation for the gallery flight tab."""
import json
import math

import pytest

from airloom.aero import build_drag_table
from airloom.flythrough import write_flights_for
from airloom.frame_gen import build_frame
from airloom.genome import Genome
from airloom.simulator import simulate_scenario


@pytest.fixture(scope="module")
def baseline(cfg):
    frame = build_frame(Genome.baseline(), cfg.platform)
    return frame, build_drag_table(frame, cfg.platform)


def test_trace_off_by_default(cfg, rotor, baseline):
    frame, drag = baseline
    res = simulate_scenario(frame.total_mass, drag, rotor,
                            cfg.scenario("calm_warm"), cfg.mission, cfg.rain,
                            battery=cfg.platform.battery)
    assert res.trace is None


def test_trace_channels_and_decimation(cfg, rotor, baseline):
    frame, drag = baseline
    res = simulate_scenario(frame.total_mass, drag, rotor,
                            cfg.scenario("calm_warm"), cfg.mission, cfg.rain,
                            battery=cfg.platform.battery, trace_hz=10.0)
    tr = res.trace
    assert tr is not None and tr["hz"] == pytest.approx(10.0)
    n = len(tr["x"])
    assert n == pytest.approx(res.flight_time_s * 10.0, abs=3)
    for ch in ("y", "z", "tx", "ty", "tz", "rpm", "vt", "pw", "lim",
               "wx", "wy", "wz"):
        assert len(tr[ch]) == n, ch
    # thrust direction is a unit vector at every sample
    for i in (0, n // 2, n - 1):
        m = math.hypot(tr["tx"][i], tr["ty"][i], tr["tz"][i])
        assert m == pytest.approx(1.0, abs=0.01)
    # the mission goes 2 km out along +x and returns
    assert max(tr["x"]) > 1900.0 and abs(tr["x"][-1]) < 100.0
    # trace identical scoring: same energy path as the untraced flight
    ref = simulate_scenario(frame.total_mass, drag, rotor,
                            cfg.scenario("calm_warm"), cfg.mission, cfg.rain,
                            battery=cfg.platform.battery)
    assert res.energy_wh == pytest.approx(ref.energy_wh, rel=1e-9)


def test_write_flights_for_baseline(cfg, tmp_path):
    png = tmp_path / "deadbeef1234.png"
    png.touch()
    files = write_flights_for(cfg, Genome.baseline().as_dict(),
                              "deadbeef1234", str(png),)
    assert set(files) == {s.name for s in cfg.scenarios}
    storm = (tmp_path / "deadbeef1234.storm.flight.js").read_text()
    assert storm.startswith('airloomFlight("deadbeef1234","storm",')
    payload = json.loads(storm[storm.index(",{") + 1:-2])
    assert payload["rain"] > 0 and payload["hz"] == pytest.approx(10.0)
    assert len(payload["x"]) > 1000
    # cached: second call must not re-simulate (files already present)
    import time
    m0 = (tmp_path / "deadbeef1234.storm.flight.js").stat().st_mtime
    time.sleep(0.05)
    write_flights_for(cfg, Genome.baseline().as_dict(),
                      "deadbeef1234", str(png))
    assert (tmp_path / "deadbeef1234.storm.flight.js").stat().st_mtime == m0
