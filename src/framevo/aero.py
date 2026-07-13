"""Phase-A frame aerodynamics: component drag buildup.

Projected areas are measured by rasterizing the frame's triangle mesh onto a
grid normal to the flow direction (per component class: arms vs body), at a
sweep of tilt angles. Drag coefficients per class:

  arms  -- interpolated by the cross-section blend gene:
           flat-plate-ish 1.9 -> cylinder 1.1 -> faired section 0.6
  body  -- rounded box, 1.05

plus an interference penalty where arms sit inside the rotor disks: the rotor
wash (induced velocity) presses down on the arm planform under each disk.

Output is a compact, picklable DragTable: CdA vs tilt for body-x and body-y
flow, blended over azimuth with cos^2/sin^2 weights in the simulator.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from .config import Platform

if TYPE_CHECKING:  # keep this module trimesh-free for lightweight sim workers
    from .frame_gen import FrameModel

TILT_GRID_DEG = np.array([0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
CD_BODY = 1.05


CD_ARM = 1.7  # flat carbon plate arm, edges rounded, edge-on flow


def projected_area(mesh: Any, direction: np.ndarray,
                   cell: float = 0.002) -> float:
    """Area of the mesh silhouette projected along `direction` (rasterized)."""
    d = np.asarray(direction, dtype=float)
    d = d / np.linalg.norm(d)
    # orthonormal basis of the projection plane
    ref = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    e1 = np.cross(d, ref); e1 /= np.linalg.norm(e1)
    e2 = np.cross(d, e1)
    verts2 = mesh.vertices @ np.column_stack([e1, e2])  # (nv, 2)
    tris = verts2[mesh.faces]  # (nf, 3, 2)

    lo = verts2.min(axis=0) - cell
    hi = verts2.max(axis=0) + cell
    nx = max(int(math.ceil((hi[0] - lo[0]) / cell)), 2)
    ny = max(int(math.ceil((hi[1] - lo[1]) / cell)), 2)
    grid = np.zeros((nx, ny), dtype=bool)

    for tri in tris:
        tmin = tri.min(axis=0); tmax = tri.max(axis=0)
        i0 = max(int((tmin[0] - lo[0]) / cell), 0)
        i1 = min(int((tmax[0] - lo[0]) / cell) + 1, nx - 1)
        j0 = max(int((tmin[1] - lo[1]) / cell), 0)
        j1 = min(int((tmax[1] - lo[1]) / cell) + 1, ny - 1)
        if i1 <= i0 or j1 <= j0:
            continue
        sub = grid[i0:i1 + 1, j0:j1 + 1]
        xs = lo[0] + (np.arange(i0, i1 + 1) + 0.5) * cell
        ys = lo[1] + (np.arange(j0, j1 + 1) + 0.5) * cell
        px, py = np.meshgrid(xs, ys, indexing="ij")
        # barycentric point-in-triangle
        ax, ay = tri[0]; bx, by = tri[1]; cx, cy = tri[2]
        det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(det) < 1e-18:
            continue
        w1 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / det
        w2 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / det
        w3 = 1.0 - w1 - w2
        sub |= (w1 >= -1e-9) & (w2 >= -1e-9) & (w3 >= -1e-9)
    return float(grid.sum()) * cell * cell


@dataclass
class DragTable:
    """Compact, picklable aero summary of one candidate."""
    tilt_deg: np.ndarray       # tilt grid
    cda_x: np.ndarray          # CdA [m^2] flow along body x, per tilt
    cda_y: np.ndarray          # CdA [m^2] flow along body y, per tilt
    a_top: float = 0.0         # upward-facing projected area (rain)
    wash_cda: float = 0.0      # Cd*A of arm planform under the rotor disks

    def cda(self, tilt_rad: float, azimuth_rad: float) -> float:
        """CdA for flow arriving at `tilt` from horizontal, `azimuth` from
        body x (cos^2/sin^2 blend between the two measured planes)."""
        t = abs(math.degrees(tilt_rad))
        grid = self.tilt_deg
        if t >= grid[-1]:
            i, f = len(grid) - 2, 1.0
        else:
            step = grid[1] - grid[0]
            x = t / step
            i = min(int(x), len(grid) - 2)
            f = x - i
        cx = self.cda_x[i] * (1 - f) + self.cda_x[i + 1] * f
        cy = self.cda_y[i] * (1 - f) + self.cda_y[i + 1] * f
        c2 = math.cos(azimuth_rad) ** 2
        return float(cx * c2 + cy * (1.0 - c2))


@dataclass
class AreaTable:
    """Raw projected areas per component class -- the expensive rasterized
    half of the drag buildup, independent of any Cd assumption. Lets the
    robustness sweep re-price drag under perturbed Cds without re-measuring."""
    tilt_deg: np.ndarray
    arm_x: np.ndarray          # arm silhouette [m^2], flow along body x
    arm_y: np.ndarray
    body_x: np.ndarray
    body_y: np.ndarray
    a_top: float
    wash_area: float           # arm planform under the rotor disks


def measure_areas(frame: "FrameModel", platform: Platform) -> AreaTable:
    arms, body = frame.arms_mesh, frame.body_mesh

    arm_x, arm_y, body_x, body_y = [], [], [], []
    for tilt_deg in TILT_GRID_DEG:
        t = math.radians(tilt_deg)
        # vehicle tilts nose-down into the flow: relative wind in body axes
        # gains an upward component
        d_x = np.array([math.cos(t), 0.0, math.sin(t)])
        d_y = np.array([0.0, math.cos(t), math.sin(t)])
        arm_x.append(projected_area(arms, d_x))
        arm_y.append(projected_area(arms, d_y))
        body_x.append(projected_area(body, d_x))
        body_y.append(projected_area(body, d_y))

    a_top = projected_area(arms, [0, 0, 1]) + projected_area(body, [0, 0, 1])

    # arm planform under the rotor disks: roughly one prop radius of arm span
    # inboard of each tip, at the mean local width
    r = platform.propulsion.prop_diameter_m / 2.0
    assert frame.arm is not None
    span = min(r, frame.arm.length)
    wash_area = 4.0 * span * frame.arm.planform_width_mean
    return AreaTable(tilt_deg=TILT_GRID_DEG.copy(),
                     arm_x=np.array(arm_x), arm_y=np.array(arm_y),
                     body_x=np.array(body_x), body_y=np.array(body_y),
                     a_top=a_top, wash_area=wash_area)


def drag_table_from_areas(areas: AreaTable, cd_arm: float = CD_ARM,
                          cd_body: float = CD_BODY,
                          wash_scale: float = 1.0) -> DragTable:
    return DragTable(tilt_deg=areas.tilt_deg.copy(),
                     cda_x=areas.arm_x * cd_arm + areas.body_x * cd_body,
                     cda_y=areas.arm_y * cd_arm + areas.body_y * cd_body,
                     a_top=areas.a_top,
                     wash_cda=areas.wash_area * cd_arm * wash_scale)


def build_drag_table(frame: "FrameModel", platform: Platform) -> DragTable:
    return drag_table_from_areas(measure_areas(frame, platform))
