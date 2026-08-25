"""Pricing: one module, one entry point (spec Part 12 seam for discounts).
Amounts are integers in tiyin. Values come from config — PLACEHOLDERS until
the founder sets real prices.

Prices are quoted per SHEET tier (PRICE_MINOR_16 is the 16-sheet book), so
the .env keys keep matching what the customer picks. Books ordered before
sheet-counting stored a page count straight from those same numbers, so they
fall back to a lookup by page count and keep their original price (A63).
"""
from app.config import get_settings
from app.domain.errors import DomainError, ErrorCode
from app.domain.tiers import sides_per_sheet, validate_tier


def prices_confirmed() -> bool:
    """Has anybody said these numbers are the real ones? (A74)"""
    return bool(get_settings().prices_confirmed)


def require_sellable_prices() -> None:
    """Refuse to turn a placeholder into somebody's bill.

    A price nobody has confirmed is still a number, and the whole checkout
    path would happily charge it. This is the one place that says no — it
    fails closed, so forgetting `PRICES_CONFIRMED=true` costs a deploy, not
    the margin on every book sold until somebody notices.
    """
    if not prices_confirmed():
        raise DomainError(
            ErrorCode.PRICES_NOT_CONFIRMED,
            "we are not taking orders just yet — the prices shown are not "
            "final. Your book is saved; nothing has been charged.",
        )


def _price_table() -> dict[int, int]:
    settings = get_settings()
    return {
        16: settings.price_minor_16,
        32: settings.price_minor_32,
        48: settings.price_minor_48,
        96: settings.price_minor_96,
    }


def price_minor_for_tier(page_count: int) -> int:
    validate_tier(page_count)
    prices = _price_table()
    sheets = page_count // sides_per_sheet()
    # A book with the same number of printed sides costs the same, whether it
    # was created as N sheets or (before sheet-counting) as N pages.
    amount = prices.get(sheets) or prices.get(page_count)
    if not isinstance(amount, int) or amount <= 0:
        raise ValueError(f"price for a {page_count}-page book is not configured")
    return amount
