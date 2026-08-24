"""Public price list. The .env PRICE_MINOR_* values are the single source
of truth — the editor fetches them here, so a price change is one .env edit
and a restart, never a frontend deploy.

Tiers are quoted in SHEETS of paper, with the page count each one yields, so
the editor can show both numbers without hardcoding the relationship."""
from fastapi import APIRouter

from app.domain.tiers import SHEET_TIERS, pages_for_sheets, sides_per_sheet
from app.services.pricing import price_minor_for_tier

router = APIRouter(prefix="/api/v1", tags=["pricing"])


@router.get("/prices")
async def prices() -> dict:
    tiers = [
        {"sheets": sheets,
         "pages": pages_for_sheets(sheets),
         "price_minor": price_minor_for_tier(pages_for_sheets(sheets))}
        for sheets in SHEET_TIERS
    ]
    return {
        "currency": "UZS",
        "sides_per_sheet": sides_per_sheet(),
        "tiers": tiers,
        # Kept keyed by sheet tier for the existing editor build.
        "prices": {str(t["sheets"]): t["price_minor"] for t in tiers},
    }
