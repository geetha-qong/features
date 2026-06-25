from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def canonical_sample_path() -> Path:
    return FIXTURE_DIR / "canonical_sample.json"
