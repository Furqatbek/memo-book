import pytest

from app.domain.errors import DomainError, ErrorCode
from app.domain.tiers import (
    LEGACY_PAGE_TIERS,
    SHEET_TIERS,
    checkout_eligibility,
    page_tiers,
    pages_for_sheets,
    validate_tier,
)


def test_exact_photo_count_is_eligible():
    result = checkout_eligibility(photo_count=16, page_count=16)
    assert result.eligible
    assert result.issues == ()
    assert result.suggested_tier is None


def test_shortfall_is_not_eligible_and_names_the_gap():
    result = checkout_eligibility(photo_count=10, page_count=16)
    assert not result.eligible
    assert result.suggested_tier is None  # 10 photos qualify for no tier
    issue = result.issues[0]
    assert issue.code == ErrorCode.PHOTOS_INSUFFICIENT
    assert issue.details == {"have": 10, "need": 16, "shortfall": 6}


def test_shortfall_suggests_largest_qualifying_tier():
    result = checkout_eligibility(photo_count=40, page_count=48)
    assert not result.eligible
    assert result.suggested_tier == 32


def test_surplus_suggests_next_larger_tier():
    tiers = page_tiers()
    result = checkout_eligibility(photo_count=tiers[1] + 8, page_count=tiers[1])
    assert result.eligible
    assert result.suggested_tier == tiers[2]


def test_surplus_on_largest_tier_suggests_nothing():
    biggest = page_tiers()[-1]
    result = checkout_eligibility(photo_count=biggest + 50, page_count=biggest)
    assert result.eligible
    assert result.suggested_tier is None


@pytest.mark.parametrize("bad_tier", [0, 15, 17, 100, -16])
def test_invalid_tier_rejected(bad_tier):
    with pytest.raises(DomainError) as exc:
        validate_tier(bad_tier)
    assert exc.value.code == ErrorCode.INVALID_PAGE_TIER


def test_customer_buys_sheets_that_yield_twice_as_many_pages():
    # A60: the tier is sheets of paper; double-sided printing gives two
    # designed pages per sheet.
    assert SHEET_TIERS == (16, 32, 48, 96)
    assert page_tiers() == (32, 64, 96, 192)
    assert pages_for_sheets(16) == 32


def test_books_from_before_sheet_counting_still_validate():
    # Their stored page counts must keep loading, saving and pricing.
    for legacy in LEGACY_PAGE_TIERS:
        assert validate_tier(legacy) == legacy
