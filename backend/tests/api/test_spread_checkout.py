"""A67: a book laid out as spreads is complete with half as many photos as
pages, and must be orderable — the old one-photo-per-page gate refused it."""
import uuid

from app.domain.geometry import BLEED_MM, TRIM_H_MM, TRIM_W_MM
from app.services.placement import layout_progress

SPREAD_W = 2 * TRIM_W_MM + 2 * BLEED_MM


def spread_pair(photo_id: str, spread_id: str) -> tuple[dict, dict]:
    """The two halves of one photo crossing the fold."""
    base = {"photo_id": photo_id, "y_mm": -BLEED_MM, "w_mm": SPREAD_W,
            "h_mm": TRIM_H_MM + 2 * BLEED_MM, "rotation": 0, "fit": "cover",
            "spread_id": spread_id}
    return ({**base, "x_mm": -BLEED_MM},
            {**base, "x_mm": -BLEED_MM - TRIM_W_MM})


def test_layout_progress_counts_a_spread_as_two_filled_pages():
    photo = str(uuid.uuid4())
    left, right = spread_pair(photo, "s1")
    layout = {"cover": {}, "pages": [
        {"index": 0, "placements": [left]},
        {"index": 1, "placements": [right]},
    ]}
    empty, unplaced = layout_progress(layout, {photo})
    assert empty == 0
    assert unplaced == 0        # the one photo is used, on both pages


def test_a_photo_used_only_on_the_cover_is_not_spare():
    cover_photo, page_photo = str(uuid.uuid4()), str(uuid.uuid4())
    layout = {"cover": {"photo_id": cover_photo}, "pages": [
        {"index": 0, "placements": [{"photo_id": page_photo}]},
    ]}
    empty, unplaced = layout_progress(layout, {cover_photo, page_photo})
    assert (empty, unplaced) == (0, 0)


def test_empty_pages_and_spare_photos_are_reported():
    used, spare = str(uuid.uuid4()), str(uuid.uuid4())
    layout = {"cover": {}, "pages": [
        {"index": 0, "placements": [{"photo_id": used}]},
        {"index": 1, "placements": []},
        {"index": 2, "placements": []},
    ]}
    assert layout_progress(layout, {used, spare}) == (2, 1)


async def test_eligibility_endpoint_accepts_a_spread_filled_book(client, db, s3):
    from tests.api.test_checkout import ready_book

    book_id, headers = await ready_book(client, db)
    book = (await client.get(f"/api/v1/books/{book_id}", headers=headers)).json()
    layout = book["layout"]
    # Re-lay the whole book as spreads: half the photos, every page filled.
    photo_ids = [p["photo_id"] for p in book["photos"]]
    pages = layout["pages"]
    for i in range(0, len(pages) - 1, 2):
        left, right = spread_pair(photo_ids[i // 2], f"s{i}")
        pages[i]["placements"] = [left]
        pages[i]["layout"] = "full"
        pages[i + 1]["placements"] = [right]
        pages[i + 1]["layout"] = "full"
    resp = await client.patch(f"/api/v1/books/{book_id}/layout", json=layout,
                              headers={**headers,
                                       "If-Match": str(book["layout_version"])})
    assert resp.status_code == 200, resp.text

    elig = (await client.get(f"/api/v1/books/{book_id}/checkout-eligibility",
                             headers=headers)).json()
    assert elig["eligible"] is True, elig
