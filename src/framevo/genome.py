"""The 13-gene continuous frame genome: bounds, hashing, random sampling."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

# (name, low, high) -- all lengths in meters, angles in degrees.
# Sized for the 7-inch DroneAid-kit / TBS-Source-One-style plate-deck class.
# body_* genes describe the deck: plate footprint, standoff gap (height),
# corner fillet, pitch of the battery wedge. `material` selects a
# print/plate material from the platform library (continuous in [0,1),
# floored onto the list -- see Platform.material_for).
GENOME_SPEC: tuple[tuple[str, float, float], ...] = (
    ("arm_length", 0.08, 0.22),
    ("arm_width", 0.009, 0.030),
    ("arm_height", 0.0035, 0.012),
    ("arm_sweep_deg", 25.0, 65.0),
    ("arm_dihedral_deg", -8.0, 8.0),
    ("section_blend", 0.0, 1.0),
    ("arm_taper", 0.5, 1.0),
    ("body_length", 0.090, 0.240),
    ("body_width", 0.036, 0.090),
    ("body_height", 0.020, 0.055),
    ("body_fillet", 0.0, 0.012),
    ("body_pitch_deg", 0.0, 15.0),
    ("thickness_scale", 0.6, 1.8),
    ("material", 0.0, 0.999),
)

N_GENES = len(GENOME_SPEC)
GENE_NAMES = tuple(name for name, _, _ in GENOME_SPEC)
LOWER = np.array([lo for _, lo, _ in GENOME_SPEC])
UPPER = np.array([hi for _, _, hi in GENOME_SPEC])
RANGE = UPPER - LOWER

# A conventional 7-inch-class X deck (Source-One-like proportions, carbon
# plates, ~0.35 m wheelbase); also the seed of generation 0.
BASELINE = {
    "arm_length": 0.135, "arm_width": 0.014, "arm_height": 0.0055,
    "arm_sweep_deg": 45.0, "arm_dihedral_deg": 0.0, "section_blend": 0.25,
    "arm_taper": 0.85, "body_length": 0.150, "body_width": 0.048,
    "body_height": 0.026, "body_fillet": 0.005, "body_pitch_deg": 2.0,
    "thickness_scale": 1.0, "material": 0.05,  # cf_plate
}


@dataclass(frozen=True)
class Genome:
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        assert len(self.values) == N_GENES

    def __getitem__(self, name: str) -> float:
        return self.values[GENE_NAMES.index(name)]

    @property
    def array(self) -> np.ndarray:
        return np.array(self.values)

    @property
    def normalized(self) -> np.ndarray:
        return (self.array - LOWER) / RANGE

    @property
    def hash(self) -> str:
        """Stable 12-hex ID from genes rounded to 1e-6."""
        payload = ",".join(f"{v:.6f}" for v in self.values)
        return hashlib.sha1(payload.encode()).hexdigest()[:12]

    def as_dict(self) -> dict[str, float]:
        return dict(zip(GENE_NAMES, self.values))

    @staticmethod
    def from_array(arr: np.ndarray) -> "Genome":
        clipped = np.clip(np.asarray(arr, dtype=float), LOWER, UPPER)
        return Genome(tuple(float(x) for x in clipped))

    @staticmethod
    def from_normalized(arr: np.ndarray) -> "Genome":
        return Genome.from_array(LOWER + np.clip(arr, 0.0, 1.0) * RANGE)

    @staticmethod
    def from_dict(d: dict[str, float]) -> "Genome":
        return Genome.from_array(np.array([d[n] for n in GENE_NAMES]))

    @staticmethod
    def baseline() -> "Genome":
        return Genome.from_dict(BASELINE)

    @staticmethod
    def random(rng: np.random.Generator) -> "Genome":
        return Genome.from_array(LOWER + rng.random(N_GENES) * RANGE)
