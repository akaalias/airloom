"""Sanity anchor from the spec: a conventional 220 mm-class X frame at
~1.1 kg all-up mass must hover at a plausible 180-280 W (electrical)."""
from framevo.frame_gen import build_frame
from framevo.genome import Genome


def test_hover_power_at_reference_mass(rotor):
    n, power = rotor.hover(1.1, rho=1.225)
    assert 180.0 <= power <= 280.0, f"hover power {power:.0f} W out of band"
    # and the rotors must have headroom left at hover
    assert n < rotor.max_rps * 0.75


def test_baseline_genome_is_220_class(cfg, rotor):
    """The baseline genome is a conventional X frame; with the fixed 5-inch
    stack its own AUW hovers below the 1.1 kg reference, so hover power must
    fall at or below the reference band's ceiling and stay plausible."""
    frame = build_frame(Genome.baseline(), cfg.platform)
    assert frame.valid
    # motor-to-motor diagonal ~ 2x(arm reach): 220 mm class means 200-300 mm
    import numpy as np
    diag = float(np.linalg.norm(frame.rotor_centers[0] - frame.rotor_centers[3]))
    assert 0.20 < diag < 0.34
    _, power = rotor.hover(frame.total_mass, rho=1.225)
    assert 80.0 < power < 280.0
