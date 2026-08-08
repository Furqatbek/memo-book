"""GET /api/v1/prices mirrors the PRICE_MINOR_* configuration."""
from app.config import get_settings


async def test_prices_match_config(client):
    r = await client.get("/api/v1/prices")
    assert r.status_code == 200
    body = r.json()
    settings = get_settings()
    assert body["currency"] == "UZS"
    assert body["prices"] == {
        "16": settings.price_minor_16,
        "32": settings.price_minor_32,
        "48": settings.price_minor_48,
        "96": settings.price_minor_96,
    }
