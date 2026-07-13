"""Energy integration sanity: the zero-wind simulated mission must agree with
a quasi-static analytic cruise-power prediction."""
import math

import pytest

from airloom.aero import build_drag_table
from airloom.frame_gen import build_frame
from airloom.genome import Genome
from airloom.simulator import simulate_scenario


def analytic_cruise_power(mass, drag, rotor, rho, v):
    """Steady level flight force balance, iterated for tilt."""
    g = 9.80665
    disk = math.pi * (rotor.diameter / 2.0) ** 2
    tilt = 0.0
    for _ in range(20):
        d = 0.5 * rho * drag.cda(tilt, 0.0) * v * v
        t = math.hypot(d, mass * g)
        tilt = math.atan2(d, mass * g)
    v_i = math.sqrt(t / (8.0 * rho * disk))
    t += 0.5 * rho * v_i * v_i * drag.wash_cda
    v_ax = v * math.sin(tilt)
    n = rotor.solve_n(t / 4.0, v_ax, rho)
    return 4.0 * rotor.electrical_power(n, v_ax, rho)


def test_zero_wind_energy_matches_quasi_static(cfg, rotor):
    frame = build_frame(Genome.baseline(), cfg.platform)
    drag = build_drag_table(frame, cfg.platform)
    scenario = cfg.scenario("calm_warm")
    assert scenario.wind_speed_ms == 0.0 and scenario.rain_mm_h == 0.0

    res = simulate_scenario(frame.total_mass, drag, rotor, scenario,
                            cfg.mission, cfg.rain)
    assert res.valid, res.failure_reason

    p_cruise = analytic_cruise_power(frame.total_mass, drag, rotor,
                                     scenario.air_density,
                                     cfg.mission.cruise_speed_ms)
    t_cruise = sum(abs(x) for x in cfg.mission.legs_m) / cfg.mission.cruise_speed_ms
    analytic_wh = p_cruise * t_cruise / 3600.0
    # acceleration/braking transients keep this from being exact
    assert res.energy_wh == pytest.approx(analytic_wh, rel=0.06)


def test_energy_scales_with_mass(cfg, rotor):
    """More mass must always cost more energy in the same conditions."""
    frame = build_frame(Genome.baseline(), cfg.platform)
    drag = build_drag_table(frame, cfg.platform)
    scenario = cfg.scenario("calm_warm")
    light = simulate_scenario(frame.total_mass, drag, rotor, scenario,
                              cfg.mission, cfg.rain)
    heavy = simulate_scenario(frame.total_mass + 0.2, drag, rotor, scenario,
                              cfg.mission, cfg.rain)
    assert heavy.energy_wh > light.energy_wh
