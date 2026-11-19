"""Authentication tests: /health is public, everything else needs the API key.

Uses only code that exists in Phase 0. When later phases add real routers, the
"protected" wiring test below already covers them, because they all share `protected`.
"""

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import get_settings
from app.security import require_api_key


@pytest.fixture
def guarded_client():
    """A tiny app with one route guarded the same way main.py guards real routers."""
    router = APIRouter()

    @router.get("/secret")
    def secret():
        return {"ok": True}

    app = FastAPI()
    app.include_router(router, dependencies=[Depends(require_api_key)])
    return TestClient(app)


# --- /health is public ---


def test_health_needs_no_key_and_reports_db_down(client):
    # The autouse fixture blocks the database, so ping() reports it as down.
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "db": False}


def test_health_ok_when_database_answers(client, monkeypatch):
    monkeypatch.setattr("app.routers.health.ping", lambda: True)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": True}


# --- the API-key check itself ---


def test_missing_key_is_rejected(guarded_client):
    assert guarded_client.get("/secret").status_code == 401


def test_wrong_key_is_rejected(guarded_client):
    r = guarded_client.get("/secret", headers={"X-API-Key": "wrong-key-wrong-key"})
    assert r.status_code == 401


def test_correct_key_is_accepted(guarded_client, auth):
    r = guarded_client.get("/secret", headers=auth)
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_empty_key_is_rejected(guarded_client):
    r = guarded_client.get("/secret", headers={"X-API-Key": ""})
    assert r.status_code == 401


def test_non_ascii_key_gives_401_not_a_crash():
    # Called directly: HTTP clients may refuse to send such a header at all.
    with pytest.raises(HTTPException) as exc:
        require_api_key("clé-secrète")
    assert exc.value.status_code == 401


# --- wiring and configuration ---


def test_main_protects_routers_with_the_api_key_check():
    from app.main import protected

    assert protected[0].dependency is require_api_key


def test_too_short_api_key_is_refused_at_startup(monkeypatch):
    monkeypatch.setenv("SAATHI_API_KEY", "short")
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError):
            get_settings()
    finally:
        # Drop the cached result so later tests see the normal test settings again.
        monkeypatch.undo()
        get_settings.cache_clear()
