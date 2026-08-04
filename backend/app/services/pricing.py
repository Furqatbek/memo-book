"""Pricing: one module, one entry point (spec Part 12 seam for discounts).
Amounts are integers in tiyin. Values come from config — PLACEHOLDERS until
the founder sets real prices."""
from app.config import get_settings
from app.domain.tiers import validate_tier


def price_minor_for_tier(page_count: int) -> int:
    validate_tier(page_count)
    settings = get_settings()
    prices = {
        16: settings.price_minor_16,
        32: settings.price_minor_32,
        48: settings.price_minor_48,
        96: settings.price_minor_96,
    }
    amount = prices[page_count]
    if not isinstance(amount, int) or amount <= 0:
        raise ValueError(f"price for tier {page_count} is not configured")
    return amount
