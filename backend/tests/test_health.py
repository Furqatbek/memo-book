"""Milestone 1: /health is dependency-free; /ready reports each dependency."""
import httpx
import pytest

from app.config import get_settings


@pytest.fixture
async def health_client(monkeypatch):
    # Point every dependency at an unroutable address so readiness fails fast
    # and deterministically, even on a machine where the real stack is up.
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("READY_CHECK_TIMEOUT_S", "0.5")
    get_settings.cache_clear()
    from app.main import create_app

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    get_settings.cache_clear()


async def test_health_is_alive_without_dependencies(health_client):
    resp = await health_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_ready_reports_each_dependency_when_down(health_client):
    resp = await health_client.get("/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert set(body["checks"]) == {"database", "redis", "storage"}
    for status in body["checks"].values():
        assert status.startswith("error")
