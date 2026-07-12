"""Watertight mesh primitives without shapely/earcut: convex-polygon
extrusions and tapered section sweeps, plus 2D polygon section properties."""
from __future__ import annotations

import math

import numpy as np
import trimesh


def polygon_area(pts: np.ndarray) -> float:
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def polygon_properties(pts: np.ndarray) -> tuple[float, float, float]:
    """(area, centroid_y, I_horizontal) of a CCW polygon.

    I_horizontal is the second moment about the horizontal axis through the
    centroid (bending under a vertical load), with y the vertical coordinate.
    """
    x, y = pts[:, 0], pts[:, 1]
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    cross = x * y1 - x1 * y
    a = 0.5 * float(np.sum(cross))
    cy = float(np.sum((y + y1) * cross)) / (6.0 * a)
    ixx = float(np.sum((y * y + y * y1 + y1 * y1) * cross)) / 12.0
    return a, cy, ixx - a * cy * cy


def rounded_rect(length: float, width: float, fillet: float, n_arc: int = 6) -> np.ndarray:
    """CCW rounded-rectangle polygon in the xy plane, centered at origin."""
    r = min(fillet, 0.49 * min(length, width))
    hx, hy = length / 2.0 - r, width / 2.0 - r
    if r < 1e-6:  # sharp corners: a plain rectangle (avoids duplicate points)
        return np.array([(hx, hy), (-hx, hy), (-hx, -hy), (hx, -hy)])
    pts: list[tuple[float, float]] = []
    corners = [(hx, hy, 0.0), (-hx, hy, 90.0), (-hx, -hy, 180.0), (hx, -hy, 270.0)]
    for cx, cy, a0 in corners:
        for i in range(n_arc + 1):
            a = math.radians(a0 + 90.0 * i / n_arc)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return np.array(pts)


def superellipse_section(width: float, height: float, blend: float,
                         n: int = 24) -> np.ndarray:
    """Arm cross-section polygon (CCW) for the shape-blend gene.

    blend 0 -> near-rectangle (superellipse exponent 8), 0.5 -> ellipse,
    1 -> faired teardrop (elongated ellipse with a narrowing tail).
    u axis = horizontal across the arm, v axis = vertical (thickness).
    """
    p = 8.0 - 12.0 * min(blend, 0.5)  # 8 -> 2
    fair = max(0.0, (blend - 0.5) * 2.0)
    a, b = width / 2.0, height / 2.0
    pts = []
    for i in range(n):
        th = 2.0 * math.pi * i / n
        c, s = math.cos(th), math.sin(th)
        u = a * math.copysign(abs(c) ** (2.0 / p), c)
        v = b * math.copysign(abs(s) ** (2.0 / p), s)
        if fair > 0.0 and c > 0.0:  # stretch + thin the downstream side
            u *= 1.0 + 1.2 * fair * c
            v *= 1.0 - 0.35 * fair * c
        pts.append((u, v))
    return np.array(pts)


def _as_solid(vertices: np.ndarray, faces: list[list[int]]) -> trimesh.Trimesh:
    mesh = trimesh.Trimesh(vertices=vertices, faces=np.array(faces), process=True)
    mesh.fix_normals()
    if mesh.volume < 0:
        mesh.invert()
    return mesh


def extrude_convex_polygon(pts: np.ndarray, z0: float, z1: float) -> trimesh.Trimesh:
    """Watertight extrusion of a convex CCW polygon along z."""
    n = len(pts)
    bottom = np.column_stack([pts, np.full(n, z0)])
    top = np.column_stack([pts, np.full(n, z1)])
    vertices = np.vstack([bottom, top])
    faces: list[list[int]] = []
    for i in range(n):
        j = (i + 1) % n
        faces.append([i, j, n + j])
        faces.append([i, n + j, n + i])
    for i in range(1, n - 1):  # caps as fans (convex)
        faces.append([0, i + 1, i])          # bottom, faces -z
        faces.append([n, n + i, n + i + 1])  # top, faces +z
    return _as_solid(vertices, faces)


def sweep_section(section: np.ndarray, root: np.ndarray, tip: np.ndarray,
                  taper: float) -> trimesh.Trimesh:
    """Sweep a 2D section from root to tip, scaling it by `taper` at the tip.

    The section's u axis is mapped to the horizontal direction perpendicular
    to the arm axis, its v axis to the (near-)vertical normal.
    """
    axis = tip - root
    length = float(np.linalg.norm(axis))
    axis = axis / length
    world_z = np.array([0.0, 0.0, 1.0])
    u = np.cross(axis, world_z)
    if np.linalg.norm(u) < 1e-9:
        u = np.array([1.0, 0.0, 0.0])
    u = u / np.linalg.norm(u)
    v = np.cross(u, axis)  # near-vertical
    n = len(section)
    ring_root = root + section[:, 0:1] * u + section[:, 1:2] * v
    ring_tip = tip + taper * (section[:, 0:1] * u + section[:, 1:2] * v)
    vertices = np.vstack([ring_root, ring_tip])
    faces: list[list[int]] = []
    for i in range(n):
        j = (i + 1) % n
        faces.append([i, j, n + j])
        faces.append([i, n + j, n + i])
    for i in range(1, n - 1):
        faces.append([0, i + 1, i])
        faces.append([n, n + i, n + i + 1])
    return _as_solid(vertices, faces)


def union(meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    return trimesh.boolean.union(meshes, engine="manifold")
