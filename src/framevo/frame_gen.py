"""Genome -> parametric plate-deck frame: watertight mesh, mass/CG, hard
validity checks.

The construction follows the TBS Source One V6 assembly (the DroneAid kit's
frame archetype; baseline dimensions measured from the official 7in DC DXF in
data/source_one/):

  - bottom plate (2 mm class) with four flat plate arms whose ROOT TONGUES
    rest on it inside the deck sandwich, clamped by the standoff bolts
  - M3 standoffs to the top plate; the FC + 4-in-1 ESC stack sits in the gap
  - battery pack strapped on TOP of the top plate; the wedge gene tilts it
    about its front bottom edge (a real wedge mount -- it never sinks into
    the plate)
  - motor cans and prop disks are visual fixed components; the stack IS part
    of the bluff body for drag, wiring is visual only

Body axes: x forward, y left, z up, origin at the top surface of the bottom
plate. Invalid genomes are still meshed when geometrically possible (their
STLs are archived with an _INVALID suffix) but never simulated: fitness = inf.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import trimesh

from .config import Material, Platform
from .genome import Genome
from .meshutil import (extrude_convex_polygon, polygon_area, polygon_properties,
                       rounded_rect, superellipse_section, sweep_section, union)

ROTOR_Z_ABOVE_TIP = 0.030   # motor stack between arm tip and rotor plane
# root tongue inside the deck sandwich: long enough for an M3 clamp-bolt
# pair. (The real Source One uses ~22 mm interlocking notched tongues; we do
# not model notches, so tongues are shorter and must not touch.)
ARM_EMBED = 0.016
ROOT_GAP_MIN = 0.004        # clearance between adjacent root tongues (bolts)
STACK_SIZE = 0.0305         # FC / ESC board footprint
STACK_BOARD_T = 0.004
STACK_Z = (0.008, 0.016)    # board undersides above the bottom plate


@dataclass
class ArmProperties:
    length: float
    root_area: float          # cross-section area at the root
    root_i_bend: float        # second moment for vertical bending, at the root
    root_height: float        # section height (stress fiber distance = h/2)
    mass: float               # one arm, solid, incl. motor pad
    planform_width_mean: float


@dataclass
class FrameModel:
    genome: Genome
    valid: bool
    failure_reason: str | None
    mesh: trimesh.Trimesh | None        # the FRAME only (deck + arms): the STL
    arms_mesh: trimesh.Trimesh | None
    body_mesh: trimesh.Trimesh | None   # deck + battery + stack: bluff body (aero)
    # labeled visual parts for colored renders/viewers. Keys: deck, arms
    # (evolved geometry); battery, stack, wiring, motors, props (fixed
    # platform). Motors/props/wiring never enter the drag rasterization.
    parts: dict[str, trimesh.Trimesh | None]
    frame_mass: float
    total_mass: float
    cg: np.ndarray
    rotor_centers: np.ndarray  # (4, 3)
    arm: ArmProperties | None
    material: Material
    top_area_footprint: float  # plan-view deck/battery footprint area

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
    bl, bw = g["body_length"], g["body_width"]       # deck plate footprint
    gap = g["body_height"]                            # standoff height
    fillet = g["body_fillet"]
    plate_t = platform.plate_base_m * g["thickness_scale"]
    material = platform.material_for(g["material"])
    batt = platform.battery
    batt_l, batt_w, batt_h = batt.size_m
    arm_h = g["arm_height"]
    failure: str | None = None

    # -- hard constraint: FC/ESC stack and arm tongues must fit in the gap
    if gap < platform.fc_stack_height_m or gap < arm_h + platform.fc_stack_height_m / 2:
        failure = "deck gap too small for stack + arm tongues"

    # -- hard constraint: the top plate must carry the battery pack
    if failure is None and (bl < batt.support_frac * batt_l
                            or bw < batt.support_frac * batt_w):
        failure = "top plate too small to support battery"

    # -- hard constraint: flat plate area for the 30.5 mm FC mount pattern
    flat = platform.fc_mount_flat_m
    if failure is None and (bl - 2 * fillet < flat or bw - 2 * fillet < flat):
        failure = "no flat area for flight-controller mount"

    # -- arm layout: front pair at +-sweep from x, rear pair mirrored.
    # Root tongues rest ON the bottom plate (inside the sandwich).
    sweep = math.radians(g["arm_sweep_deg"])
    dihedral = math.radians(g["arm_dihedral_deg"])
    azimuths = [sweep, -sweep, math.pi - sweep, -(math.pi - sweep)]
    arm_len = g["arm_length"]
    arm_z = arm_h / 2.0

    roots, tips, attaches, rotor_centers = [], [], [], []
    for az in azimuths:
        d = np.array([math.cos(az), math.sin(az)])
        # ray-rectangle intersection for the attach point on the deck outline
        tx = (bl / 2.0) / abs(d[0]) if abs(d[0]) > 1e-9 else math.inf
        ty = (bw / 2.0) / abs(d[1]) if abs(d[1]) > 1e-9 else math.inf
        attach = d * min(tx, ty)
        attaches.append(attach)
        root = np.array([*(attach - d * ARM_EMBED), arm_z])
        direction = np.array([d[0] * math.cos(dihedral), d[1] * math.cos(dihedral),
                              math.sin(dihedral)])
        tip = root + direction * (arm_len + ARM_EMBED)
        roots.append(root)
        tips.append(tip)
        rotor_centers.append(tip + np.array([0.0, 0.0,
                                             platform.motor_pad_height_m + ROTOR_Z_ABOVE_TIP]))
    rotor_centers_arr = np.array(rotor_centers)

    # -- hard constraint: root tongues must not collide inside the sandwich
    # (each needs clamp-bolt room; unlike the real Source One we do not model
    # interlocking notches, so tongues may not cross at the center either)
    if failure is None:
        min_gap = g["arm_width"] + ROOT_GAP_MIN
        root_ends = [a - (a / np.linalg.norm(a)) * ARM_EMBED for a in attaches]
        for i in range(4):
            for j in range(i + 1, 4):
                if np.linalg.norm(attaches[i] - attaches[j]) < min_gap \
                        or np.linalg.norm(root_ends[i] - root_ends[j]) < min_gap:
                    failure = "arm root tongues overlap in the deck"
                    break
            if failure:
                break

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

    # -- hard constraint: rotor tip clearance from deck AND battery, each
    # checked against its own footprint (plan view; conservative about the
    # z offset from dihedral)
    if failure is None:
        need = prop_d / 2.0 + clear
        for rc in rotor_centers:
            if _dist_outside_rounded_rect(rc[:2], bl, bw, fillet) < need:
                failure = "rotor too close to deck"
                break
            if _dist_outside_rounded_rect(rc[:2], batt_l, batt_w, 0.0) < need:
                failure = "rotor too close to battery"
                break

    # -- arm section properties (solid print/plate material)
    section = superellipse_section(g["arm_width"], arm_h, g["section_blend"])
    area, _, i_bend = polygon_properties(section)
    area = abs(area)
    taper = g["arm_taper"]
    rho = material.density_kg_m3
    # linear scale 1 -> taper: volume = A_root * L * (1 + t + t^2)/3,
    # plus the constant-section root tongue inside the sandwich
    arm_volume = area * arm_len * (1.0 + taper + taper * taper) / 3.0 \
        + area * ARM_EMBED
    pad_volume = math.pi * platform.motor_pad_radius_m ** 2 * platform.motor_pad_height_m
    arm_mass = (arm_volume + pad_volume) * rho
    arm_props = ArmProperties(
        length=arm_len, root_area=area, root_i_bend=abs(i_bend),
        root_height=arm_h, mass=arm_mass,
        planform_width_mean=g["arm_width"] * (1.0 + taper) / 2.0,
    )

    # -- deck mass: two plates + four standoffs
    plate_poly = rounded_rect(bl, bw, fillet)
    plate_area = abs(polygon_area(plate_poly))
    deck_mass = 2.0 * plate_area * plate_t * rho \
        + 4.0 * gap * platform.standoff_mass_per_m

    frame_mass = deck_mass + 4.0 * arm_mass
    total_mass = frame_mass + platform.fixed_mass_kg

    # -- CG (informative)
    t_ = np.linspace(0.0, 1.0, 33)
    s2 = (1.0 + (taper - 1.0) * t_) ** 2
    arm_centroid_frac = float(np.trapezoid(t_ * s2, t_) / np.trapezoid(s2, t_))
    batt_z = gap + plate_t + batt_h / 2.0  # battery rides on the top plate
    moments = np.array([0.0, 0.0, batt.mass_kg * batt_z
                        + plate_area * plate_t * rho * (gap + plate_t / 2.0)])
    for root, tip, rc in zip(roots, tips, rotor_centers):
        arm_c = root + (tip - root) * arm_centroid_frac
        moments += arm_mass * arm_c + platform.propulsion.motor_mass_kg * rc
    cg = moments / total_mass

    # -- mesh (also for invalid genomes: their STLs are archived)
    mesh = arms_mesh = body_mesh = None
    parts: dict[str, trimesh.Trimesh | None] = {
        "deck": None, "arms": None, "battery": None, "stack": None,
        "wiring": None, "motors": None, "props": None}
    if want_mesh:
        try:
            deck_solids = []
            bottom = extrude_convex_polygon(plate_poly, -plate_t, 0.0)
            top = extrude_convex_polygon(plate_poly, gap, gap + plate_t)
            deck_solids += [bottom, top]
            sx = bl / 2.0 - max(fillet, 0.008)
            sy = bw / 2.0 - max(fillet, 0.008)
            for px, py in ((sx, sy), (-sx, sy), (-sx, -sy), (sx, -sy)):
                s = trimesh.creation.cylinder(radius=platform.standoff_radius_m,
                                              height=gap + plate_t, sections=10)
                s.apply_translation([px, py, gap / 2.0])
                deck_solids.append(s)
            deck_mesh = union(deck_solids)

            # battery wedge: hinged at its FRONT bottom edge so the rear
            # lifts -- the pack never sinks through the plate
            battery_box = trimesh.creation.box((batt_l, batt_w, batt_h))
            pitch = math.radians(g["body_pitch_deg"])
            if pitch > 1e-9:
                rot = trimesh.transformations.rotation_matrix(
                    pitch, [0, 1, 0], [batt_l / 2.0, 0.0, -batt_h / 2.0])
                battery_box.apply_transform(rot)
            battery_box.apply_translation([0.0, 0.0, batt_z])

            # FC + 4-in-1 ESC boards inside the deck gap (a real bluff body
            # between the plates -> included in the drag mesh)
            stack_solids = []
            for z0 in STACK_Z:
                board = trimesh.creation.box((STACK_SIZE, STACK_SIZE, STACK_BOARD_T))
                board.apply_translation([0.0, 0.0, z0 + STACK_BOARD_T / 2.0])
                stack_solids.append(board)
            stack_mesh = union(stack_solids)

            # wiring (visual only): XT60 block on the top plate rear + cable
            xt60 = trimesh.creation.box((0.016, 0.009, 0.009))
            xt60.apply_translation([-bl / 2.0 + 0.010, 0.0,
                                    gap + plate_t + 0.0045])
            cable = trimesh.creation.cylinder(
                radius=0.002,
                segment=[[-0.005, 0.0, STACK_Z[1]],
                         [-bl / 2.0 - 0.006, 0.0, gap + plate_t + 0.004]])
            wiring_mesh = union([xt60, cable])

            arm_solids = []
            for root, tip in zip(roots, tips):
                arm_solids.append(sweep_section(section, root, tip, taper))
                pad = trimesh.creation.cylinder(radius=platform.motor_pad_radius_m,
                                                height=platform.motor_pad_height_m,
                                                sections=16)
                pad.apply_translation(tip + [0.0, 0.0, platform.motor_pad_height_m / 2.0])
                arm_solids.append(pad)
            arms_mesh = union(arm_solids)

            # visual-only fixed components: motor cans + thin prop disks
            motor_solids, prop_solids = [], []
            for tip, rc in zip(tips, rotor_centers):
                motor = trimesh.creation.cylinder(
                    radius=platform.motor_body_radius_m,
                    height=platform.motor_body_height_m, sections=14)
                motor.apply_translation(
                    tip + [0.0, 0.0, platform.motor_pad_height_m
                           + platform.motor_body_height_m / 2.0])
                motor_solids.append(motor)
                disk = trimesh.creation.cylinder(
                    radius=platform.propulsion.prop_diameter_m / 2.0,
                    height=0.0022, sections=28)
                disk.apply_translation(rc)
                prop_solids.append(disk)

            parts = {"deck": deck_mesh, "arms": arms_mesh,
                     "battery": battery_box, "stack": stack_mesh,
                     "wiring": wiring_mesh,
                     "motors": union(motor_solids),
                     "props": union(prop_solids)}
            body_mesh = union([deck_mesh, battery_box, stack_mesh])  # aero
            mesh = union([deck_mesh, arms_mesh])                     # the STL
            if failure is None and not mesh.is_watertight:
                failure = "mesh not watertight"
        except Exception:
            mesh = None
            if failure is None:
                failure = "mesh boolean union failed"

    return FrameModel(genome=genome, valid=failure is None, failure_reason=failure,
                      mesh=mesh, arms_mesh=arms_mesh, body_mesh=body_mesh,
                      parts=parts,
                      frame_mass=frame_mass, total_mass=total_mass, cg=cg,
                      rotor_centers=rotor_centers_arr, arm=arm_props,
                      material=material,
                      top_area_footprint=max(plate_area, batt_l * batt_w))


def export_printable_parts(genome: Genome, platform: Platform,
                           out_dir) -> list[str]:
    """The individual frame pieces, each flat in print/cut orientation:
    bottom_plate.stl, top_plate.stl, arm.stl (x4 identical). Units: meters.
    Bolt holes are not modeled (see README limitations)."""
    from pathlib import Path

    g = genome.as_dict()
    plate_t = platform.plate_base_m * g["thickness_scale"]
    poly = rounded_rect(g["body_length"], g["body_width"], g["body_fillet"])
    section = superellipse_section(g["arm_width"], g["arm_height"],
                                   g["section_blend"])
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, solid in (
        ("bottom_plate", extrude_convex_polygon(poly, 0.0, plate_t)),
        ("top_plate", extrude_convex_polygon(poly, 0.0, plate_t)),
        ("arm", sweep_section(section,
                              np.array([0.0, 0.0, g["arm_height"] / 2.0]),
                              np.array([g["arm_length"] + ARM_EMBED, 0.0,
                                        g["arm_height"] / 2.0]),
                              g["arm_taper"])),
    ):
        p = out / f"{name}.stl"
        solid.export(p)
        written.append(str(p))
    return written
