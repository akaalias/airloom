"""Beam model vs hand-calculated cantilever numbers."""
import math

import numpy as np
import pytest

from airloom.meshutil import polygon_properties
from airloom.structures import (cantilever_deflection, cantilever_stress,
                                first_bending_frequency)

# hand-calculated case: rectangular section w=16 mm, h=8 mm, L=110 mm,
# tip load P=10 N, E=70 GPa
W, H, L, P, E = 0.016, 0.008, 0.110, 10.0, 70.0e9
I_RECT = W * H ** 3 / 12.0                      # 6.8267e-10 m^4
SIGMA_HAND = P * L * (H / 2.0) / I_RECT         # 6.4453e6 Pa
DELTA_HAND = P * L ** 3 / (3.0 * E * I_RECT)    # 9.2865e-5 m


def test_stress_matches_hand_calculation():
    assert cantilever_stress(P, L, I_RECT, H / 2.0) == pytest.approx(6.4453e6, rel=1e-3)


def test_deflection_matches_hand_calculation():
    assert cantilever_deflection(P, L, E, I_RECT) == pytest.approx(9.2865e-5, rel=1e-3)


def test_polygon_second_moment_of_rectangle():
    half_w, half_h = W / 2.0, H / 2.0
    rect = np.array([(half_w, half_h), (-half_w, half_h),
                     (-half_w, -half_h), (half_w, -half_h)])
    area, cy, i_bend = polygon_properties(rect)
    assert area == pytest.approx(W * H, rel=1e-9)
    assert cy == pytest.approx(0.0, abs=1e-12)
    assert i_bend == pytest.approx(I_RECT, rel=1e-9)


def test_first_bending_frequency_formula():
    m_tip, m_arm = 0.032, 0.030
    f1 = first_bending_frequency(L, E, I_RECT, m_tip, m_arm)
    expected = math.sqrt(3 * E * I_RECT / (L ** 3 * (m_tip + 0.243 * m_arm))) \
        / (2 * math.pi)
    assert f1 == pytest.approx(expected, rel=1e-12)
    assert 100.0 < f1 < 600.0  # plausible band for a CF mini-quad arm
