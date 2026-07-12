"""Frame generator: validity checks and watertightness (7-inch plate-deck)."""
import numpy as np

from framevo.frame_gen import build_frame
from framevo.genome import Genome


def test_baseline_frame_is_valid_and_watertight(cfg):
    frame = build_frame(Genome.baseline(), cfg.platform)
    assert frame.valid, frame.failure_reason
    assert frame.mesh is not None and frame.mesh.is_watertight
    # a 7-inch-class plate frame: plausible mass band
    assert 0.05 < frame.frame_mass < 0.40
    assert frame.total_mass == frame.frame_mass + cfg.platform.fixed_mass_kg
    assert frame.material.name == "cf_plate"
    # labeled parts exist for colored rendering (evolved + fixed)
    for name in ("deck", "arms", "battery", "motors", "props"):
        assert frame.parts.get(name) is not None


def test_top_plate_must_support_battery(cfg):
    g = Genome.baseline().as_dict()
    # narrower than 55% of the 66 mm battery footprint
    g["body_width"] = 0.036
    frame = build_frame(Genome.from_dict(g), cfg.platform)
    assert not frame.valid
    assert "battery" in frame.failure_reason
    # instructive failures are still meshed and archived
    assert frame.mesh is not None


def test_fc_mount_needs_flat_area(cfg):
    g = Genome.baseline().as_dict()
    # supports the battery (>= 36.3 mm) but the fillet eats the FC flat
    g["body_width"] = 0.038
    g["body_fillet"] = 0.004
    frame = build_frame(Genome.from_dict(g), cfg.platform)
    assert not frame.valid
    assert "flight-controller" in frame.failure_reason


def test_rotor_clearances(cfg):
    g = Genome.baseline().as_dict()
    g["arm_length"] = 0.08
    g["arm_sweep_deg"] = 25.0  # short arms, front pair nearly parallel
    frame = build_frame(Genome.from_dict(g), cfg.platform)
    assert not frame.valid
    assert "rotor" in frame.failure_reason

    g = Genome.baseline().as_dict()
    g["arm_length"] = 0.08
    g["body_length"] = 0.24
    g["body_width"] = 0.09
    frame = build_frame(Genome.from_dict(g), cfg.platform)
    assert not frame.valid
    assert "rotor" in frame.failure_reason


def test_random_genomes_always_mesh(cfg):
    rng = np.random.default_rng(123)
    for _ in range(25):
        frame = build_frame(Genome.random(rng), cfg.platform)
        assert frame.mesh is not None, frame.failure_reason
        assert frame.mesh.is_watertight or not frame.valid
