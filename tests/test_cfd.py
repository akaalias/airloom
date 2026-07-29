"""CFD calibration harness: everything except the Docker solve.

Case generation, the analytical predictions the report compares against,
the freestream-direction convention (must match aero.py's rasterization
direction), and the force.dat parser for both OpenFOAM output layouts.
"""
import base64
import json
import math

import numpy as np
import pytest

from airloom.aero import CD_ARM, CD_BODY, measure_areas, projected_area
from airloom.cfd import (CONTRAST_GENES, TILTS_DEG, generate, measured_cda,
                         parse_forces, predicted_cda, _frame_for,
                         _map_nearest, _mesh_face_centroids,
                         _parse_surface_vtp)
from airloom.genome import BASELINE, Genome


@pytest.fixture(scope="module")
def cases(cfg, tmp_path_factory):
    root = tmp_path_factory.mktemp("cfd")
    specs = generate(cfg, root, tilts=(0.0, 20.0))
    return root, specs


def test_contrast_genome_builds_valid(cfg):
    frame = _frame_for(CONTRAST_GENES, cfg)
    assert frame.valid
    base = _frame_for(BASELINE, cfg)
    # it must actually be a different shape (arm span differs)
    assert abs(frame.arms_mesh.bounds[1][0]
               - base.arms_mesh.bounds[1][0]) > 0.02


def test_generate_writes_complete_cases(cfg, cases):
    root, specs = cases
    assert len(specs) == 4 * 2  # 4 geometries x 2 tilts requested
    man = json.loads((root / "manifest.json").read_text())
    assert len(man["cases"]) == len(specs)
    for s in specs:
        d = root / "cases" / s.name
        for f in ("system/blockMeshDict", "system/snappyHexMeshDict",
                  "system/controlDict", "system/fvSchemes",
                  "system/fvSolution", "constant/turbulenceProperties",
                  "constant/triSurface/frame.stl",
                  "0/U", "0/p", "0/k", "0/omega", "0/nut"):
            assert (d / f).exists(), f"{s.name}: missing {f}"
        u_txt = (d / "0/U").read_text()
        t = math.radians(s.tilt_deg)
        assert f"{s.u_ms * math.cos(t):.6g}" in u_txt
        assert "freestreamVelocity" in u_txt


def test_predictions_are_consistent(cfg, cases):
    root, specs = cases
    by = {(s.geometry, s.tilt_deg): s.predicted_cda_m2 for s in specs}
    for tilt in (0.0, 20.0):
        arms = by[("arms_baseline", tilt)]
        body = by[("body_baseline", tilt)]
        full = by[("full_baseline", tilt)]
        assert arms > 0 and body > 0
        # the buildup has no interference: full is exactly the sum
        assert full == pytest.approx(arms + body, rel=1e-9)
    # frontal (0 deg) drag area must be plausibly small for a 7-inch quad
    assert 0.001 < by[("full_baseline", 0.0)] < 0.05


def test_predicted_matches_aero_buildup(cfg):
    frame = _frame_for(BASELINE, cfg)
    areas = measure_areas(frame, cfg.platform)
    # at a grid tilt, prediction = area * Cd exactly (no interpolation error)
    assert predicted_cda(areas, "arms_baseline", 20.0) == pytest.approx(
        float(np.interp(20.0, areas.tilt_deg, areas.arm_x)) * CD_ARM)
    assert predicted_cda(areas, "full_baseline", 0.0) == pytest.approx(
        areas.arm_x[0] * CD_ARM + areas.body_x[0] * CD_BODY)


def test_flow_direction_matches_rasterizer(cfg):
    """The case's freestream vector must probe the same silhouette aero.py
    rasterizes: projected area along (cos t, 0, sin t)."""
    frame = _frame_for(BASELINE, cfg)
    t = math.radians(20.0)
    d = np.array([math.cos(t), 0.0, math.sin(t)])
    a_dir = projected_area(frame.arms_mesh, d)
    areas = measure_areas(frame, cfg.platform)
    assert a_dir == pytest.approx(
        float(np.interp(20.0, areas.tilt_deg, areas.arm_x)), rel=0.02)


def _fake_case(tmp_path, line):
    d = tmp_path / "postProcessing/forces1/0"
    d.mkdir(parents=True)
    (d / "force.dat").write_text("# comment\n# more\n" + line + "\n")
    return tmp_path


def test_parse_forces_old_layout(tmp_path):
    # (pressure) (viscous) (porous): total = pressure + viscous
    case = _fake_case(tmp_path,
                      "600 ((1.0 0.1 0.2) (0.5 0.05 0.1) (0 0 0))")
    assert parse_forces(case) == pytest.approx((1.5, 0.15, 0.3))


def test_parse_forces_new_layout(tmp_path):
    # (total) (pressure) (viscous): first triplet already the sum
    case = _fake_case(tmp_path,
                      "600 ((1.5 0.15 0.3) (1.0 0.1 0.2) (0.5 0.05 0.1))")
    assert parse_forces(case) == pytest.approx((1.5, 0.15, 0.3))


def test_measured_cda_projects_on_freestream(tmp_path):
    case = _fake_case(tmp_path, "600 ((2.0 0.0 1.0) (0 0 0) (0 0 0))")
    u, tilt = 12.0, 30.0
    t = math.radians(tilt)
    expect = (2.0 * math.cos(t) + 1.0 * math.sin(t)) / (0.5 * 1.225 * u * u)
    assert measured_cda(case, tilt, u) == pytest.approx(expect)


# --------------------------------------------- surface pressure mapping ---
def _vtp_inline_array(arr: np.ndarray) -> str:
    """OpenFOAM's inline-binary DataArray body: base64(UInt64 byte-count
    header + raw payload), matching what _parse_surface_vtp/
    _parse_tracks_vtp both expect."""
    raw = arr.tobytes()
    return base64.b64encode(np.uint64(len(raw)).tobytes() + raw).decode()


def _write_fake_surface_vtp(path, points, conn, offsets, p) -> None:
    def da(dtype_name, name, arr):
        return (f"<DataArray type='{dtype_name}' Name='{name}'>"
                f"{_vtp_inline_array(arr)}</DataArray>")
    txt = ("<VTKFile><PolyData><Piece>"
          f"<Points>{da('Float32', 'Points', points.astype(np.float32))}"
          "</Points>"
          "<Polys>"
          f"{da('Int32', 'connectivity', conn.astype(np.int32))}"
          f"{da('Int32', 'offsets', offsets.astype(np.int32))}"
          "</Polys>"
          f"<CellData>{da('Float32', 'p', p.astype(np.float32))}"
          "</CellData>"
          "</Piece></PolyData></VTKFile>")
    path.write_text(txt)


def test_parse_surface_vtp_centroids_and_pressure(tmp_path):
    # two triangles, sharing no vertices, one CellData value each
    points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0],
                       [2, 0, 0], [3, 0, 0], [2, 1, 0]], float)
    conn = np.arange(6)
    offsets = np.array([3, 6])
    p = np.array([10.0, 20.0])
    vtp = tmp_path / "frame.vtp"
    _write_fake_surface_vtp(vtp, points, conn, offsets, p)
    centroids, values = _parse_surface_vtp(vtp)
    assert centroids.shape == (2, 3)
    assert centroids[0] == pytest.approx([1 / 3, 1 / 3, 0], abs=1e-5)
    assert centroids[1] == pytest.approx([7 / 3, 1 / 3, 0], abs=1e-5)
    assert values == pytest.approx([10.0, 20.0], abs=1e-3)


def test_mesh_face_centroids_matches_render_face_order(tmp_path):
    # a unit square split into two triangles, uint16 face indices
    v = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
                 dtype=np.float32)
    f = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.uint16)
    blob = {"v": base64.b64encode(v.tobytes()).decode(),
           "f": base64.b64encode(f.tobytes()).decode(), "i": "u16"}
    mesh_json = tmp_path / "cand.mesh.json"
    mesh_json.write_text(json.dumps(blob))
    centroids = _mesh_face_centroids(mesh_json)
    assert centroids.shape == (2, 3)
    assert centroids[0] == pytest.approx([2 / 3, 1 / 3, 0], abs=1e-5)
    assert centroids[1] == pytest.approx([1 / 3, 2 / 3, 0], abs=1e-5)


def test_map_nearest_carries_closest_source_value():
    src_xyz = np.array([[0, 0, 0], [10, 0, 0]], float)
    src_val = np.array([1.0, 99.0])
    dst_xyz = np.array([[0.1, 0, 0], [9.9, 0, 0], [4.9, 0, 0]], float)
    out = _map_nearest(src_xyz, src_val, dst_xyz)
    assert out == pytest.approx([1.0, 99.0, 1.0])
