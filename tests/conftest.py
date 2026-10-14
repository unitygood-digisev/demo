import datetime as dt
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE_DATE = dt.date(2026, 10, 14)


@pytest.fixture
def root() -> Path:
    return ROOT
