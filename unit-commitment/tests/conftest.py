"""Shared pytest setup: make the `solver` package importable and expose the data directory."""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def data_dir() -> str:
    """Absolute path of the directory holding power_plants.json and entsoe_2023.json."""
    return str(PROJECT_ROOT / "data")
