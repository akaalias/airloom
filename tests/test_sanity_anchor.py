"""Sanity anchors.

1. The original spec anchor: a conventional 220 mm-class 5-inch quad at
   ~1.1 kg all-up mass must hover at a plausible 180-280 W. Checked against
   the cached UIUC GWS DD 5x4.3 dataset directly (the shipped platform is the
   7-inch DroneAid kit, so this pins the *method* to known physics).
2. The shipped 7-inch platform: baseline deck frame is wheelbase-plausible
   and hovers at a plausible power for its ~1 kg AUW.
"""
from pathlib import Path

import numpy as np

from airloom.config import Propulsion
from airloom.frame_gen import build_frame
from airloom.genome import Genome
from airloom.rotor_model import RotorModel

ROOT = Path(__file__).resolve().parent.parent


def _five_inch_rotor() -> RotorModel:
    prop = Propulsion(
        prop_name="GWS DD 5x4.3", prop_diameter_m=0.127, n_rotors=4,
        motor_mass_kg=0.032, motor_esc_efficiency=0.85, max_rpm=28000,
        max_motor_power_w=400, uiuc_data_dir=ROOT / "data" / "uiuc",
        uiuc_static_file="gwsdd_5x4.3_static_0493rd.txt",
        uiuc_dynamic_files=(
            "gwsdd_5x4.3_0511rd_4048.txt", "gwsdd_5x4.3_0512rd_6047.txt",
            "gwsdd_5x4.3_0513rd_8044.txt", "gwsdd_5x4.3_0514rd_8078.txt"),
    )
    return RotorModel.from_platform(prop)


def test_hover_power_5in_at_reference_mass():
    rotor = _five_inch_rotor()
    n, power = rotor.hover(1.1, rho=1.225)
    assert 180.0 <= power <= 280.0, f"hover power {power:.0f} W out of band"
    assert n < rotor.max_rps * 0.75  # headroom left at hover


def test_platform_baseline_is_7in_class(cfg, rotor):
    frame = build_frame(Genome.baseline(), cfg.platform)
    assert frame.valid, frame.failure_reason
    # front-left to rear-right span of the real V6 7in DC stance
    diag = float(np.linalg.norm(frame.rotor_centers[0] - frame.rotor_centers[3]))
    assert 0.28 < diag < 0.42
    # ~1 kg AUW on 7x4 props: plausible hover band for a 7" long-ranger
    n, power = rotor.hover(frame.total_mass, rho=1.225)
    assert 90.0 < power < 230.0
    # and the rotors must have plenty of headroom at hover
    assert n < rotor.max_rps * 0.75