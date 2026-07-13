"""Real Source One V6 geometry: extraction and evolution-ready morphing.

The official So1-V6-7inDC plate drawing (data/source_one/, GPLv3) is parsed
into named outlines -- front/rear arms, main / mid / top deck plates -- each
with its true shape, lightening cutouts and bolt holes. The genome then
deforms these REAL outlines with zone-based morphs that preserve the
functional regions (tongue bolt clusters, motor mounts, the 30.5 mm stack
pattern), so every candidate remains a plausible, printable/cuttable part
derived from the real design rather than a primitive.

All extraction coordinates are millimeters in a part-local frame
(x along the part's long axis, y centered); extrusion converts to meters.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

import numpy as np
import trimesh
from matplotlib.path import Path as _MplPath

DXF_FILE = "So1-V6-7inDC-2025-JUL-07.dxf"


# --------------------------------------------------------------- containers --
@dataclass(frozen=True)
class Outline:
    """A flat CNC/print part in local mm coordinates."""
    name: str
    shell: np.ndarray                 # (N, 2) closed outline
    holes: tuple[tuple[float, float, float], ...]   # (x, y, r) bolt holes
    cutouts: tuple[np.ndarray, ...]   # lightening slots (closed polys)

    @property
    def length(self) -> float:
        return float(self.shell[:, 0].max() - self.shell[:, 0].min())

    @property
    def width(self) -> float:
        return float(self.shell[:, 1].max() - self.shell[:, 1].min())


@dataclass(frozen=True)
class ArmOutline(Outline):
    tongue_end: float      # x where the rigid root tongue ends
    mount_start: float     # x where the rigid motor-mount zone begins
    motor_xy: tuple[float, float]  # motor axis position


# --------------------------------------------------------------- extraction --
def _polys(msp, layer: str) -> list[np.ndarray]:
    """Closed polyline outlines with arc bulges properly flattened."""
    from ezdxf import path as ezpath

    out = []
    for e in msp.query(f'LWPOLYLINE[layer=="{layer}"]'):
        if len(e) < 3 or not e.closed:
            continue
        pts = np.array([(v.x, v.y) for v in
                        ezpath.make_path(e).flattening(distance=0.05)])
        if len(pts) >= 3:
            if np.allclose(pts[0], pts[-1]):
                pts = pts[:-1]
            out.append(pts)
    return out


def _circles(msp, layer: str) -> list[tuple[np.ndarray, float]]:
    return [(np.array([e.dxf.center.x, e.dxf.center.y]), e.dxf.radius)
            for e in msp.query(f'CIRCLE[layer=="{layer}"]')]


def _area(pts: np.ndarray) -> float:
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * abs(float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)))


def _inside(poly: np.ndarray, pt: np.ndarray) -> bool:
    return bool(_MplPath(poly).contains_point(pt))


def _find_instance(polys: list[np.ndarray], w: float, h: float,
                   tol: float = 1.5) -> np.ndarray:
    for p in polys:
        pw = p[:, 0].max() - p[:, 0].min()
        ph = p[:, 1].max() - p[:, 1].min()
        if abs(pw - w) < tol and abs(ph - h) < tol:
            return p
    raise ValueError(f"no {w}x{h} outline instance found")


def _to_arm_local(arm: np.ndarray, circles, root_at_min_y: bool = True):
    """Rotate a vertically drawn arm to x-along-axis, root at x=0."""
    org = np.array([(arm[:, 0].min() + arm[:, 0].max()) / 2, arm[:, 1].min()])
    shell = np.column_stack([arm[:, 1] - org[1], -(arm[:, 0] - org[0])])
    holes = tuple((float(c[1] - org[1]), float(-(c[0] - org[0])), float(r))
                  for c, r in circles if _inside(arm, c))
    return shell, holes


def _extract_arm(msp, name: str, bbox: tuple[float, float]) -> ArmOutline:
    arm = _find_instance(_polys(msp, "Frame-Arms"), *bbox)
    shell, holes = _to_arm_local(arm, _circles(msp, "Frame-Arms"))
    xs = sorted(h[0] for h in holes)
    motor = max(holes, key=lambda h: h[0])          # the r3.5 shaft hole
    tongue_end = max(x for x in xs if x < shell[:, 0].max() * 0.5) + 8.0
    mount_start = motor[0] - 14.0
    # the drawing keeps the 4x M3 motor-pattern holes on an assembly layer;
    # add them explicitly (16 x 19 mm standard 2806 pattern)
    extra = tuple((motor[0] + dx, motor[1] + dy, 1.6)
                  for dx, dy in ((8.0, 9.5), (-8.0, 9.5), (8.0, -9.5), (-8.0, -9.5)))
    return ArmOutline(name=name, shell=shell, holes=holes + extra, cutouts=(),
                      tongue_end=float(tongue_end),
                      mount_start=float(mount_start),
                      motor_xy=(float(motor[0]), float(motor[1])))


def _extract_plate(msp, name: str, layer: str, long_dim: float) -> Outline:
    polys = _polys(msp, layer)
    plate = None
    for p in polys:
        w = p[:, 0].max() - p[:, 0].min()
        h = p[:, 1].max() - p[:, 1].min()
        if abs(max(w, h) - long_dim) < 1.0:
            plate = p
            break
    if plate is None:
        raise ValueError(f"no plate with long dim {long_dim} on {layer}")
    w = plate[:, 0].max() - plate[:, 0].min()
    h = plate[:, 1].max() - plate[:, 1].min()
    ctr = np.array([(plate[:, 0].min() + plate[:, 0].max()) / 2,
                    (plate[:, 1].min() + plate[:, 1].max()) / 2])
    if h > w:  # rotate to long-axis = x
        shell = np.column_stack([plate[:, 1] - ctr[1], -(plate[:, 0] - ctr[0])])
        tf = lambda c: (float(c[1] - ctr[1]), float(-(c[0] - ctr[0])))  # noqa: E731
    else:
        shell = plate - ctr
        tf = lambda c: (float(c[0] - ctr[0]), float(c[1] - ctr[1]))  # noqa: E731
    holes = tuple((*tf(c), float(r)) for c, r in _circles(msp, layer)
                  if _inside(plate, c))
    cutouts = []
    for p in polys:
        if p is plate or _area(p) > _area(plate) * 0.5:
            continue
        if _inside(plate, p.mean(axis=0)):
            cutouts.append(np.array([tf(q) for q in p]))
    return Outline(name=name, shell=shell, holes=holes, cutouts=tuple(cutouts))


@lru_cache(maxsize=2)
def load_outlines(data_dir: str) -> dict[str, Outline]:
    """Parse the official DXF once per process."""
    import ezdxf

    doc = ezdxf.readfile(str(Path(data_dir) / DXF_FILE))
    msp = doc.modelspace()
    return {
        "arm_rear": _extract_arm(msp, "arm_rear", (29.2, 160.7)),
        "arm_front": _extract_arm(msp, "arm_front", (31.1, 185.2)),
        "plate_main": _extract_plate(msp, "plate_main", "Draw3", 106.6),
        "plate_mid": _extract_plate(msp, "plate_mid", "Draw14", 107.6),
        "plate_top": _extract_plate(msp, "plate_top", "Draw13", 160.3),
    }


# ------------------------------------------------------------------ morphing --
def _circle_poly(x: float, y: float, r: float, n: int = 20) -> np.ndarray:
    a = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return np.column_stack([x + r * np.cos(a), y + r * np.sin(a)])


def morph_arm(arm: ArmOutline, length_scale: float, width_scale: float,
              waist_scale: float) -> ArmOutline:
    """Deform the real arm outline while preserving the functional zones.

    The tongue [0, tongue_end] stays rigid (it must still bolt into the
    deck); the motor mount zone stays rigid (the 2806 pattern must fit);
    the shaft between them stretches along x by `length_scale` and its
    width is scaled by a profile that blends `width_scale` at the zone
    borders into `waist_scale` at mid-shaft.
    """
    t0, m0 = arm.tongue_end, arm.mount_start
    shaft = m0 - t0
    shift = shaft * (length_scale - 1.0)

    def densify(pts: np.ndarray, step: float = 2.0) -> np.ndarray:
        out = []
        for a, b in zip(pts, np.roll(pts, -1, axis=0)):
            n = max(int(np.linalg.norm(b - a) / step), 1)
            out += [a + (b - a) * t for t in np.linspace(0, 1, n, endpoint=False)]
        return np.array(out)

    def warp(pts: np.ndarray) -> np.ndarray:
        x, y = pts[:, 0].copy(), pts[:, 1].copy()
        s = np.clip((x - t0) / shaft, 0.0, 1.0)
        x = np.where(x <= t0, x,
                     np.where(x >= m0, x + shift, t0 + (x - t0) * length_scale))
        bump = np.sin(np.pi * s) ** 2
        wf = np.where((pts[:, 0] > t0) & (pts[:, 0] < m0),
                      width_scale + (waist_scale - width_scale) * bump, 1.0)
        return np.column_stack([x, y * wf])

    shell = warp(densify(arm.shell))
    holes = tuple((h[0] if h[0] <= t0 else h[0] + shift, h[1], h[2])
                  for h in arm.holes)
    return replace(arm, shell=shell, holes=holes,
                   mount_start=m0 + shift,
                   motor_xy=(arm.motor_xy[0] + shift, arm.motor_xy[1]))


def morph_plate(plate: Outline, sx: float, sy: float,
                rigid_holes_r_min: float = 0.0) -> Outline:
    """Scale a deck plate; the 30.5 mm stack pattern (the four r<=1.6 holes
    nearest the center) is re-pinned to its exact original positions so the
    FC/ESC stack always fits."""
    shell = plate.shell * np.array([sx, sy])
    cutouts = tuple(c * np.array([sx, sy]) for c in plate.cutouts)
    stack = sorted((h for h in plate.holes if h[2] <= 1.8),
                   key=lambda h: math.hypot(h[0], h[1]))[:4]
    stack_set = set(stack)
    holes = []
    for h in plate.holes:
        if h in stack_set:
            holes.append(h)  # keep the stack pattern exact
        else:
            holes.append((h[0] * sx, h[1] * sy, h[2]))
    return replace(plate, shell=shell, holes=tuple(holes), cutouts=cutouts)


# ------------------------------------------------------------------ meshing --
def extrude(outline: Outline, thickness_m: float,
            drop_small_cutouts: bool = False) -> trimesh.Trimesh:
    """Real outline (mm) -> watertight plate solid (meters)."""
    from shapely.geometry import Polygon
    from shapely.validation import make_valid

    shell = outline.shell * 1e-3
    poly = Polygon(shell)
    if not poly.is_valid:
        poly = make_valid(poly).buffer(0)
    # subtract holes one by one: robust against touching/overlapping features
    cutters = [Polygon(_circle_poly(*h) * 1e-3) for h in outline.holes]
    if not drop_small_cutouts:
        cutters += [Polygon(c * 1e-3).buffer(0) for c in outline.cutouts]
    for cut in cutters:
        if cut.is_valid and cut.area > 0:
            poly = poly.difference(cut.buffer(1e-5))
    poly = poly.simplify(2e-5).buffer(0)
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    mesh = trimesh.creation.extrude_polygon(poly, height=thickness_m)
    if not mesh.is_watertight:
        mesh.merge_vertices()
        trimesh.repair.fill_holes(mesh)
    return mesh


def mirror_y(outline: Outline) -> Outline:
    """The opposite-chirality arm (DC left/right arms are mirror images)."""
    shell = outline.shell.copy()
    shell[:, 1] *= -1.0
    shell = shell[::-1]  # keep winding CCW
    holes = tuple((h[0], -h[1], h[2]) for h in outline.holes)
    cutouts = tuple(np.column_stack([c[:, 0], -c[:, 1]])[::-1]
                    for c in outline.cutouts)
    if isinstance(outline, ArmOutline):
        return replace(outline, shell=shell, holes=holes, cutouts=cutouts,
                       motor_xy=(outline.motor_xy[0], -outline.motor_xy[1]))
    return replace(outline, shell=shell, holes=holes, cutouts=cutouts)


# Stock arm anchors on the main plate, derived from the official drawing:
# the front pair is EXACT (registered on the tongue bolt-hole pattern); the
# rear pair is the best clamp-coverage fit onto the rear plate lobes
# (98% tongue coverage; the rear tongue holes do not appear as a matchable
# pair on the main plate -- see data/source_one/README.md).
# (azimuth_deg of the left arm, anchor T in plate-local mm)
STOCK_ANCHORS = {
    "front": (31.4, (34.3, 6.8)),
    "rear": (144.0, (17.5, 8.0)),
}


# ----------------------------------------------------------------- analysis --
def shaft_min_width(arm: ArmOutline) -> float:
    """Narrowest shaft width (mm) of a (possibly morphed) arm outline --
    the structural cross-section for the beam checks."""
    dense = []
    for a, b in zip(arm.shell, np.roll(arm.shell, -1, axis=0)):
        n = max(int(np.linalg.norm(b - a) / 0.7), 1)
        dense += [a + (b - a) * t for t in np.linspace(0, 1, n, endpoint=False)]
    d = np.array(dense)
    t0, m0 = arm.tongue_end, arm.mount_start
    widths = []
    for x in np.linspace(t0 + 2.0, m0 - 2.0, 25):
        ys = d[np.abs(d[:, 0] - x) < 1.0][:, 1]
        if len(ys) > 1:
            widths.append(float(ys.max() - ys.min()))
    return min(widths) if widths else arm.width


def ray_to_boundary(outline: Outline, azimuth_rad: float) -> float:
    """Distance (mm) from the outline's origin to its boundary along a ray."""
    from shapely.geometry import LineString, Polygon

    poly = Polygon(outline.shell)
    far = 500.0
    ray = LineString([(0, 0), (far * math.cos(azimuth_rad),
                               far * math.sin(azimuth_rad))])
    hit = poly.boundary.intersection(ray)
    if hit.is_empty:
        return 0.0
    pts = getattr(hit, "geoms", [hit])
    return min(math.hypot(p.x, p.y) for p in pts if hasattr(p, "x"))
