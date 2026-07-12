"""Frame generator: validity checks and watertightness."""
import numpy as np

from framevo.frame_gen import build_frame
from framevo.genome import Genome


def test_baseline_frame_is_valid_and_watertight(cfg):
    frame = build_frame(Genome.baseline(), cfg.platform)
    assert frame.valid, frame.failure_reason
    assert frame.mesh is not None and frame.mesh.is_watertight
    # a 220 mm-class CF frame: plausible mass band
    assert 0.05 < frame.frame_mass < 0.45
    assert frame.total_mass == frame.frame_mass + cfg.platform.fixed_mass_kg


def test_battery_must_fit(cfg):
    g = Genome.baseline().as_dict()
    g["body_width"] = 0.048  # battery is 47 mm wide + walls + clearance
    frame = build_frame(Genome.from_dict(g), cfg.platform)
    assert not frame.valid
    assert "battery" in frame.failure_reason
    # instructive failures are still meshed and archived
    assert frame.mesh is not None


def test_rotor_body_clearance(cfg):
    g = Genome.baseline().as_dict()
    g["arm_length"] = 0.07
    g["body_length"] = 0.24
    g["body_width"] = 0.10
    frame = build_frame(Genome.from_dict(g), cfg.platform)
    assert not frame.valid
    assert "rotor" in frame.failure_reason


def test_rotor_rotor_clearance(cfg):
    g = Genome.baseline().as_dict()
    g["arm_length"] = 0.07
    g["arm_sweep_deg"] = 25.0  # front pair nearly parallel -> disks collide
    frame = build_frame(Genome.from_dict(g), cfg.platform)
    assert not frame.valid
    assert "rotor" in frame.failure_reason


def test_random_genomes_always_mesh(cfg):
    rng = np.random.default_rng(123)
    for _ in range(25):
        frame = build_frame(Genome.random(rng), cfg.platform)
        assert frame.mesh is not None, frame.failure_reason
        assert frame.mesh.is_watertight or not frame.valid
