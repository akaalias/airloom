"""The calibrated drag model must reproduce the CFD measurements it was
fitted to (cfd/calibration.md), and the calibration must actually bite."""
import math

import pytest

from framevo.aero import (build_drag_table, drag_table_from_areas,
                          measure_areas)
from framevo.frame_gen import build_frame
from framevo.genome import Genome

# full-assembly CdA measured by OpenFOAM on the baseline geometry,
# flow along body x (cfd/calibration.md, 2026-07-14)
MEASURED_FULL = {0.0: 0.00684, 20.0: 0.00944, 40.0: 0.01390}


@pytest.fixture(scope="module")
def baseline(cfg):
    return build_frame(Genome.baseline(), cfg.platform)


def test_calibrated_table_reproduces_cfd(cfg, baseline):
    drag = build_drag_table(baseline, cfg.platform)
    for tilt, cda in MEASURED_FULL.items():
        got = drag.cda(math.radians(tilt), 0.0)
        assert got == pytest.approx(cda, rel=0.03), f"tilt {tilt}"


def test_calibration_reduces_cruise_drag(cfg, baseline):
    areas = measure_areas(baseline, cfg.platform)
    cal = drag_table_from_areas(areas)
    raw = drag_table_from_areas(areas, calibrated=False)
    t20 = math.radians(20.0)
    # at cruise tilt the uncalibrated buildup overestimated by ~2x
    assert cal.cda(t20, 0.0) < 0.55 * raw.cda(t20, 0.0)
    # frontal is the mildest correction, but still a reduction
    assert cal.cda(0.0, 0.0) < raw.cda(0.0, 0.0)
    # wash term is deliberately untouched by calibration
    assert cal.wash_cda == pytest.approx(raw.wash_cda)


def test_flight_energy_drops_under_calibration(cfg, rotor, baseline):
    from framevo.simulator import simulate_scenario
    areas = measure_areas(baseline, cfg.platform)
    cal = drag_table_from_areas(areas)
    raw = drag_table_from_areas(areas, calibrated=False)
    scen = cfg.scenario("calm_warm")
    e_cal = simulate_scenario(baseline.total_mass, cal, rotor, scen,
                              cfg.mission, cfg.rain,
                              battery=cfg.platform.battery)
    e_raw = simulate_scenario(baseline.total_mass, raw, rotor, scen,
                              cfg.mission, cfg.rain,
                              battery=cfg.platform.battery)
    assert e_cal.valid and e_raw.valid
    assert e_cal.wh_per_km < e_raw.wh_per_km
