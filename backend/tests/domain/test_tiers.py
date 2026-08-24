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
    assert issue.details["shortfall"] == 6
    assert issue.details["have"] == 10


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
    # A63: the tier is sheets of paper; double-sided printing gives two
    # designed pages per sheet.
    assert SHEET_TIERS == (16, 32, 48, 96)
    assert page_tiers() == (32, 64, 96, 192)
    assert pages_for_sheets(16) == 32


def test_books_from_before_sheet_counting_still_validate():
    # Their stored page counts must keep loading, saving and pricing.
    for legacy in LEGACY_PAGE_TIERS:
        assert validate_tier(legacy) == legacy


class TestLayoutAwareEligibility:
    """A67: one photo is no longer one page — a grid page holds four and a
    photo across the fold fills two, so what matters is empty pages."""

    def test_a_book_of_spreads_is_complete_with_half_the_photos(self):
        result = checkout_eligibility(photo_count=16, page_count=32,
                                      empty_pages=0, unplaced_photos=0)
        assert result.eligible
        assert result.issues == ()

    def test_grids_can_need_more_photos_than_pages(self):
        # Four-up pages ate every photo and most pages are still bare.
        result = checkout_eligibility(photo_count=32, page_count=32,
                                      empty_pages=24, unplaced_photos=0)
        assert not result.eligible
        issue = result.issues[0]
        assert issue.code == ErrorCode.PHOTOS_INSUFFICIENT
        assert issue.details["shortfall"] == 24

    def test_enough_photos_but_not_placed_yet_is_still_eligible(self):
        """This endpoint answers the tier question — "have you enough photos
        for a book this size". Placing them is the editor's banner to nag
        about, and checkout's own blank-page gate to refuse."""
        result = checkout_eligibility(photo_count=32, page_count=32,
                                      empty_pages=32, unplaced_photos=32)
        assert result.eligible
        assert result.issues == ()

    def test_spare_photos_still_suggest_a_bigger_book(self):
        result = checkout_eligibility(photo_count=40, page_count=32,
                                      empty_pages=0, unplaced_photos=8)
        assert result.eligible
        assert result.suggested_tier == 64

    def test_without_layout_detail_it_assumes_one_photo_per_page(self):
        assert checkout_eligibility(photo_count=32, page_count=32).eligible
        assert not checkout_eligibility(photo_count=31, page_count=32).eligible
