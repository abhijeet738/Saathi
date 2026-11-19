"""Shared test setup. Tests never use real keys, a real database, or the network."""

import os
import sys
from pathlib import Path

import pytest

# Make `import app...` work no matter where pytest is started from.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Fake settings. Assigned (not setdefault) so a real key in your shell can never leak into tests.
TEST_API_KEY = "test-key-0123456789abcdef"
os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:5432/test"
os.environ["SAATHI_API_KEY"] = TEST_API_KEY
os.environ["GEMINI_API_KEY"] = "test-gemini-key"


@pytest.fixture(autouse=True)
def block_database(monkeypatch):
    """Fail loudly if a unit test tries to reach the database.

    db.ping() swallows the error and reports "database down", so health tests still work.
    """

    def _blocked():
        raise RuntimeError("unit tests must not use the database")

    monkeypatch.setattr("app.db.get_pool", _blocked)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


@pytest.fixture
def auth():
    """Headers that pass the API-key check."""
    return {"X-API-Key": TEST_API_KEY}
