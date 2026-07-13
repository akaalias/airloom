"""Arm structural integrity: constraint, not objective.

Each arm is an Euler-Bernoulli cantilever loaded at the tip by the worst-case
per-rotor thrust seen across ALL scenarios, times a safety factor. Checks:

  1. max bending stress at the root <= material tensile strength
  2. tip deflection <= 5% of arm length
  3. first bending natural frequency (tip mass = motor + effective arm mass,
     0.243 m_arm per Rayleigh) outside +-15% of the hover rotor frequency (1P)
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from .config import Material, Platform
from .frame_gen import ArmProperties


@dataclass(frozen=True)
class StructResult:
    ok: bool
    reason: str | None
    max_stress_pa: float
    tip_deflection_m: float
    f1_hz: float


def cantilever_stress(p_tip: float, length: float, i_bend: float,
                      fiber: float) -> float:
    """Root bending stress for a tip point load: sigma = P L c / I."""
    return p_tip * length * fiber / i_bend


def cantilever_deflection(p_tip: float, length: float, e_mod: float,
                          i_bend: float) -> float:
    """Tip deflection: delta = P L^3 / (3 E I)."""
    return p_tip * length ** 3 / (3.0 * e_mod * i_bend)


def first_bending_frequency(length: float, e_mod: float, i_bend: float,
                            tip_mass: float, arm_mass: float) -> float:
    m_eff = tip_mass + 0.243 * arm_mass
    return math.sqrt(3.0 * e_mod * i_bend / (length ** 3 * m_eff)) / (2.0 * math.pi)


def check_structure(arm: ArmProperties, peak_rotor_thrust: float,
                    hover_rotor_hz: float, platform: Platform,
                    mat: Material) -> StructResult:
    p = peak_rotor_thrust * platform.safety_factor
    fiber = arm.root_height / 2.0
    stress = cantilever_stress(p, arm.length, arm.root_i_bend, fiber)
    defl = cantilever_deflection(p, arm.length, mat.youngs_modulus_pa, arm.root_i_bend)
    f1 = first_bending_frequency(arm.length, mat.youngs_modulus_pa,
                                 arm.root_i_bend,
                                 platform.propulsion.motor_mass_kg, arm.mass)
    if stress > mat.tensile_strength_pa:
        return StructResult(False, f"arm overstressed ({mat.name})", stress, defl, f1)
    if defl > platform.max_tip_deflection_frac * arm.length:
        return StructResult(False, f"arm tip deflection ({mat.name})", stress, defl, f1)
    if hover_rotor_hz > 0.0 and \
            abs(f1 - hover_rotor_hz) / hover_rotor_hz < platform.resonance_band_frac:
        return StructResult(False, "arm resonance with rotor 1P", stress, defl, f1)
    return StructResult(True, None, stress, defl, f1)
