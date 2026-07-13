"""Battery pack model: voltage sag, deliverable-power ceiling, IR losses.

The pack is modeled as V = V0 - I*R with a cell current rating; the sim
solves pack current from demanded motor power each step, integrates energy
at the pack terminals (motor power + I^2 R), and scales the RPM ceiling
with the sagged terminal voltage.
"""
import dataclasses
import math

import pytest

from framevo.aero import build_drag_table
from framevo.frame_gen import build_frame
from framevo.genome import Genome
from framevo.simulator import simulate_scenario


@pytest.fixture(scope="module")
def baseline(cfg):
    frame = build_frame(Genome.baseline(), cfg.platform)
    return frame, build_drag_table(frame, cfg.platform)


def test_platform_pack_limits_configured(cfg):
    b = cfg.platform.battery
    assert b.internal_resistance_ohm > 0.0
    assert math.isfinite(b.max_current_a)
    # 6S1P 21700: deliverable ceiling V0^2/(4R) must sit far below the
    # 4 x 500 W the per-motor limits alone would allow
    assert b.voltage_nominal ** 2 / (4.0 * b.internal_resistance_ohm) < 1000.0


def test_baseline_still_flies_with_pack_model(cfg, rotor, baseline):
    frame, drag = baseline
    res = simulate_scenario(frame.total_mass, drag, rotor,
                            cfg.scenario("calm_warm"), cfg.mission, cfg.rain,
                            battery=cfg.platform.battery)
    assert res.valid, res.failure_reason
    # cruise draws far less than the pack ceiling, with visible sag
    assert 0.0 < res.peak_pack_power_w < 600.0
    assert 0.0 < res.min_pack_voltage_v < cfg.platform.battery.voltage_nominal


def test_pack_ir_losses_increase_energy(cfg, rotor, baseline):
    frame, drag = baseline
    scen = cfg.scenario("calm_warm")
    no_pack = simulate_scenario(frame.total_mass, drag, rotor, scen,
                                cfg.mission, cfg.rain)
    packed = simulate_scenario(frame.total_mass, drag, rotor, scen,
                               cfg.mission, cfg.rain,
                               battery=cfg.platform.battery)
    assert packed.valid and no_pack.valid
    # I^2 R loss must show up: a few percent, not zero and not wild
    ratio = packed.energy_wh / no_pack.energy_wh
    assert 1.005 < ratio < 1.15


def test_pack_current_solution_matches_quadratic(cfg):
    b = cfg.platform.battery
    v0, r = b.voltage_nominal, b.internal_resistance_ohm
    p_motors = 300.0
    i = (v0 - math.sqrt(v0 * v0 - 4.0 * r * p_motors)) / (2.0 * r)
    # the solved current must reproduce the demanded power at the sagged V
    assert (v0 - i * r) * i == pytest.approx(p_motors, rel=1e-9)
    # and pack-side power is exactly V0 * I
    assert p_motors + i * i * r == pytest.approx(v0 * i, rel=1e-9)


def test_storm_saturation_clamps_instead_of_killing(cfg, rotor, baseline):
    """The fixed 6S1P pack cannot hold 12 m/s through the storm's worst
    gusts -- the vehicle must ride through at its capability limit, arrive
    a little late and pay energy, NOT be declared a crash."""
    frame, drag = baseline
    scen = cfg.scenario("storm")
    res = simulate_scenario(frame.total_mass, drag, rotor, scen,
                            cfg.mission, cfg.rain,
                            battery=cfg.platform.battery)
    assert res.valid, res.failure_reason
    assert res.sat_time_s > 1.0          # it really was thrust-limited
    nominal_t = sum(abs(x) for x in cfg.mission.legs_m) / cfg.mission.cruise_speed_ms
    assert res.sat_time_s < cfg.mission.saturation_frac_limit * nominal_t
    no_pack = simulate_scenario(frame.total_mass, drag, rotor, scen,
                                cfg.mission, cfg.rain)
    assert res.wh_per_km > no_pack.wh_per_km  # the pack limit costs energy


def test_overweight_fails_on_pack_not_motors(cfg, rotor, baseline):
    """A demand the motors could nominally meet but the pack cannot must be
    rejected, and blamed on the pack."""
    frame, drag = baseline
    scen = cfg.scenario("calm_warm")
    heavy = 3.2  # kg: ~31 N hover thrust, beyond the pack's ~820 W ceiling
    res = simulate_scenario(heavy, drag, rotor, scen, cfg.mission, cfg.rain,
                            battery=cfg.platform.battery)
    assert not res.valid
    # sustained-saturation kill or thrust-limited divergence, blamed on the pack
    assert "battery pack" in (res.failure_reason or "")

    # sanity: with an ideal pack (limits disabled) the same mass either flies
    # or fails for a NON-pack reason
    ideal = dataclasses.replace(cfg.platform.battery,
                                internal_resistance_ohm=0.0,
                                max_current_a=math.inf)
    res2 = simulate_scenario(heavy, drag, rotor, scen, cfg.mission, cfg.rain,
                             battery=ideal)
    assert "battery pack" not in (res2.failure_reason or "")
