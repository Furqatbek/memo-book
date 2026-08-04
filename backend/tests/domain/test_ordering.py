"""R2 auto-place ordering — per the spec, the highest-value unit tests in the suite."""
import random
from datetime import UTC, datetime, timedelta

from app.domain.ordering import PhotoForOrdering, auto_place_order

T0 = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def photo(pid: str, taken_offset_h: int | None, uploaded_offset_h: int) -> PhotoForOrdering:
    return PhotoForOrdering(
        id=pid,
        taken_at=None if taken_offset_h is None else T0 + timedelta(hours=taken_offset_h),
        uploaded_at=T0 + timedelta(hours=uploaded_offset_h),
    )


def test_dated_photos_sort_ascending():
    photos = [photo("c", 3, 0), photo("a", 1, 1), photo("b", 2, 2)]
    assert auto_place_order(photos) == ["a", "b", "c"]


def test_undated_photos_come_last_in_upload_order():
    photos = [photo("u2", None, 5), photo("d1", 1, 9), photo("u1", None, 4)]
    assert auto_place_order(photos) == ["d1", "u1", "u2"]


def test_mixed_set_dated_first_then_undated():
    photos = [
        photo("u_late", None, 10),
        photo("d_late", 8, 0),
        photo("u_early", None, 1),
        photo("d_early", 2, 20),
    ]
    assert auto_place_order(photos) == ["d_early", "d_late", "u_early", "u_late"]


def test_identical_taken_at_breaks_ties_by_uploaded_at():
    photos = [photo("second", 5, 2), photo("first", 5, 1)]
    assert auto_place_order(photos) == ["first", "second"]


def test_fully_identical_timestamps_deterministic_by_id():
    photos = [photo("b", 5, 1), photo("a", 5, 1)]
    assert auto_place_order(photos) == ["a", "b"]


def test_output_is_never_random():
    photos = [photo(f"p{i}", i if i % 3 else None, 100 - i) for i in range(50)]
    first = auto_place_order(photos)
    second = auto_place_order(photos)
    assert first == second

    # Determinism must also hold regardless of input order.
    shuffled = photos[:]
    random.Random(1234).shuffle(shuffled)
    assert auto_place_order(shuffled) == first


def test_empty_input():
    assert auto_place_order([]) == []
