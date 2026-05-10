"""
tests/conftest.py — Shared fixtures and session-level setup.
"""
import pytest
from pathlib import Path

XLSX_PRESENT = (Path(__file__).parent.parent / "Copy of Cattle_Spreads.xlsx").exists()

requires_xlsx = pytest.mark.skipif(
    not XLSX_PRESENT,
    reason="Copy of Cattle_Spreads.xlsx not present — skipping integration test",
)


@pytest.fixture(scope="session", autouse=True)
def load_data():
    """Load the data store once per test session when the XLSX is available."""
    if XLSX_PRESENT:
        import data
        data.load()


@pytest.fixture
def client():
    """Flask test client."""
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
