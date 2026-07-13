"""Dimension-accurate 3D component library for a 7-inch Source One V6 build.

Every builder returns a single ``trimesh.Trimesh`` in its own LOCAL frame
(documented per function, Z up, all units meters) so assembly code can place
parts with plain rigid transforms. Solids are combined with a manifold
boolean union where possible so results stay watertight; if the union engine
rejects a shape we degrade gracefully to a plain concatenation, which still
renders and measures correctly.

Only numpy and trimesh are used -- no other framevo modules -- so this file
can be imported standalone (e.g. from the mesh-preview scripts).
"""
from __future__ import annotations

import numpy as np
import trimesh
from trimesh.transformations import rotation_matrix


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _union(parts: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    """Boolean-union parts (manifold engine), concatenating on failure."""
    if len(parts) == 1:
        return parts[0]
    try:
        return trimesh.boolean.union(parts, engine="manifold")
    except BaseException:
        return trimesh.util.concatenate(parts)


def _box(ex: float, ey: float, ez: float,
         at: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> trimesh.Trimesh:
    b = trimesh.creation.box(extents=[ex, ey, ez])
    b.apply_translation(at)
    return b


def _cyl(radius: float, height: float,
         at: tuple[float, float, float] = (0.0, 0.0, 0.0),
         axis: str = "z", sections: int = 32) -> trimesh.Trimesh:
    """Cylinder with its axis along x/y/z, CENTERED at ``at``."""
    c = trimesh.creation.cylinder(radius=radius, height=height,
                                  sections=sections)
    if axis == "x":
        c.apply_transform(rotation_matrix(np.pi / 2.0, [0, 1, 0]))
    elif axis == "y":
        c.apply_transform(rotation_matrix(np.pi / 2.0, [1, 0, 0]))
    c.apply_translation(at)
    return c


def _dome(radius_xy: float, radius_z: float,
          at: tuple[float, float, float]) -> trimesh.Trimesh:
    """Squashed icosphere (an ellipsoid) centered at ``at``."""
    s = trimesh.creation.icosphere(subdivisions=2, radius=1.0)
    s.apply_scale([radius_xy, radius_xy, radius_z])
    s.apply_translation(at)
    return s


def _loft(rings: np.ndarray) -> trimesh.Trimesh:
    """Skin a stack of equal-count vertex rings into a closed solid.

    ``rings`` is (n_rings, n_pts, 3). Adjacent rings are joined with quad
    walls split into triangles; both ends are capped with a triangle fan
    around the ring centroid, so the result is watertight by construction.
    """
    n_r, n_p, _ = rings.shape
    verts = rings.reshape(-1, 3)
    faces: list[list[int]] = []
    for i in range(n_r - 1):
        a, b = i * n_p, (i + 1) * n_p
        for j in range(n_p):
            k = (j + 1) % n_p
            faces.append([a + j, b + k, b + j])
            faces.append([a + j, a + k, b + k])
    c0, c1 = len(verts), len(verts) + 1
    verts = np.vstack([verts, rings[0].mean(axis=0), rings[-1].mean(axis=0)])
    e = (n_r - 1) * n_p
    for j in range(n_p):
        k = (j + 1) % n_p
        faces.append([c0, k, j])                      # start cap (reversed)
        faces.append([c1, e + j, e + k])              # end cap
    return trimesh.Trimesh(vertices=verts, faces=np.asarray(faces),
                           process=False)


# ---------------------------------------------------------------------------
# components
# ---------------------------------------------------------------------------

def battery_pack() -> trimesh.Trimesh:
    """6S1P pack of Molicel P45B 21700 cells in a 2x3 brick.

    Cells (d=0.0213, l=0.0703) lie on their sides, axes along y, arranged as
    3 columns along x and 2 layers along z, wrapped in four thin shrink-wrap
    slabs (the +-y ends stay open so the cell circles read), with a small
    BMS/lead-exit block on the -x end.

    Local frame: origin at the center of the brick's bottom face, z=0 at the
    bottom of the cells, pack length along y.
    """
    d, cell_len = 0.0213, 0.0703
    r = d / 2.0
    parts: list[trimesh.Trimesh] = []
    for col in (-1, 0, 1):                       # 3 columns along x
        for layer in (0, 1):                     # 2 layers along z
            parts.append(_cyl(r, cell_len, at=(col * d, 0.0, r + layer * d),
                              axis="y"))
    # shrink wrap: 4 thin slabs (+-x, +-z), 0.0005 proud of the cells, the
    # +-y faces are left open so the cell ends remain visible.
    hw_x = 1.5 * d + 0.0005                      # outer half-width in x
    top = 2.0 * d + 0.0005                       # outer top in z
    t = 0.0008                                   # wrap thickness
    parts.append(_box(2 * hw_x, cell_len, t, at=(0, 0, top - t / 2)))
    parts.append(_box(2 * hw_x, cell_len, t, at=(0, 0, -0.0005 + t / 2)))
    parts.append(_box(t, cell_len, top + 0.0005,
                      at=(hw_x - t / 2, 0, (top - 0.0005) / 2)))
    parts.append(_box(t, cell_len, top + 0.0005,
                      at=(-hw_x + t / 2, 0, (top - 0.0005) / 2)))
    # BMS / lead exit block, protruding 0.002 past the -x wall at mid-height
    parts.append(_box(0.012, 0.02, 0.006,
                      at=(-hw_x - 0.002 + 0.006, 0.0, d)))
    return _union(parts)


def fc_stack() -> trimesh.Trimesh:
    """FC + 4-in-1 ESC stack on a 30.5 mm mounting pattern.

    Two 36.5 mm square PCBs (1.6 mm thick) with their undersides at z=0.008
    and z=0.016, aluminum standoffs (r=0.0025) at the four pattern corners
    (+-0.01525) running from z=0 up between the boards, a low-ESR capacitor
    lying along x on the top board's +x edge, and a USB-C nub on its -x edge.

    Local frame: origin at the pattern center, z=0 at the bottom of the
    lower standoffs.
    """
    board, tb = 0.0365, 0.0016
    parts: list[trimesh.Trimesh] = []
    for z_bot in (0.008, 0.016):
        parts.append(_box(board, board, tb, at=(0, 0, z_bot + tb / 2)))
    for sx in (-1, 1):
        for sy in (-1, 1):
            x, y = sx * 0.01525, sy * 0.01525
            parts.append(_cyl(0.0025, 0.008, at=(x, y, 0.004)))       # below
            parts.append(_cyl(0.0025, 0.016 - 0.0096,
                              at=(x, y, (0.0096 + 0.016) / 2)))       # between
    # capacitor resting along the top board's +x edge, axis along x
    parts.append(_cyl(0.005, 0.012, at=(board / 2 - 0.007, 0.0,
                                        0.016 + tb + 0.005), axis="x"))
    # USB-C nub on the top board's -x edge
    parts.append(_box(0.003, 0.009, 0.0032,
                      at=(-board / 2 + 0.0015, 0.0, 0.016 + tb + 0.0016)))
    return _union(parts)


def motor_2806(kv_text: bool = False) -> trimesh.Trimesh:
    """2806.5 outrunner motor silhouette (~26-28 mm tall).

    Stator base disc with 4 mounting lugs, a narrower waist, the rotating
    bell with 12 raised vertical ribs, a slightly domed top cap, then the
    shaft stub and prop-nut hex. ``kv_text`` adds a thin raised band on the
    bell wall standing in for the printed KV marking.

    Local frame: origin at the center of the base, z=0 at the base bottom,
    shaft up along +z.
    """
    parts: list[trimesh.Trimesh] = []
    parts.append(_cyl(0.0148, 0.004, at=(0, 0, 0.002)))               # base
    for k in range(4):                                                # lugs
        a = np.deg2rad(45.0 + 90.0 * k)
        lug = _box(0.007, 0.005, 0.004, at=(0.0148, 0.0, 0.002))
        lug.apply_transform(rotation_matrix(a, [0, 0, 1]))
        parts.append(lug)
    parts.append(_cyl(0.010, 0.003, at=(0, 0, 0.0055)))               # waist
    bell_z0, bell_h = 0.007, 0.011
    parts.append(_cyl(0.0155, bell_h, at=(0, 0, bell_z0 + bell_h / 2)))
    for k in range(12):                                               # ribs
        a = 2.0 * np.pi * k / 12.0
        rib = _box(0.0012, 0.0018, bell_h - 0.002,
                   at=(0.0155, 0.0, bell_z0 + bell_h / 2))
        rib.apply_transform(rotation_matrix(a, [0, 0, 1]))
        parts.append(rib)
    if kv_text:
        parts.append(_cyl(0.0158, 0.0025, at=(0, 0, bell_z0 + bell_h - 0.003)))
    parts.append(_dome(0.0150, 0.0030, at=(0, 0, bell_z0 + bell_h)))  # cap
    parts.append(_cyl(0.0025, 0.004, at=(0, 0, 0.021 + 0.002)))       # shaft
    parts.append(_cyl(0.004, 0.004, at=(0, 0, 0.025 + 0.002),
                      sections=6))                                    # nut
    return _union(parts)


def propeller_7x4_3blade(pitch_deg: float = 12.0) -> trimesh.Trimesh:
    """3-blade 7x4 propeller (diameter 0.1778 m), lofted twisted blades.

    Each blade is skinned through cambered flat-plate airfoil sections at
    radius stations [0.012, 0.03, 0.05, 0.07, 0.0889] with chords
    [0.014, 0.019, 0.017, 0.013, 0.006], thickness 12% of chord, and a
    geometric twist tapering 28 deg (root) -> 8 deg (tip); ``pitch_deg``
    shifts the whole twist distribution relative to the 12-deg default.
    Blades are spaced 120 deg around a hub cylinder (r=0.007, h=0.007).

    Local frame: origin at the hub center, z=0 at mid-hub, rotation axis +z.
    """
    stations = np.array([0.012, 0.03, 0.05, 0.07, 0.0889])
    chords = np.array([0.014, 0.019, 0.017, 0.013, 0.006])
    twists = np.linspace(28.0, 8.0, len(stations)) + (pitch_deg - 12.0)
    # extra buried root station so the blade fuses into the hub
    stations = np.concatenate([[0.005], stations])
    chords = np.concatenate([[0.012], chords])
    twists = np.concatenate([[twists[0]], twists])

    n_pts = 18
    t = np.linspace(0.0, 2.0 * np.pi, n_pts, endpoint=False)
    rings = np.zeros((len(stations), n_pts, 3))
    for i, (rad, c, tw) in enumerate(zip(stations, chords, twists)):
        th = 0.12 * c
        yc = 0.5 * c * np.cos(t)                       # chordwise
        zc = 0.5 * th * np.sin(t)                      # thickness
        zc += 0.035 * c * (1.0 - (2.0 * yc / c) ** 2)  # slight camber
        a = np.deg2rad(tw)
        y = yc * np.cos(a) - zc * np.sin(a)
        z = yc * np.sin(a) + zc * np.cos(a)
        rings[i] = np.column_stack([np.full(n_pts, rad), y, z])
    blade = _loft(rings)

    parts = [_cyl(0.007, 0.007)]
    for k in range(3):
        b = blade.copy()
        b.apply_transform(rotation_matrix(2.0 * np.pi * k / 3.0, [0, 0, 1]))
        parts.append(b)
    return _union(parts)


def camera_micro() -> trimesh.Trimesh:
    """19 mm micro FPV camera: cube body, lens barrel and lens ring.

    Local frame: origin at the body-box center, lens axis along +x (barrel
    protrudes from the +x face).
    """
    parts = [_box(0.019, 0.019, 0.02)]
    parts.append(_cyl(0.007, 0.008, at=(0.019 / 2 + 0.004, 0, 0), axis="x"))
    parts.append(_cyl(0.0075, 0.002, at=(0.019 / 2 + 0.008 + 0.001, 0, 0),
                      axis="x"))
    return _union(parts)


def vtx_antenna() -> trimesh.Trimesh:
    """Stubby RHCP video antenna: SMA base, thin shaft, mushroom cap.

    Local frame: axis along +z, origin at the bottom of the SMA base.
    """
    parts = [_cyl(0.004, 0.008, at=(0, 0, 0.004))]
    parts.append(_cyl(0.0025, 0.030, at=(0, 0, 0.008 + 0.015)))
    parts.append(_cyl(0.008, 0.009, at=(0, 0, 0.038 + 0.0045)))
    parts.append(_dome(0.008, 0.004, at=(0, 0, 0.047)))   # rounded top
    return _union(parts)


def elrs_dipole() -> trimesh.Trimesh:
    """ELRS T-antenna: coax stem up +z, horizontal dipole bar along x.

    Local frame: origin at the bottom of the stem, dipole bar at z=0.04.
    """
    parts = [_cyl(0.0008, 0.04, at=(0, 0, 0.02), sections=12)]
    parts.append(_cyl(0.0012, 0.052, at=(0, 0, 0.04), axis="x", sections=12))
    for sx in (-1, 1):
        parts.append(_dome(0.0018, 0.0018, at=(sx * 0.026, 0, 0.04)))
    return _union(parts)


def gps_puck() -> trimesh.Trimesh:
    """GPS module puck: 16 mm square box with a rounded (domed) top.

    Local frame: origin at the center of the bottom face, z=0 at the bottom.
    """
    parts = [_box(0.016, 0.016, 0.007, at=(0, 0, 0.0035))]
    parts.append(_dome(0.0078, 0.0028, at=(0, 0, 0.007)))
    return _union(parts)


def xt60() -> trimesh.Trimesh:
    """XT60 connector body with its chamfered long edge, plus wire boots.

    The chamfer is approximated by stacking a full-height lower box with a
    narrower upper box shifted toward one long side. Two wire boots
    (r=0.0025, l=0.008) exit the -x face.

    Local frame: origin at the body center, mating face toward +x.
    """
    parts = [_box(0.016, 0.0082, 0.0055, at=(0, 0, -0.00125))]
    parts.append(_box(0.016, 0.0058, 0.0035, at=(0, -0.0012, 0.00225)))
    for sy in (-1, 1):
        parts.append(_cyl(0.0025, 0.008, at=(-0.008 - 0.002, sy * 0.002, 0),
                          axis="x", sections=16))
    return _union(parts)


def wire(path_points: list, radius: float = 0.0011,
         sections: int = 8) -> trimesh.Trimesh:
    """Smooth cable tube swept along a 3D polyline.

    The polyline is resampled to ~max(8, length/0.004) points, relaxed with
    two neighbor-averaging passes (endpoints pinned), then swept with a
    parallel-transported ring basis (no twist) and capped at both ends.
    Safe on 2-point paths.

    Local frame: whatever frame ``path_points`` are given in.
    """
    pts = np.asarray(path_points, dtype=float).reshape(-1, 3)
    keep = np.ones(len(pts), dtype=bool)
    keep[1:] = np.linalg.norm(np.diff(pts, axis=0), axis=1) > 1e-9
    pts = pts[keep]
    if len(pts) < 2:
        raise ValueError("wire() needs at least 2 distinct path points")
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    n = max(8, int(s[-1] / 0.004))
    u = np.linspace(0.0, s[-1], n)
    p = np.column_stack([np.interp(u, s, pts[:, k]) for k in range(3)])
    for _ in range(2):                       # gentle smoothing, ends pinned
        p[1:-1] = 0.5 * p[1:-1] + 0.25 * (p[:-2] + p[2:])

    # tangents (central differences) and a parallel-transported normal
    tan = np.gradient(p, axis=0)
    tan /= np.linalg.norm(tan, axis=1)[:, None]
    ref = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(tan[0], ref))) > 0.9:
        ref = np.array([1.0, 0.0, 0.0])
    nrm = np.cross(tan[0], ref)
    nrm /= np.linalg.norm(nrm)
    ang = np.linspace(0.0, 2.0 * np.pi, sections, endpoint=False)
    rings = np.zeros((n, sections, 3))
    for i in range(n):
        if i > 0:                            # transport nrm tan[i-1]->tan[i]
            axis = np.cross(tan[i - 1], tan[i])
            norm = np.linalg.norm(axis)
            if norm > 1e-12:
                dot = float(np.clip(np.dot(tan[i - 1], tan[i]), -1.0, 1.0))
                rot = rotation_matrix(np.arccos(dot), axis / norm)[:3, :3]
                nrm = rot @ nrm
        nrm -= tan[i] * float(np.dot(nrm, tan[i]))   # re-orthogonalize
        nrm /= np.linalg.norm(nrm)
        binm = np.cross(tan[i], nrm)
        rings[i] = (p[i] + radius * np.outer(np.cos(ang), nrm)
                    + radius * np.outer(np.sin(ang), binm))
    return _loft(rings)


def wire_bundle(path_points: list, n: int = 3,
                radius: float = 0.0009) -> trimesh.Trimesh:
    """``n`` parallel wires side by side along one polyline.

    Copies of :func:`wire` offset by ``2 * radius`` steps along a direction
    perpendicular to the path's average tangent.

    Local frame: whatever frame ``path_points`` are given in.
    """
    pts = np.asarray(path_points, dtype=float).reshape(-1, 3)
    avg = pts[-1] - pts[0]
    if np.linalg.norm(avg) < 1e-9:
        avg = np.array([1.0, 0.0, 0.0])
    avg /= np.linalg.norm(avg)
    ref = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(avg, ref))) > 0.9:
        ref = np.array([1.0, 0.0, 0.0])
    side = np.cross(avg, ref)
    side /= np.linalg.norm(side)
    parts = []
    for i in range(n):
        off = (i - (n - 1) / 2.0) * 2.0 * radius * side
        parts.append(wire((pts + off).tolist(), radius=radius))
    return _union(parts)
