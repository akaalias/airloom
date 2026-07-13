"""Genome -> a complete, real Source One V6-derived drone assembly.

Every structural part is the official plate outline (data/source_one/),
morphed by the genome under zone constraints (realgeo.py); every component
is a dimension-accurate model of the actual kit hardware (components.py):
21700 cell pack, FC/ESC stack, 2806 motors, 3-blade props, camera, VTX and
ELRS antennas, GPS, XT60 and routed wiring looms.

Assembly (z up, x forward, origin at the main plate top surface):
  main plate [ -tp, 0 ] -> arm tongues on it [0, ta] -> mid plate clamps
  them [ta, ta+tp] -> standoffs (deck_gap) -> top plate; the FC/ESC stack
  lives in the gap; the battery is strapped on the top plate (wedge gene);
  camera at the nose, antennas + GPS at the tail.

Invalid genomes are still meshed when possible (their STLs are archived
with an _INVALID suffix) but never simulated: fitness = inf.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import trimesh

from . import components as comp
from .config import Material, Platform
from .genome import Genome
from .realgeo import (STOCK_ANCHORS, ArmOutline, extrude, load_outlines,
                      mirror_y, morph_arm, morph_plate, shaft_min_width)

MOTOR_H = 0.026            # motor stack height above the arm mount
STACK_H = 0.0216           # FC + ESC stack height inside the gap
STANDOFF_R = 0.0025
MAX_TONGUE_OVERLAP_MM2 = 1.0


@dataclass
class ArmProperties:
    length: float             # cantilever length: tongue end -> motor axis
    root_area: float          # shaft cross-section area (min width x t)
    root_i_bend: float        # second moment for vertical bending
    root_height: float        # plate thickness (stress fiber = t/2)
    mass: float               # one arm
    planform_width_mean: float


@dataclass
class FrameModel:
    genome: Genome
    valid: bool
    failure_reason: str | None
    mesh: trimesh.Trimesh | None        # the FRAME plates+arms (the STL)
    arms_mesh: trimesh.Trimesh | None
    body_mesh: trimesh.Trimesh | None   # everything else that meets the wind
    parts: dict[str, trimesh.Trimesh | None]
    frame_mass: float
    total_mass: float
    cg: np.ndarray
    rotor_centers: np.ndarray  # (4, 3)
    arm: ArmProperties | None
    material: Material
    top_area_footprint: float

    @property
    def hash(self) -> str:
        return self.genome.hash


def _tongue_region(outline: ArmOutline, az: float, t_m) -> np.ndarray:
    """The tongue's occupancy rectangle in world mm (for clamp coverage)."""
    c, s = math.cos(az), math.sin(az)
    hw = outline.width / 2.0 + 2.0
    corners = np.array([[0.0, -hw], [outline.tongue_end, -hw],
                        [outline.tongue_end, hw], [0.0, hw]])
    tx, ty = 1e3 * t_m[0], 1e3 * t_m[1]
    return np.column_stack([tx + corners[:, 0] * c - corners[:, 1] * s,
                            ty + corners[:, 0] * s + corners[:, 1] * c])


def _rot_z(mesh: trimesh.Trimesh, angle: float) -> trimesh.Trimesh:
    mesh.apply_transform(trimesh.transformations.rotation_matrix(angle, [0, 0, 1]))
    return mesh


def _try_union(parts: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    try:
        return trimesh.boolean.union(parts, engine="manifold")
    except Exception:
        return trimesh.util.concatenate(parts)


def build_frame(genome: Genome, platform: Platform, want_mesh: bool = True) -> FrameModel:
    g = genome.as_dict()
    material = platform.material_for(g["material"])
    rho = material.density_kg_m3
    outlines = load_outlines(str(platform.propulsion.uiuc_data_dir.parent / "source_one"))
    batt = platform.battery
    batt_l, batt_w, batt_h = batt.size_m
    failure: str | None = None

    tp = platform.plate_base_m * g["plate_thickness_scale"]
    ta = g["arm_thickness"]
    gap = g["deck_gap"]
    top_z = ta + tp + gap  # underside of the top plate

    # -- morph the real outlines
    arm_front = morph_arm(outlines["arm_front"], g["arm_length_scale"],
                          g["arm_width_scale"], g["arm_waist_scale"])
    arm_rear = morph_arm(outlines["arm_rear"], g["arm_length_scale"],
                         g["arm_width_scale"], g["arm_waist_scale"])
    sx, sy = g["plate_length_scale"], g["plate_width_scale"]
    p_main = morph_plate(outlines["plate_main"], sx, sy)
    p_mid = morph_plate(outlines["plate_mid"], sx, sy)
    p_top = morph_plate(outlines["plate_top"], sx, sy)

    # -- hard constraint: the FC/ESC stack must fit in the gap
    if gap < STACK_H + 0.001:
        failure = "deck gap too small for FC/ESC stack"

    # -- arm placement at the drawing-derived plate anchors; anchors scale
    # with the plate morph, sweep genes rotate each arm about its anchor.
    # Left/right arms are mirrored chirality like the real DC parts.
    az_f = math.radians(g["front_sweep_deg"])
    az_r = math.pi - math.radians(g["rear_sweep_deg"])
    tfx, tfy = STOCK_ANCHORS["front"][1]
    trx, try_ = STOCK_ANCHORS["rear"][1]
    scale = np.array([sx, sy]) * 1e-3
    arms_spec = [  # (outline, azimuth, anchor T in meters)
        (arm_front, az_f, np.array([tfx, tfy]) * scale),
        (mirror_y(arm_front), -az_f, np.array([tfx, -tfy]) * scale),
        (mirror_y(arm_rear), az_r, np.array([trx, try_]) * scale),
        (arm_rear, -az_r, np.array([trx, -try_]) * scale),
    ]
    placements: list[tuple[ArmOutline, float, np.ndarray]] = list(arms_spec)
    rotor_centers = []
    rotor_z = ta + MOTOR_H
    for outline, az, t_m in placements:
        mx, my = outline.motor_xy
        c, s = math.cos(az), math.sin(az)
        rotor_centers.append([t_m[0] + 1e-3 * (mx * c - my * s),
                              t_m[1] + 1e-3 * (mx * s + my * c), rotor_z])
    rotor_centers_arr = np.array(rotor_centers)

    # -- hard constraints on the REAL 2D geometry: placed arm outlines must
    # not overlap each other (no notch redesign is modeled), and every
    # tongue bolt must land on the main plate
    if failure is None:
        from shapely import affinity
        from shapely.geometry import Point, Polygon as ShPoly
        placed = []
        for outline, az, t_m in placements:
            poly = affinity.rotate(ShPoly(outline.shell), math.degrees(az),
                                   origin=(0, 0))
            poly = affinity.translate(poly, 1e3 * t_m[0], 1e3 * t_m[1])
            placed.append(poly)
        for i in range(4):
            for j in range(i + 1, 4):
                if placed[i].intersection(placed[j]).area > MAX_TONGUE_OVERLAP_MM2:
                    failure = "arm root tongues collide on the main plate"
                    break
            if failure:
                break
        if failure is None:
            # each arm is held by its tongue bolt pair: both bolts must land
            # on main-plate material with >= 2.5 mm edge margin (bolt holes
            # are re-cut with the plates, which regenerate per candidate)
            plate_clamp = ShPoly(p_main.shell).buffer(-2.5)
            for outline, az, t_m in placements:
                bolts = [h for h in outline.holes
                         if h[0] < outline.tongue_end and h[2] < 1.6]
                c, s = math.cos(az), math.sin(az)
                for bx, by, _ in bolts:
                    wx = 1e3 * t_m[0] + bx * c - by * s
                    wy = 1e3 * t_m[1] + bx * s + by * c
                    if not plate_clamp.contains(Point(wx, wy)):
                        failure = "arm tongue bolts miss the main plate"
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

    # -- hard constraint: rotor clearance from battery and top plate.
    # 3D-aware: the horizontal check applies only when the prop plane is
    # within a 5 mm safety band of the obstacle's z-range (on the real V6
    # the rear props sweep below the top-plate corners with mm to spare --
    # the deck_gap gene trades that margin directly).
    if failure is None:
        need = prop_d / 2.0 + clear
        z_band = 0.005
        obstacles = (  # (length, width, z_lo, z_hi)
            (batt_l, batt_w, top_z + tp, top_z + tp + batt_h),
            (p_top.length * 1e-3, p_top.width * 1e-3, top_z, top_z + tp),
        )
        for rc in rotor_centers_arr:
            for ll, ww, z_lo, z_hi in obstacles:
                if rc[2] < z_lo - z_band or rc[2] > z_hi + z_band:
                    continue  # prop plane clears this obstacle vertically
                dx = max(abs(rc[0]) - ll / 2.0, 0.0)
                dy = max(abs(rc[1]) - ww / 2.0, 0.0)
                if math.hypot(dx, dy) < need:
                    failure = "rotor too close to deck/battery"
                    break
            if failure:
                break

    # -- structural section from the real morphed outline
    w_min = shaft_min_width(arm_front) * 1e-3
    i_bend = w_min * ta ** 3 / 12.0
    arm_len = (arm_front.motor_xy[0] - arm_front.tongue_end) * 1e-3

    # -- build the real part meshes
    mesh = arms_mesh = body_mesh = None
    parts: dict[str, trimesh.Trimesh | None] = {
        k: None for k in ("deck", "arms", "battery", "stack", "wiring",
                          "camera", "antennas", "motors", "props")}
    frame_mass = math.nan
    try:
        main_mesh = extrude(p_main, tp)
        main_mesh.apply_translation([0, 0, -tp])
        mid_mesh = extrude(p_mid, tp)
        mid_mesh.apply_translation([0, 0, ta])
        top_mesh = extrude(p_top, tp)
        top_mesh.apply_translation([0, 0, top_z])
        standoffs = []
        sx_off = 0.36 * p_mid.length * 1e-3
        sy_off = 0.30 * p_mid.width * 1e-3
        for px, py in ((sx_off, sy_off), (-sx_off, sy_off),
                       (-sx_off, -sy_off), (sx_off, -sy_off)):
            so = trimesh.creation.cylinder(radius=STANDOFF_R, height=gap, sections=12)
            so.apply_translation([px, py, ta + tp + gap / 2.0])
            standoffs.append(so)
        deck_mesh = _try_union([main_mesh, mid_mesh, top_mesh] + standoffs)

        arm_meshes = []
        for outline, az, t_m in placements:
            am = extrude(outline, ta)
            _rot_z(am, az)
            am.apply_translation([t_m[0], t_m[1], 0.0])
            arm_meshes.append(am)
        arms_mesh = _try_union(arm_meshes)

        # frame mass from the REAL volumes
        plate_vol = main_mesh.volume + mid_mesh.volume + top_mesh.volume
        arm_vol = sum(a.volume for a in arm_meshes)
        frame_mass = (plate_vol + arm_vol) * rho \
            + 4.0 * gap * platform.standoff_mass_per_m

        # -- fixed components, placed like the real build
        battery = comp.battery_pack()
        _rot_z(battery, math.pi / 2)  # long side along x
        wedge = math.radians(g["battery_wedge_deg"])
        if wedge > 1e-9:
            battery.apply_transform(trimesh.transformations.rotation_matrix(
                wedge, [0, 1, 0], [batt_l / 2.0, 0.0, 0.0]))
        battery.apply_translation([0, 0, top_z + tp])

        stack = comp.fc_stack()
        stack.apply_translation([0, 0, ta + tp])

        nose_x = p_top.length * 1e-3 / 2.0
        tail_x = -nose_x
        camera = comp.camera_micro()
        camera.apply_transform(trimesh.transformations.rotation_matrix(
            math.radians(-20), [0, 1, 0]))
        camera.apply_translation([nose_x - 0.006, 0, top_z + tp + 0.012])

        vtx = comp.vtx_antenna()
        vtx.apply_transform(trimesh.transformations.rotation_matrix(
            math.radians(135), [0, 1, 0]))
        vtx.apply_translation([tail_x + 0.004, 0.012, top_z + tp + 0.002])
        elrs = comp.elrs_dipole()
        elrs.apply_transform(trimesh.transformations.rotation_matrix(
            math.radians(150), [0, 1, 0]))
        elrs.apply_translation([tail_x + 0.006, -0.012, top_z + tp + 0.002])
        gps = comp.gps_puck()
        gps.apply_translation([tail_x + 0.030, 0, top_z + tp])
        antennas = trimesh.util.concatenate([vtx, elrs, gps])

        # -- wiring: motor looms along each arm, battery lead to the XT60,
        # camera + VTX coax
        looms = []
        for (outline, az, t_m), rc in zip(placements, rotor_centers_arr):
            base = np.array([rc[0], rc[1], ta + 0.002])
            mid = np.array([t_m[0] + 0.45 * (rc[0] - t_m[0]),
                            t_m[1] + 0.45 * (rc[1] - t_m[1]), ta + 0.004])
            inb = np.array([0.5 * t_m[0], 0.5 * t_m[1], ta + tp + 0.004])
            looms.append(comp.wire_bundle([base, mid, inb], n=3))
        xt = comp.xt60()
        xt.apply_translation([-0.030, batt_w / 2.0 - 0.004, top_z + tp + 0.006])
        lead = comp.wire([[-batt_l / 2.0 + 0.004, 0.008, top_z + tp + 0.012],
                          [-0.042, batt_w / 2.0 - 0.002, top_z + tp + 0.010],
                          [-0.036, batt_w / 2.0 - 0.004, top_z + tp + 0.006]],
                         radius=0.0016)
        cam_coax = comp.wire([[nose_x - 0.012, 0.004, top_z + tp + 0.008],
                              [nose_x - 0.030, 0.006, top_z - gap / 2.0],
                              [0.020, 0.008, ta + tp + 0.014]])
        vtx_coax = comp.wire([[tail_x + 0.006, 0.012, top_z + tp],
                              [tail_x + 0.020, 0.010, top_z - gap / 2.0],
                              [-0.020, 0.006, ta + tp + 0.014]])
        wiring = trimesh.util.concatenate(looms + [xt, lead, cam_coax, vtx_coax])

        motors_l, props_l = [], []
        for rc in rotor_centers_arr:
            m = comp.motor_2806()
            m.apply_translation([rc[0], rc[1], ta])
            motors_l.append(m)
            p = comp.propeller_7x4_3blade()
            p.apply_translation([rc[0], rc[1], rotor_z + 0.004])
            props_l.append(p)

        parts = {"deck": deck_mesh, "arms": arms_mesh, "battery": battery,
                 "stack": stack, "wiring": wiring, "camera": camera,
                 "antennas": antennas,
                 "motors": trimesh.util.concatenate(motors_l),
                 "props": trimesh.util.concatenate(props_l)}
        # aero bluff body: everything substantial the wind sees except arms
        # (own Cd class) and the spinning props (handled by the rotor
        # model). Antennas and wiring are omitted from the raster: <2% of
        # frontal area but thousands of triangles.
        body_mesh = trimesh.util.concatenate(
            [deck_mesh, battery, stack, camera, parts["motors"]])
        mesh = _try_union([deck_mesh, arms_mesh])
        if failure is None and not mesh.is_watertight:
            failure = "mesh not watertight"
    except Exception:
        if failure is None:
            failure = "real-geometry meshing failed"

    total_mass = (frame_mass if math.isfinite(frame_mass) else 0.0) \
        + platform.fixed_mass_kg
    arm_mass = (arm_vol * rho / 4.0) if math.isfinite(frame_mass) else 0.01
    arm_props = ArmProperties(
        length=arm_len, root_area=w_min * ta, root_i_bend=i_bend,
        root_height=ta, mass=arm_mass, planform_width_mean=w_min)

    # -- CG (informative)
    cg = np.zeros(3)
    if mesh is not None:
        moments = mesh.volume * rho * mesh.center_mass \
            + batt.mass_kg * np.array([0, 0, top_z + tp + batt_h / 2.0])
        for rc in rotor_centers_arr:
            moments = moments + platform.propulsion.motor_mass_kg * rc
        cg = moments / max(total_mass, 1e-9)

    return FrameModel(genome=genome, valid=failure is None, failure_reason=failure,
                      mesh=mesh, arms_mesh=arms_mesh, body_mesh=body_mesh,
                      parts=parts, frame_mass=frame_mass, total_mass=total_mass,
                      cg=cg, rotor_centers=rotor_centers_arr, arm=arm_props,
                      material=material,
                      top_area_footprint=max(p_top.length * p_top.width,
                                             batt_l * batt_w * 1e6) * 1e-6)


def export_printable_parts(genome: Genome, platform: Platform,
                           out_dir) -> list[str]:
    """The champion's individual pieces, flat in print/cut orientation --
    real morphed Source One outlines with their bolt holes and cutouts."""
    from pathlib import Path

    g = genome.as_dict()
    outlines = load_outlines(str(platform.propulsion.uiuc_data_dir.parent / "source_one"))
    tp = platform.plate_base_m * g["plate_thickness_scale"]
    sx, sy = g["plate_length_scale"], g["plate_width_scale"]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, solid in (
        ("arm_front", extrude(morph_arm(outlines["arm_front"], g["arm_length_scale"],
                                        g["arm_width_scale"], g["arm_waist_scale"]),
                              g["arm_thickness"])),
        ("arm_rear", extrude(morph_arm(outlines["arm_rear"], g["arm_length_scale"],
                                       g["arm_width_scale"], g["arm_waist_scale"]),
                             g["arm_thickness"])),
        ("plate_main", extrude(morph_plate(outlines["plate_main"], sx, sy), tp)),
        ("plate_mid", extrude(morph_plate(outlines["plate_mid"], sx, sy), tp)),
        ("plate_top", extrude(morph_plate(outlines["plate_top"], sx, sy), tp)),
    ):
        p = out / f"{name}.stl"
        solid.export(p)
        written.append(str(p))
    return written
