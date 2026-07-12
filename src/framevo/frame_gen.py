"""Genome -> parametric frame: watertight mesh, mass/CG, hard validity checks.

Body axes: x forward, y left, z up, origin at body center. Arms attach at the
body outline at mid-height and carry a motor pad at the tip; the rotor disk
sits just above the pad.

Invalid genomes (battery does not fit, rotor clearance violated, ...) are
still meshed when geometrically possible -- the failures are instructive and
their STLs are archived with an _INVALID suffix -- but they are never
simulated: fitness = infinity.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import trimesh

from .config import Platform
from .genome import Genome
from .meshutil import (extrude_convex_polygon, polygon_area, polygon_properties,
                       rounded_rect, superellipse_section, sweep_section, union)

ROTOR_Z_ABOVE_TIP = 0.022  # motor stack height between arm tip and rotor plane


@dataclass
class ArmProperties:
    length: float
    root_area: float          # cross-section area at the root
    root_i_bend: float        # second moment for vertical bending, at the root
    root_height: float        # section height (stress fiber distance = h/2)
    mass: float               # one arm, solid CF (incl. motor pad)
    planform_width_mean: float


@dataclass
class FrameModel:
    genome: Genome
    valid: bool
    failure_reason: str | None
    mesh: trimesh.Trimesh | None
    arms_mesh: trimesh.Trimesh | None
    body_mesh: trimesh.Trimesh | None
    frame_mass: float
    total_mass: float
    cg: np.ndarray
    rotor_centers: np.ndarray  # (4, 3)
    arm: ArmProperties | None
    top_area_footprint: float  # plan-view body footprint area

    @property
    def hash(self) -> str:
        return self.genome.hash


def _dist_outside_rounded_rect(p: np.ndarray, length: float, width: float,
                               fillet: float) -> float:
    """Signed distance from a plan-view point to a rounded-rect boundary
    (positive outside)."""
    r = min(fillet, 0.49 * min(length, width))
    dx = abs(p[0]) - (length / 2.0 - r)
    dy = abs(p[1]) - (width / 2.0 - r)
    if dx <= 0.0 and dy <= 0.0:
        return max(dx, dy) - r  # inside
    return math.hypot(max(dx, 0.0), max(dy, 0.0)) - r


def build_frame(genome: Genome, platform: Platform, want_mesh: bool = True) -> FrameModel:
    g = genome.as_dict()
    bl, bw, bh = g["body_length"], g["body_width"], g["body_height"]
    fillet = g["body_fillet"]
    wall = platform.body_wall_base_m * g["thickness_scale"]
    failure: str | None = None

    # -- hard constraint: battery block (plus clearance) fits inside the shell
    batt = platform.battery
    c = batt.fit_clearance_m
    cavity = (bl - 2 * wall, bw - 2 * wall, bh - 2 * wall)
    if any(cav < need + 2 * c for cav, need in zip(cavity, batt.size_m)):
        failure = "battery does not fit body cavity"

    # -- hard constraint: flat top area for the 30.5 mm FC mount pattern
    flat = platform.fc_mount_flat_m
    if failure is None and (bl - 2 * fillet < flat or bw - 2 * fillet < flat):
        failure = "no flat area for flight-controller mount"

    # -- arm layout: front pair at +-sweep from x, rear pair mirrored
    sweep = math.radians(g["arm_sweep_deg"])
    dihedral = math.radians(g["arm_dihedral_deg"])
    azimuths = [sweep, -sweep, math.pi - sweep, -(math.pi - sweep)]
    arm_len = g["arm_length"]
    embed = 0.010  # arms plunge into the body so the union is one solid

    roots, tips, rotor_centers = [], [], []
    for az in azimuths:
        d = np.array([math.cos(az), math.sin(az)])
        # ray-rectangle intersection for the attach point on the body outline
        tx = (bl / 2.0) / abs(d[0]) if abs(d[0]) > 1e-9 else math.inf
        ty = (bw / 2.0) / abs(d[1]) if abs(d[1]) > 1e-9 else math.inf
        attach = d * min(tx, ty)
        root = np.array([*(attach - d * embed), 0.0])
        direction = np.array([d[0] * math.cos(dihedral), d[1] * math.cos(dihedral),
                              math.sin(dihedral)])
        tip = root + direction * (arm_len + embed)
        roots.append(root)
        tips.append(tip)
        rotor_centers.append(tip + np.array([0.0, 0.0,
                                             platform.motor_pad_height_m + ROTOR_Z_ABOVE_TIP]))
    rotor_centers_arr = np.array(rotor_centers)

    # -- hard constraint: rotor-rotor separation
    prop_d = platform.propulsion.prop_diameter_m
    clear = platform.rotor_tip_clearance_m
    if failure is None:
        for i in range(4):
            for j in range(i + 1, 4):
                if np.linalg.norm(rotor_centers_arr[i] - rotor_centers_arr[j]) \
                        < prop_d + clear:
                    failure = "rotor disks overlap (tip clearance)"
                    break
            if failure:
                break

    # -- hard constraint: rotor tip clearance from the body (plan view,
    # conservative: ignores any z offset from dihedral)
    if failure is None:
        for rc in rotor_centers:
            if _dist_outside_rounded_rect(rc[:2], bl, bw, fillet) \
                    < prop_d / 2.0 + clear:
                failure = "rotor too close to body"
                break

    # -- arm section properties (solid carbon fiber)
    section = superellipse_section(g["arm_width"], g["arm_height"], g["section_blend"])
    area, _, i_bend = polygon_properties(section)
    area = abs(area)
    taper = g["arm_taper"]
    rho = platform.material.density_kg_m3
    # linear scale 1 -> taper: volume = A_root * L * (1 + t + t^2)/3
    arm_volume = area * arm_len * (1.0 + taper + taper * taper) / 3.0
    pad_volume = math.pi * platform.motor_pad_radius_m ** 2 * platform.motor_pad_height_m
    arm_mass = (arm_volume + pad_volume) * rho
    arm_props = ArmProperties(
        length=arm_len, root_area=area, root_i_bend=abs(i_bend),
        root_height=g["arm_height"], mass=arm_mass,
        planform_width_mean=g["arm_width"] * (1.0 + taper) / 2.0,
    )

    # -- body shell mass (outer solid minus cavity)
    outer_poly = rounded_rect(bl, bw, fillet)
    inner_poly = rounded_rect(bl - 2 * wall, bw - 2 * wall, max(fillet - wall, 0.0))
    outer_area = abs(polygon_area(outer_poly))
    body_volume = outer_area * bh - abs(polygon_area(inner_poly)) * max(bh - 2 * wall, 0.0)
    body_mass = body_volume * rho

    frame_mass = body_mass + 4.0 * arm_mass
    total_mass = frame_mass + platform.fixed_mass_kg

    # -- CG (informative): body + battery + FC at origin, arms/motors outboard
    t = np.linspace(0.0, 1.0, 33)
    s2 = (1.0 + (taper - 1.0) * t) ** 2
    arm_centroid_frac = float(np.trapezoid(t * s2, t) / np.trapezoid(s2, t))
    moments = np.zeros(3)
    for root, tip, rc in zip(roots, tips, rotor_centers):
        arm_c = root + (tip - root) * arm_centroid_frac
        moments += arm_mass * arm_c + platform.propulsion.motor_mass_kg * rc
    cg = moments / total_mass

    # -- mesh (also for invalid genomes: their STLs are archived)
    mesh = arms_mesh = body_mesh = None
    if want_mesh:
        try:
            pitch = math.radians(g["body_pitch_deg"])
            rot = trimesh.transformations.rotation_matrix(-pitch, [0, 1, 0])
            body_mesh = extrude_convex_polygon(outer_poly, -bh / 2.0, bh / 2.0)
            body_mesh.apply_transform(rot)
            parts = []
            for root, tip in zip(roots, tips):
                parts.append(sweep_section(section, root, tip, taper))
                pad = trimesh.creation.cylinder(radius=platform.motor_pad_radius_m,
                                                height=platform.motor_pad_height_m,
                                                sections=16)
                pad.apply_translation(tip + [0.0, 0.0, platform.motor_pad_height_m / 2.0])
                parts.append(pad)
            arms_mesh = union(parts)
            mesh = union([body_mesh, arms_mesh])
            if failure is None and not mesh.is_watertight:
                failure = "mesh not watertight"
        except Exception:
            mesh = None
            if failure is None:
                failure = "mesh boolean union failed"

    return FrameModel(genome=genome, valid=failure is None, failure_reason=failure,
                      mesh=mesh, arms_mesh=arms_mesh, body_mesh=body_mesh,
                      frame_mass=frame_mass, total_mass=total_mass, cg=cg,
                      rotor_centers=rotor_centers_arr, arm=arm_props,
                      top_area_footprint=outer_area)
