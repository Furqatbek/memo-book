"""GET /payments/dev/config: dev env only — never in prod, even with dev
payments enabled (the pilot's manual-payment mode)."""
import httpx

from app.config import get_settings
from app.main import create_app


async def test_dev_env_exposes_secret(client):
    resp = await client.get("/api/v1/payments/dev/config")
    assert resp.status_code == 200
    assert resp.json()["dev_payment_secret"]


async def test_prod_env_hides_secret(monkeypatch):
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("DEV_PAYMENTS_ENABLED", "true")   # pilot manual mode
    get_settings.cache_clear()
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            resp = await c.get("/api/v1/payments/dev/config")
    finally:
        get_settings.cache_clear()
    assert resp.status_code == 404
