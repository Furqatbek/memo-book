"""Page tiers and checkout eligibility — business rules R1 and R3.

The customer buys **sheets of paper**; each sheet carries `sides_per_sheet`
printed sides (2 with ordinary double-sided printing), and one printed side
is one designed page. Everything downstream — the layout document, the
renderer, the PDF — counts pages, so `page_count` stays the internal unit
and `SHEET_TIERS` is only what the customer picks (A63).

Never allow checkout with a page the photos cannot fill: blank printed pages
are a guaranteed refund. On surplus, suggest the next larger tier; the backend
never silently drops photos.
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


def checkout_eligibility(photo_count: int, page_count: int,
                         empty_pages: int | None = None,
                         unplaced_photos: int | None = None) -> CheckoutEligibility:
    """R1 + R3, counted by what the layout actually needs.

    One photo no longer means one page: a grid page holds four, and a photo
    across the fold fills two (A67). So the question is not "are there as
    many photos as pages" but "does every empty page have a spare photo to
    go on it" — a book laid out entirely as spreads is complete with half as
    many photos as pages.

    Both counts come from the live layout; the defaults describe a book
    nobody has placed anything in yet (every page empty, every photo spare),
    which reduces exactly to the classic `photo_count >= page_count` rule.

    `shortfall` and `leftover` are the two signs of one difference: empty
    pages the photos cannot cover, or photos the pages cannot hold.

    `suggested_tier` means:
    - shortfall: the largest tier the user currently qualifies for (may be None)
    - leftover:  the next larger tier, as an upsell suggestion
    """
    validate_tier(page_count)
    if empty_pages is None:
        empty_pages = page_count
    if unplaced_photos is None:
        unplaced_photos = photo_count

    shortfall = max(0, empty_pages - unplaced_photos)
    if shortfall:
        return CheckoutEligibility(
            eligible=False,
            photo_count=photo_count,
            page_count=page_count,
            issues=(EligibilityIssue(
                code=ErrorCode.PHOTOS_INSUFFICIENT,
                message=f"{shortfall} more photos are needed to fill this book.",
                details={"have": photo_count, "empty_pages": empty_pages,
                         "unplaced_photos": unplaced_photos,
                         "shortfall": shortfall},
            ),),
            suggested_tier=largest_qualifying_tier(photo_count),
        )

    leftover = max(0, unplaced_photos - empty_pages)
    return CheckoutEligibility(
        eligible=True,
        photo_count=photo_count,
        page_count=page_count,
        issues=(),
        suggested_tier=next_larger_tier(page_count) if leftover else None,
    )
