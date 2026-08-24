"""Page tiers and checkout eligibility — business rules R1 and R3.

The customer buys **sheets of paper**; each sheet carries `sides_per_sheet`
printed sides (2 with ordinary double-sided printing), and one printed side
is one designed page. Everything downstream — the layout document, the
renderer, the PDF — counts pages, so `page_count` stays the internal unit
and `SHEET_TIERS` is only what the customer picks (A60).

Never allow checkout with fewer photos than pages: blank printed pages are a
guaranteed refund. On surplus, suggest the next larger tier; the backend never
silently drops photos.
"""
from dataclasses import dataclass, field

from app.config import get_settings
from app.domain.errors import DomainError, ErrorCode

# What the customer chooses, in sheets of paper.
SHEET_TIERS: tuple[int, ...] = (16, 32, 48, 96)

# Books ordered before sheet-counting stored these page counts directly and
# must keep loading, saving and pricing exactly as they always did.
LEGACY_PAGE_TIERS: tuple[int, ...] = (16, 32, 48, 96)


def sides_per_sheet() -> int:
    return max(1, get_settings().sides_per_sheet)


def pages_for_sheets(sheets: int) -> int:
    return sheets * sides_per_sheet()


def page_tiers() -> tuple[int, ...]:
    """Page counts a NEW book may be created with."""
    return tuple(pages_for_sheets(s) for s in SHEET_TIERS)


def _known_page_counts() -> tuple[int, ...]:
    return tuple(sorted(set(page_tiers()) | set(LEGACY_PAGE_TIERS)))


def validate_tier(page_count: int) -> int:
    allowed = _known_page_counts()
    if page_count not in allowed:
        raise DomainError(ErrorCode.INVALID_PAGE_TIER,
                          f"page_count must be one of {allowed}",
                          {"page_count": page_count, "allowed": list(allowed)})
    return page_count


def largest_qualifying_tier(photo_count: int) -> int | None:
    """The largest tier the user currently has enough photos for, or None."""
    qualifying = [t for t in page_tiers() if photo_count >= t]
    return max(qualifying) if qualifying else None


def next_larger_tier(page_count: int) -> int | None:
    larger = [t for t in page_tiers() if t > page_count]
    return min(larger) if larger else None


@dataclass(frozen=True)
class EligibilityIssue:
    code: ErrorCode
    message: str
    details: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CheckoutEligibility:
    eligible: bool
    photo_count: int
    page_count: int
    issues: tuple[EligibilityIssue, ...]
    suggested_tier: int | None


def checkout_eligibility(photo_count: int, page_count: int) -> CheckoutEligibility:
    """R1 + R3. `suggested_tier` means:
    - shortfall: the largest tier the user currently qualifies for (may be None)
    - surplus:   the next larger tier, as an upsell suggestion
    """
    validate_tier(page_count)

    if photo_count < page_count:
        return CheckoutEligibility(
            eligible=False,
            photo_count=photo_count,
            page_count=page_count,
            issues=(EligibilityIssue(
                code=ErrorCode.PHOTOS_INSUFFICIENT,
                message=f"You have {photo_count} photos but the "
                        f"{page_count}-page book needs {page_count}.",
                details={"have": photo_count, "need": page_count,
                         "shortfall": page_count - photo_count},
            ),),
            suggested_tier=largest_qualifying_tier(photo_count),
        )

    suggested = next_larger_tier(page_count) if photo_count > page_count else None
    return CheckoutEligibility(
        eligible=True,
        photo_count=photo_count,
        page_count=page_count,
        issues=(),
        suggested_tier=suggested,
    )
