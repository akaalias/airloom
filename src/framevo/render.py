"""Headless thumbnail rendering.

Default (and always-available) path: matplotlib 3D with the Agg backend --
works on any CPU-only machine, no EGL/OSMesa/GPU. A consistent three-quarter
camera and fixed world scale make frames visually comparable across
generations.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import trimesh  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

VIEW_ELEV = 22.0
VIEW_AZIM = -55.0
WORLD_HALF = 0.26  # meters; fixed so every thumbnail shares scale


def render_thumbnail(mesh: trimesh.Trimesh, path: Path, valid: bool = True,
                     size_px: tuple[int, int] = (360, 270)) -> None:
    dpi = 90
    fig = plt.figure(figsize=(size_px[0] / dpi, size_px[1] / dpi), dpi=dpi)
    ax = fig.add_subplot(111, projection="3d")
    tris = mesh.vertices[mesh.faces]
    face = "#8a97a8" if valid else "#c9c2bc"
    coll = Poly3DCollection(tris, facecolors=face, shade=True,
                            lightsource=matplotlib.colors.LightSource(azdeg=210, altdeg=48))
    coll.set_linewidth(0.0)
    ax.add_collection3d(coll)
    ax.set_xlim(-WORLD_HALF, WORLD_HALF)
    ax.set_ylim(-WORLD_HALF, WORLD_HALF)
    ax.set_zlim(-WORLD_HALF * 0.75, WORLD_HALF * 0.75)
    ax.set_box_aspect((1.0, 1.0, 0.75))
    ax.view_init(elev=VIEW_ELEV, azim=VIEW_AZIM)
    ax.set_axis_off()
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, facecolor="white")
    plt.close(fig)


def render_placeholder(path: Path, reason: str,
                       size_px: tuple[int, int] = (360, 270)) -> None:
    """Thumbnail for candidates whose mesh could not be built at all."""
    dpi = 90
    fig = plt.figure(figsize=(size_px[0] / dpi, size_px[1] / dpi), dpi=dpi)
    ax = fig.add_subplot(111)
    ax.text(0.5, 0.5, f"invalid\n{reason}", ha="center", va="center",
            fontsize=8, color="#8a8580", wrap=True)
    ax.set_axis_off()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, facecolor="white")
    plt.close(fig)
