import pytest

from app.domain.errors import DomainError, ErrorCode
from app.domain.tiers import PAGE_TIERS, checkout_eligibility, validate_tier


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
    result = checkout_eligibility(photo_count=40, page_count=32)
    assert result.eligible
    assert result.suggested_tier == 48


def test_surplus_on_largest_tier_suggests_nothing():
    result = checkout_eligibility(photo_count=200, page_count=96)
    assert result.eligible
    assert result.suggested_tier is None


@pytest.mark.parametrize("bad_tier", [0, 15, 17, 64, 100, -16])
def test_invalid_tier_rejected(bad_tier):
    with pytest.raises(DomainError) as exc:
        validate_tier(bad_tier)
    assert exc.value.code == ErrorCode.INVALID_PAGE_TIER


def test_tiers_are_the_spec_enum():
    assert PAGE_TIERS == (16, 32, 48, 96)
