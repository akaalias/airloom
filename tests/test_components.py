"""Smoke tests for the drone component library: every part builds, has real
geometry, and key dimensions land where the datasheets say (tolerance 1e-3)."""
import numpy as np
import pytest
import trimesh

from airloom import components

TOL = 1e-3


def _built(mesh: trimesh.Trimesh) -> None:
    assert isinstance(mesh, trimesh.Trimesh)
    assert len(mesh.faces) > 0
    assert mesh.area > 0.0


def test_battery_pack_dimensions():
    m = components.battery_pack()
    _built(m)
    ext = m.extents
    assert 0.064 - TOL <= ext[0] <= 0.068 + TOL   # 3 cells wide + wrap + BMS
    assert 0.070 - TOL <= ext[1] <= 0.072 + TOL   # cell length
    assert 0.044 - TOL <= ext[2] <= 0.048 + TOL   # 2 cells tall + wrap


def test_fc_stack_builds():
    m = components.fc_stack()
    _built(m)
    assert abs(m.extents[0] - 0.0365) <= TOL      # board width in x
    assert m.bounds[0][2] == pytest.approx(0.0, abs=TOL)  # standoffs at z=0
    assert m.bounds[1][2] >= 0.016 + 0.0016 - TOL  # top board present


def test_motor_height():
    m = components.motor_2806()
    _built(m)
    assert 0.024 <= m.extents[2] <= 0.030
    assert m.bounds[0][2] == pytest.approx(0.0, abs=TOL)


def test_motor_kv_text_variant():
    _built(components.motor_2806(kv_text=True))


def test_propeller_diameter():
    m = components.propeller_7x4_3blade()
    _built(m)
    radial = np.linalg.norm(m.vertices[:, :2], axis=1)
    assert 2.0 * radial.max() == pytest.approx(0.1778, abs=0.002)
    assert max(m.extents[0], m.extents[1]) <= 0.1778 + 0.002  # fits the disk


def test_camera_micro():
    m = components.camera_micro()
    _built(m)
    assert abs(m.extents[1] - 0.019) <= TOL
    assert m.bounds[1][0] >= 0.019 / 2 + 0.008 - TOL  # lens sticks out +x


def test_vtx_antenna():
    m = components.vtx_antenna()
    _built(m)
    assert 0.045 <= m.extents[2] <= 0.055


def test_elrs_dipole():
    m = components.elrs_dipole()
    _built(m)
    assert abs(m.extents[0] - 0.052) <= 0.004      # dipole bar span + caps
    assert m.bounds[1][2] >= 0.04 - TOL


def test_gps_puck():
    m = components.gps_puck()
    _built(m)
    assert abs(m.extents[0] - 0.016) <= TOL
    assert m.extents[2] >= 0.007 - TOL             # box + dome


def test_xt60():
    m = components.xt60()
    _built(m)
    assert m.extents[0] >= 0.016 - TOL             # body + wire boots


def test_wire_l_path():
    m = components.wire([[0, 0, 0], [0.05, 0, 0], [0.05, 0.05, 0]])
    _built(m)
    assert m.extents[0] == pytest.approx(0.05, abs=0.004)
    assert m.extents[1] == pytest.approx(0.05, abs=0.004)
    assert m.is_watertight or len(m.faces) > 100


def test_wire_two_points():
    m = components.wire([[0, 0, 0], [0.02, 0, 0.01]])
    _built(m)


def test_wire_bundle():
    m = components.wire_bundle([[0, 0, 0], [0.04, 0.01, 0.01]], n=3)
    _built(m)
    assert m.extents[1] >= 3 * 2 * 0.0009 - TOL    # wires span sideways
