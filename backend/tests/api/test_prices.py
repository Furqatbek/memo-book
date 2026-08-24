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


async def test_prices_expose_sheets_and_the_pages_they_yield(client):
    body = (await client.get("/api/v1/prices")).json()
    assert body["sides_per_sheet"] == 2
    assert [t["sheets"] for t in body["tiers"]] == [16, 32, 48, 96]
    assert [t["pages"] for t in body["tiers"]] == [32, 64, 96, 192]


async def test_photo_mount_binding_reverts_to_one_side_per_sheet(client, monkeypatch):
    """A60: if the printer glues sheets back-to-back, a sheet carries one
    printed side and every tier returns to its original page count."""
    monkeypatch.setenv("SIDES_PER_SHEET", "1")
    get_settings.cache_clear()
    try:
        body = (await client.get("/api/v1/prices")).json()
        assert [t["pages"] for t in body["tiers"]] == [16, 32, 48, 96]
    finally:
        get_settings.cache_clear()


def test_books_from_before_sheet_counting_keep_their_price():
    from app.services.pricing import price_minor_for_tier

    settings = get_settings()
    # A legacy 16-page book has no sheet tier of its own (8 sheets) and must
    # fall back to the price its customer was originally quoted.
    assert price_minor_for_tier(16) == settings.price_minor_16
    # 32 printed sides cost the same however the book was created.
    assert price_minor_for_tier(32) == settings.price_minor_16
