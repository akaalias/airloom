"""Arm structural integrity: constraint, not objective.

Station-by-station variable-section bending along the REAL morphed arm
outline, cantilevered at the tongue end (deck clamp edge) and loaded at the
tip by the worst-case per-rotor thrust seen across ALL scenarios, times a
safety factor. At each station:

  net width = shell width minus any hole/cutout crossing that station
  (bolt holes fall outside the shaft span and never contribute; lightening
  holes from genome.arm_cutout_scale do), with a Peterson net-section
  stress-concentration factor (Kt = 2 + (1 - d/w)^3, the tension form,
  conservative for plate bending) applied wherever a feature pierces the
  section; local thickness follows the genome.tip_thickness_scale bump
  profile (full at the tongue and motor mount, thinnest mid-shaft).

Checks:
  1. max bending stress across all stations <= material tensile strength
     (datasheet -- the as-built print-strength knockdown stays a
     verify-champions-only refinement, not a hard loop gate)
  2. tip deflection (integrated over the real I(x)) <= 5% of arm length
  3. first bending natural frequency (tip mass = motor + effective arm
     mass, 0.243 m_arm per Rayleigh, root-station stiffness) outside
     +-15% of the hover rotor frequency (1P)

Promoted 2026-07-24 from a single-root-section model to this one: once the
genome could taper thickness or pierce the shaft with lightening holes, a
root-only check stopped being merely conservative -- stress isn't
guaranteed monotonic in x once both the bending moment and the local
thickness vary along the arm, so the in-loop gate needed the same
station-by-station model `verify-champions` already used post-hoc.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .config import Material, Platform
from .realgeo import ArmOutline

STATION_STEP_MM = 0.5
SLAB_MM = 0.75          # half-width of the sampling slab around a station


@dataclass(frozen=True)
class Station:
    x_mm: float
    w_gross_mm: float
    w_net_mm: float
    removed_mm: float     # summed hole/cutout chord at this station
    kt: float
    moment_nm: float
    stress_pa: float      # Kt * M c / I_net


@dataclass(frozen=True)
class ArmVerdict:
    stations: tuple[Station, ...]
    p_tip_n: float                # applied load (peak thrust x SF)
    x_crit_mm: float
    stress_max_pa: float
    kt_crit: float
    feature_crit: str             # "hole/cutout" | "plain section"
    strength_as_built_pa: float
    margin: float                 # as-built strength / peak refined stress
    margin_naive: float           # datasheet strength / root beam stress
                                   # (no Kt) -- what a root-only check sees
    tip_deflection_m: float
    deflection_limit_m: float
    predicted_failure_load_n: float


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


def _extents_at(pts: np.ndarray, x: float, slab: float = SLAB_MM) -> float:
    ys = pts[np.abs(pts[:, 0] - x) < slab][:, 1]
    return float(ys.max() - ys.min()) if len(ys) > 1 else 0.0


def _densify(poly: np.ndarray, step: float = 0.7) -> np.ndarray:
    out = []
    for a, b in zip(poly, np.roll(poly, -1, axis=0)):
        n = max(int(np.linalg.norm(b - a) / step), 1)
        out += [a + (b - a) * t for t in np.linspace(0, 1, n, endpoint=False)]
    return np.array(out)


def analyze_arm(arm: ArmOutline, thickness_m: float, material: Material,
                p_tip_n: float, max_tip_deflection_frac: float = 0.05,
                tip_thickness_scale: float = 1.0) -> ArmVerdict:
    """Refined bending check of one (morphed) arm under a tip load at the
    motor axis, cantilevered at the tongue end (deck clamp edge).

    `tip_thickness_scale` < 1.0 dips local thickness mid-shaft (bump
    profile: full at the tongue and at the motor mount) -- see
    genome.py's tip_thickness_scale and realgeo.extrude_tapered, which
    build the matching geometry."""
    shell = _densify(arm.shell)
    cut_pts = [_densify(c) for c in arm.cutouts]
    x_root, x_mount = arm.tongue_end, arm.mount_start
    x_tip = arm.motor_xy[0]
    shaft = x_mount - x_root
    e_mod = material.youngs_modulus_pa

    def thickness_at(x: float) -> float:
        if shaft <= 0 or tip_thickness_scale >= 1.0:
            return thickness_m
        s = min(max((x - x_root) / shaft, 0.0), 1.0)
        bump = math.sin(math.pi * s) ** 2
        return thickness_m * (1.0 - (1.0 - tip_thickness_scale) * bump)

    xs = np.arange(x_root + 0.5, x_mount - 0.25, STATION_STEP_MM)
    if len(xs) == 0:  # a pathologically short shaft: still analyze one point
        xs = np.array([0.5 * (x_root + x_mount)])
    stations: list[Station] = []
    inv_ei = []  # 1/EI per station, for the deflection integral
    for x in xs:
        w_gross = _extents_at(shell, x)
        if w_gross <= 0.0:
            continue
        removed = 0.0
        for hx, _hy, r in arm.holes:
            if abs(x - hx) < r:
                removed += 2.0 * math.sqrt(r * r - (x - hx) ** 2)
        for cp in cut_pts:
            if cp[:, 0].min() - SLAB_MM < x < cp[:, 0].max() + SLAB_MM:
                removed += _extents_at(cp, x)
        w_net = max(w_gross - removed, 0.3)  # never a zero-width section
        d_over_w = min(removed / w_gross, 0.95)
        kt = 2.0 + (1.0 - d_over_w) ** 3 if removed > 0.2 else 1.0

        t = thickness_at(float(x))
        m_nm = p_tip_n * (x_tip - x) * 1e-3
        w_net_m = w_net * 1e-3
        i_net = w_net_m * t ** 3 / 12.0
        stress = kt * m_nm * (t / 2.0) / i_net
        stations.append(Station(float(x), w_gross, w_net, removed, kt,
                                m_nm, stress))
        inv_ei.append(1.0 / (e_mod * w_net_m * t ** 3 / 12.0))

    crit = max(stations, key=lambda s: s.stress_pa)
    feature = "hole/cutout" if crit.removed_mm > 0.2 else "plain section"
    strength_built = material.tensile_strength_pa * material.as_built_strength_frac

    # unit-load deflection integral over the flexible shaft (tongue and
    # motor-mount zones treated as rigid): delta = int M(x)^2 / (EI P) dx
    dx_m = STATION_STEP_MM * 1e-3
    defl = sum(s.moment_nm ** 2 * ie for s, ie in zip(stations, inv_ei)) \
        * dx_m / p_tip_n
    arm_len_m = (x_tip - x_root) * 1e-3

    # naive view = a root-only check: root station, no Kt, datasheet strength
    root = stations[0]
    naive_stress = root.stress_pa / root.kt
    return ArmVerdict(
        stations=tuple(stations), p_tip_n=p_tip_n,
        x_crit_mm=crit.x_mm, stress_max_pa=crit.stress_pa, kt_crit=crit.kt,
        feature_crit=feature, strength_as_built_pa=strength_built,
        margin=strength_built / crit.stress_pa,
        margin_naive=material.tensile_strength_pa / naive_stress,
        tip_deflection_m=defl,
        deflection_limit_m=max_tip_deflection_frac * arm_len_m,
        predicted_failure_load_n=p_tip_n * strength_built / crit.stress_pa)


def check_structure(arm: ArmOutline, thickness_m: float,
                    tip_thickness_scale: float, arm_mass_kg: float,
                    peak_rotor_thrust: float, hover_rotor_hz: float,
                    platform: Platform, mat: Material) -> StructResult:
    p = peak_rotor_thrust * platform.safety_factor
    v = analyze_arm(arm, thickness_m, mat, p, platform.max_tip_deflection_frac,
                    tip_thickness_scale=tip_thickness_scale)
    arm_len_m = (arm.motor_xy[0] - arm.tongue_end) * 1e-3
    stress, defl = v.stress_max_pa, v.tip_deflection_m

    # resonance: Rayleigh estimate off the root station's stiffness (the
    # stiffest point on the arm, thickness unaffected by the taper there
    # by construction -- see thickness_at's bump profile). A documented
    # approximation: resonance is a secondary check, and a full
    # stiffness-weighted I(x) integral isn't worth the complexity here.
    root = v.stations[0]
    i_root = root.w_net_mm * 1e-3 * thickness_m ** 3 / 12.0
    f1 = first_bending_frequency(arm_len_m, mat.youngs_modulus_pa, i_root,
                                 platform.propulsion.motor_mass_kg, arm_mass_kg)

    if stress > mat.tensile_strength_pa:
        return StructResult(False, f"arm overstressed ({mat.name})", stress, defl, f1)
    if defl > platform.max_tip_deflection_frac * arm_len_m:
        return StructResult(False, f"arm tip deflection ({mat.name})", stress, defl, f1)
    if hover_rotor_hz > 0.0 and \
            abs(f1 - hover_rotor_hz) / hover_rotor_hz < platform.resonance_band_frac:
        return StructResult(False, "arm resonance with rotor 1P", stress, defl, f1)
    return StructResult(True, None, stress, defl, f1)
