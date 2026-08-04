"""Page tiers and checkout eligibility — business rules R1 and R3.

Never allow checkout with fewer photos than pages: blank printed pages are a
guaranteed refund. On surplus, suggest the next larger tier; the backend never
silently drops photos.
"""
from dataclasses import dataclass, field

from app.domain.errors import DomainError, ErrorCode

PAGE_TIERS: tuple[int, ...] = (16, 32, 48, 96)


def validate_tier(page_count: int) -> int:
    if page_count not in PAGE_TIERS:
        raise DomainError(ErrorCode.INVALID_PAGE_TIER,
                          f"page_count must be one of {PAGE_TIERS}",
                          {"page_count": page_count, "allowed": list(PAGE_TIERS)})
    return page_count


def largest_qualifying_tier(photo_count: int) -> int | None:
    """The largest tier the user currently has enough photos for, or None."""
    qualifying = [t for t in PAGE_TIERS if photo_count >= t]
    return max(qualifying) if qualifying else None


def next_larger_tier(page_count: int) -> int | None:
    larger = [t for t in PAGE_TIERS if t > page_count]
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
