from __future__ import annotations

from pathlib import Path

import pytest

from novacart_datagen.config import ALL_COMPONENTS, Config
from novacart_datagen.generate import run_generate
from novacart_datagen.world import World


@pytest.fixture(scope="session")
def cfg() -> Config:
    # XS, ale z okresem obejmującym anomalie (>= 14 dni) i Black Friday
    return Config.from_scale("xs", days=40)


@pytest.fixture(scope="session")
def world(cfg: Config) -> World:
    return World(cfg)


@pytest.fixture(scope="session")
def dataset(tmp_path_factory: pytest.TempPathFactory, cfg: Config) -> Path:
    out = tmp_path_factory.mktemp("xs1")
    run_generate(cfg, str(out), ALL_COMPONENTS, workers=1)
    return out


@pytest.fixture(scope="session")
def dataset_parallel(tmp_path_factory: pytest.TempPathFactory, cfg: Config) -> Path:
    out = tmp_path_factory.mktemp("xs3")
    run_generate(cfg, str(out), ALL_COMPONENTS, workers=3)
    return out
