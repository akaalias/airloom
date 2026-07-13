"""Frame generator: the real Source One V6 assembly and its validity rules."""
import numpy as np

from airloom.frame_gen import build_frame
from airloom.genome import Genome


def test_baseline_reproduces_the_real_v6(cfg):
    """Gene scales at 1.0 must rebuild the actual Source One V6 7in DC."""
    frame = build_frame(Genome.baseline(), cfg.platform)
    assert frame.valid, frame.failure_reason
    assert frame.mesh is not None and frame.mesh.is_watertight
    # the real V6 7" frame weighs ~145 g in carbon
    assert 0.120 < frame.frame_mass < 0.175
    assert frame.material.name == "cf_plate"
    # front rotor positions registered from the official drawing (~mm exact)
    front = max(frame.rotor_centers, key=lambda r: r[0])
    assert abs(front[0] - 0.180) < 0.004 and abs(abs(front[1]) - 0.096) < 0.004
    for name in ("deck", "arms", "battery", "stack", "wiring", "camera",
                 "antennas", "motors", "props"):
        assert frame.parts.get(name) is not None, name


def test_gap_must_fit_stack(cfg):
    g = Genome.baseline().as_dict()
    g["deck_gap"] = 0.020  # < 22.6 mm stack + margin
    frame = build_frame(Genome.from_dict(g), cfg.platform)
    assert not frame.valid
    assert "stack" in frame.failure_reason


def test_tongue_collision_rejected(cfg):
    g = Genome.baseline().as_dict()
    g["front_sweep_deg"] = 30.0
    g["rear_sweep_deg"] = 34.0
    g["arm_width_scale"] = 1.4  # fat arms at converging sweeps must collide
    frame = build_frame(Genome.from_dict(g), cfg.platform)
    assert not frame.valid
    assert "tongue" in frame.failure_reason or "rotor" in frame.failure_reason


def test_morph_changes_mass_and_stays_buildable(cfg):
    g = Genome.baseline().as_dict()
    g.update(arm_length_scale=1.3, arm_waist_scale=0.7, plate_length_scale=1.1)
    frame = build_frame(Genome.from_dict(g), cfg.platform)
    assert frame.mesh is not None
    base = build_frame(Genome.baseline(), cfg.platform)
    assert frame.frame_mass != base.frame_mass


def test_random_genomes_always_mesh(cfg):
    rng = np.random.default_rng(123)
    valid = 0
    for _ in range(10):
        frame = build_frame(Genome.random(rng), cfg.platform)
        assert frame.mesh is not None or not frame.valid
        valid += frame.valid
    assert valid >= 1  # the space is not degenerate


def test_meshless_prescreen_matches_constraints(cfg):
    """want_mesh=False must reproduce the geometric verdicts without meshing."""
    ok = build_frame(Genome.baseline(), cfg.platform, want_mesh=False)
    assert ok.valid and ok.mesh is None and ok.arm is not None

    g = Genome.baseline().as_dict()
    g["deck_gap"] = 0.020
    bad = build_frame(Genome.from_dict(g), cfg.platform, want_mesh=False)
    assert not bad.valid and "stack" in bad.failure_reason
    assert bad.mesh is None


def test_plate_web_collapse_rejected(cfg):
    """Shrinking plates around the pinned stack holes crushes the material
    webs between features -- the exact geometry a run champion exploited."""
    g = Genome.baseline().as_dict()
    g["plate_length_scale"] = 0.93
    g["plate_width_scale"] = 0.94
    frame = build_frame(Genome.from_dict(g), cfg.platform, want_mesh=False)
    assert not frame.valid and "web" in frame.failure_reason


def test_printed_plates_need_minimum_thickness(cfg):
    g = Genome.baseline().as_dict()
    g["material"] = 0.25          # pa12_cf (printed)
    g["plate_thickness_scale"] = 0.7   # 1.4 mm < the 1.6 mm printed floor
    frame = build_frame(Genome.from_dict(g), cfg.platform, want_mesh=False)
    assert not frame.valid and "too thin" in frame.failure_reason

    g["material"] = 0.05          # cf_plate: 1.2 mm floor -> 1.4 mm passes
    frame = build_frame(Genome.from_dict(g), cfg.platform, want_mesh=False)
    assert frame.failure_reason is None or "thin" not in frame.failure_reason
