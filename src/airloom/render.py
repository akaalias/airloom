"""Headless thumbnail rendering.

Default (and always-available) path: matplotlib 3D with the Agg backend --
works on any CPU-only machine, no EGL/OSMesa/GPU. A consistent three-quarter
camera and fixed world scale make frames visually comparable across
generations.

Parts are colored by role so evolved geometry reads apart from the fixed
platform: rust arms + near-black deck plates are what evolution shapes;
the blue Li-Ion pack, gray motor cans and pale translucent prop disks are
the fixed DroneAid kit.
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
WORLD_HALF = 0.34  # meters; fixed so every thumbnail shares scale (7" class)
PAPER = "#fffff8"

# part -> (hex color, alpha). Evolved geometry in warm/dark tones, the fixed
# platform in cool/neutral ones. Shared with the gallery's 3D viewer.
PART_COLORS: dict[str, tuple[str, float]] = {
    "deck": ("#34322e", 1.00),     # evolved: carbon deck plates + standoffs
    "arms": ("#8c2f1f", 1.00),     # evolved: plate arms + motor pads
    "battery": ("#4a6fa5", 1.00),  # fixed: 6S Li-Ion pack
    "stack": ("#5a7a52", 1.00),    # fixed: FC + 4-in-1 ESC boards in the gap
    "wiring": ("#8a6a1e", 1.00),   # fixed: XT60 + battery lead
    "camera": ("#2b2a28", 1.00),   # fixed: micro FPV camera
    "antennas": ("#3f7f8a", 1.00), # fixed: VTX / ELRS antennas + GPS
    "motors": ("#55534c", 1.00),   # fixed: motor cans
    "props": ("#b9b6a6", 0.55),    # fixed: real 3-blade props (translucent)
}
DRAW_ORDER = ("deck", "battery", "stack", "wiring", "camera", "antennas",
              "motors", "arms", "props")


def render_parts(parts: dict[str, "trimesh.Trimesh | None"], path: Path,
                 valid: bool = True,
                 size_px: tuple[int, int] = (720, 540)) -> None:
    dpi = 90
    fig = plt.figure(figsize=(size_px[0] / dpi, size_px[1] / dpi), dpi=dpi)
    ax = fig.add_subplot(111, projection="3d")
    light = matplotlib.colors.LightSource(azdeg=210, altdeg=48)
    fade = 1.0 if valid else 0.45
    for name in DRAW_ORDER:
        mesh = parts.get(name)
        if mesh is None:
            continue
        color, alpha = PART_COLORS.get(name, ("#8a97a8", 1.0))
        coll = Poly3DCollection(mesh.vertices[mesh.faces], facecolors=color,
                                shade=True, lightsource=light,
                                alpha=alpha * fade, zsort="average")
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
    fig.savefig(path, dpi=dpi, facecolor=PAPER)
    plt.close(fig)


def render_bottom_view(parts: dict[str, "trimesh.Trimesh | None"], path: Path,
                       valid: bool = True,
                       size_px: tuple[int, int] = (440, 440)) -> None:
    """The gallery's detail-block still: from under the drone looking up --
    the view that shows the evolved arm/plate geometry best."""
    dpi = 90
    fig = plt.figure(figsize=(size_px[0] / dpi, size_px[1] / dpi), dpi=dpi)
    ax = fig.add_subplot(111, projection="3d")
    light = matplotlib.colors.LightSource(azdeg=200, altdeg=-40)
    fade = 1.0 if valid else 0.45
    for name in DRAW_ORDER:
        mesh = parts.get(name)
        if mesh is None:
            continue
        color, alpha = PART_COLORS.get(name, ("#8a97a8", 1.0))
        coll = Poly3DCollection(mesh.vertices[mesh.faces], facecolors=color,
                                shade=True, lightsource=light,
                                alpha=alpha * fade, zsort="average")
        coll.set_linewidth(0.0)
        ax.add_collection3d(coll)
    half = 0.235
    ax.set_xlim(-half, half)
    ax.set_ylim(-half, half)
    ax.set_zlim(-half, half)
    ax.set_box_aspect((1.0, 1.0, 1.0))
    ax.view_init(elev=-82, azim=-90)
    ax.set_axis_off()
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, facecolor=PAPER)
    plt.close(fig)


def render_thumbnail(mesh: trimesh.Trimesh, path: Path, valid: bool = True,
                     size_px: tuple[int, int] = (720, 540)) -> None:
    """Single-mesh fallback (no labeled parts available)."""
    render_parts({"deck": mesh}, path, valid=valid, size_px=size_px)


def render_placeholder(path: Path, reason: str,
                       size_px: tuple[int, int] = (720, 540)) -> None:
    """Thumbnail for candidates whose mesh could not be built at all."""
    dpi = 90
    fig = plt.figure(figsize=(size_px[0] / dpi, size_px[1] / dpi), dpi=dpi)
    ax = fig.add_subplot(111)
    ax.text(0.5, 0.5, f"invalid\n{reason}", ha="center", va="center",
            fontsize=8, color="#9b998c", wrap=True)
    ax.set_axis_off()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, facecolor=PAPER)
    plt.close(fig)
