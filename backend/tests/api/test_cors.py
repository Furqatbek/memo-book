"""CORS is opt-in: no cross-origin access unless CORS_ORIGINS is set."""
import httpx

from app.config import get_settings
from app.main import create_app

PREFLIGHT = {
    "Origin": "https://furqatbek.github.io",
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "content-type,x-edit-token,if-match",
}


async def test_disabled_by_default(client):
    resp = await client.options("/api/v1/books", headers=PREFLIGHT)
    assert "access-control-allow-origin" not in resp.headers


async def test_configured_origin_allowed(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://furqatbek.github.io")
    get_settings.cache_clear()
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            ok = await c.options("/api/v1/books", headers=PREFLIGHT)
            other = await c.options("/api/v1/books", headers={
                **PREFLIGHT, "Origin": "https://evil.example"})
    finally:
        get_settings.cache_clear()
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "https://furqatbek.github.io"
    allowed = ok.headers["access-control-allow-headers"].lower()
    assert "x-edit-token" in allowed and "if-match" in allowed
    assert "access-control-allow-origin" not in other.headers
