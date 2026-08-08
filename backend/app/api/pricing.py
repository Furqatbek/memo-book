"""Public price list. The .env PRICE_MINOR_* values are the single source
of truth — the editor fetches them here, so a price change is one .env edit
and a restart, never a frontend deploy."""
from fastapi import APIRouter

from app.domain.tiers import PAGE_TIERS
from app.services.pricing import price_minor_for_tier

router = APIRouter(prefix="/api/v1", tags=["pricing"])


@router.get("/prices")
async def prices() -> dict:
    return {
        "currency": "UZS",
        "prices": {str(tier): price_minor_for_tier(tier) for tier in PAGE_TIERS},
    }
