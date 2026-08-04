import pytest

from app.domain.errors import AmountMismatch
from app.domain.money import assert_amount_matches, from_minor, to_minor


def test_minor_unit_roundtrip():
    for major in (0, 1, 149, 1_500_000):
        for minor_part in (0, 1, 99):
            amount = to_minor(major, minor_part)
            assert isinstance(amount, int)
            assert from_minor(amount) == (major, minor_part)


@pytest.mark.parametrize("call", [
    lambda: to_minor(10.0),
    lambda: to_minor(10, 5.0),
    lambda: from_minor(1000.0),
    lambda: assert_amount_matches(100.0, 100),
    lambda: assert_amount_matches(100, 100.0),
])
def test_floats_are_rejected_everywhere(call):
    with pytest.raises(TypeError):
        call()


def test_amount_mismatch_rejected():
    with pytest.raises(AmountMismatch) as exc:
        assert_amount_matches(expected_minor=14_900_000, received_minor=14_800_000)
    assert exc.value.details == {"expected_minor": 14_900_000, "received_minor": 14_800_000}


def test_matching_amount_passes():
    assert_amount_matches(14_900_000, 14_900_000)  # must not raise


def test_invalid_minor_part_rejected():
    with pytest.raises(ValueError):
        to_minor(10, 100)
    with pytest.raises(ValueError):
        to_minor(-1)
