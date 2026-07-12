from pathlib import Path

import pytest

from framevo.config import Config, load_config
from framevo.rotor_model import RotorModel

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def cfg() -> Config:
    return load_config(ROOT)


@pytest.fixture(scope="session")
def rotor(cfg: Config) -> RotorModel:
    return RotorModel.from_platform(cfg.platform.propulsion)
