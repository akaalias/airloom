"""The frame genome: morph parameters over the REAL Source One V6 outlines.

Genes no longer describe primitives -- they deform the official plate
drawings (data/source_one/) under zone constraints that keep every candidate
a plausible, printable derivative of the real design: arm tongues and motor
mounts stay rigid, the 30.5 mm stack pattern stays exact, plates stretch
around their functional regions. Gene value 1.0 (for the scale genes)
reproduces the real V6 part.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

# (name, low, high) -- scales are relative to the real V6 part; lengths in
# meters, angles in degrees.
GENOME_SPEC: tuple[tuple[str, float, float], ...] = (
    ("arm_length_scale", 0.75, 1.35),   # shaft stretch (wheelbase)
    ("arm_width_scale", 0.75, 1.40),    # shaft width at the zone borders
    ("arm_waist_scale", 0.55, 1.30),    # extra narrowing at mid-shaft
    ("arm_thickness", 0.004, 0.009),    # real: 6 mm plate
    ("front_sweep_deg", 30.0, 52.0),    # front arm azimuth from +x (nose)
    ("rear_sweep_deg", 34.0, 62.0),     # rear arm azimuth from -x (tail)
    ("plate_length_scale", 0.85, 1.30),
    ("plate_width_scale", 0.85, 1.25),
    ("deck_gap", 0.020, 0.045),         # standoff length; real: M3x30
    ("battery_wedge_deg", 0.0, 15.0),
    ("plate_thickness_scale", 0.7, 1.6),  # x 2 mm real plates
    ("material", 0.0, 0.999),
)

N_GENES = len(GENOME_SPEC)
GENE_NAMES = tuple(name for name, _, _ in GENOME_SPEC)
LOWER = np.array([lo for _, lo, _ in GENOME_SPEC])
UPPER = np.array([hi for _, _, hi in GENOME_SPEC])
RANGE = UPPER - LOWER

# Generation 0 seed = the actual Source One V6 7in DC: every scale at 1.0,
# 6 mm carbon arms, 2 mm plates, M3x30 standoffs, sweep angles from the
# bolt-hole registration against the main plate, carbon plate material.
BASELINE = {
    "arm_length_scale": 1.0, "arm_width_scale": 1.0, "arm_waist_scale": 1.0,
    "arm_thickness": 0.006, "front_sweep_deg": 31.4, "rear_sweep_deg": 36.0,
    "plate_length_scale": 1.0, "plate_width_scale": 1.0, "deck_gap": 0.030,
    "battery_wedge_deg": 2.0, "plate_thickness_scale": 1.0,
    "material": 0.05,  # cf_plate
}

# human-readable labels + formatting for galleries/tooltips
GENE_FORMAT: tuple[tuple[str, str, str], ...] = (
    ("arm_length_scale", "arm length", "x"),
    ("arm_width_scale", "arm width", "x"),
    ("arm_waist_scale", "arm waist", "x"),
    ("arm_thickness", "arm thickness", "mm"),
    ("front_sweep_deg", "front sweep", "deg"),
    ("rear_sweep_deg", "rear sweep", "deg"),
    ("plate_length_scale", "plate length", "x"),
    ("plate_width_scale", "plate width", "x"),
    ("deck_gap", "deck gap", "mm"),
    ("battery_wedge_deg", "battery wedge", "deg"),
    ("plate_thickness_scale", "plate thickness", "x"),
    ("material", "material", ""),
)


def describe_genome(genes: dict[str, float],
                    material_name: str | None = None) -> list[tuple[str, str]]:
    """(label, formatted value) pairs for display. Scale genes read as
    multiples of the real Source One V6 part ('x1.00' = the real shape)."""
    out = []
    for gene, label, unit in GENE_FORMAT:
        v = genes.get(gene)
        if v is None:
            continue
        if gene == "material":
            out.append((label, material_name or f"{v:.2f}"))
        elif unit == "mm":
            out.append((label, f"{v * 1000:.1f} mm"))
        elif unit == "deg":
            out.append((label, f"{v:.1f}°"))
        elif unit == "x":
            out.append((label, f"×{v:.2f}"))
        else:
            out.append((label, f"{v:.2f}"))
    return out


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
