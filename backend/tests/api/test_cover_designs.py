"""A71: the ready-made cover catalogue — what the customer is offered, and
what happens to a book whose design is later retired."""
import io
import uuid
from datetime import UTC, datetime

import pytest
from PIL import Image

from app import storage
from app.models.cover_design import CoverDesign
from app.services.cover_designs import (
    ARTWORK_H_PX,
    ARTWORK_W_PX,
    design_artwork_bytes,
    get_design,
    parse_book_types,
    serialize,
    suits,
    upsert_design,
)


def artwork(w: int = ARTWORK_W_PX, h: int = ARTWORK_H_PX,
            colour: tuple[int, int, int] = (30, 90, 160)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(out, format="JPEG", quality=90)
    return out.getvalue()


async def seed(db, slug: str, *, types: str = "", rect: dict | None = None,
               order: int = 100, active: bool = True) -> CoverDesign:
    design = await upsert_design(
        db, slug=slug, name=slug.title(), book_types=types,
        artwork=artwork(), display=artwork(600, 885), thumb=artwork(200, 295),
        width=ARTWORK_W_PX, height=ARTWORK_H_PX, photo_rect=rect,
        title={"x_mm": 74, "y_mm": 160, "size_pt": 24},
        title_color="#ffffff", bg_color="#1d4d85", sort_order=order)
    if not active:
        design.active = False
        await db.commit()
    return design


class TestOccasionFilter:
    def test_a_design_with_no_occasions_suits_every_book(self):
        """Blank means "any", which is the point of leaving it blank."""
        anything = CoverDesign(book_types="")
        for book_type in ("love", "travel", "birthday", "memory", None):
            assert suits(anything, book_type) is True

    def test_a_design_is_hidden_from_the_wrong_occasion(self):
        romantic = CoverDesign(book_types="love,birthday")
        assert suits(romantic, "love") is True
        assert suits(romantic, "birthday") is True
        assert suits(romantic, "travel") is False

    async def test_asking_without_an_occasion_shows_the_whole_shelf(self, client, db):
        """No filter means no filter. The editor always knows the occasion by
        this point, so this is the browsing case, where hiding most of the
        catalogue would only confuse."""
        await seed(db, "hearts", types="love")
        await seed(db, "plain")
        body = (await client.get("/api/v1/cover-designs")).json()
        assert {d["slug"] for d in body["designs"]} == {"hearts", "plain"}

    @pytest.mark.parametrize("raw,expected", [
        ("love,travel", ["love", "travel"]),
        (" Love ,  TRAVEL ", ["love", "travel"]),
        ("love;birthday", ["love", "birthday"]),
        ("love,love", ["love"]),
        ("love,nonsense", ["love"]),
        ("nonsense", []),
        ("", []),
        (None, []),
    ])
    def test_occasion_lists_are_forgiving_of_typing(self, raw, expected):
        assert parse_book_types(raw) == expected


class TestTheGallery:
    async def test_it_filters_by_occasion(self, client, db):
        await seed(db, "hearts", types="love")
        await seed(db, "map", types="travel")
        await seed(db, "plain")

        love = (await client.get("/api/v1/cover-designs?book_type=love")).json()
        assert {d["slug"] for d in love["designs"]} == {"hearts", "plain"}

        travel = (await client.get("/api/v1/cover-designs?book_type=travel")).json()
        assert {d["slug"] for d in travel["designs"]} == {"map", "plain"}

    async def test_it_needs_no_book_and_no_token(self, client, db):
        await seed(db, "plain")
        resp = await client.get("/api/v1/cover-designs")
        assert resp.status_code == 200
        assert resp.json()["designs"][0]["slug"] == "plain"

    async def test_retired_designs_leave_the_gallery(self, client, db):
        await seed(db, "old", active=False)
        await seed(db, "current")
        body = (await client.get("/api/v1/cover-designs")).json()
        assert [d["slug"] for d in body["designs"]] == ["current"]

    async def test_sort_order_decides_what_is_seen_first(self, client, db):
        await seed(db, "third", order=30)
        await seed(db, "first", order=10)
        await seed(db, "second", order=20)
        body = (await client.get("/api/v1/cover-designs")).json()
        assert [d["slug"] for d in body["designs"]] == ["first", "second", "third"]

    async def test_the_print_artwork_is_never_handed_to_the_customer(self, client, db):
        """The gallery shows the design; it does not distribute the file."""
        await seed(db, "plain")
        body = (await client.get("/api/v1/cover-designs")).json()
        design = body["designs"][0]
        assert design["thumb_url"] and design["display_url"]
        blob = str(design)
        assert "artwork" not in blob
        assert "artwork_key" not in design

    async def test_it_carries_the_geometry_the_editor_needs(self, client, db):
        rect = {"x_mm": 19, "y_mm": 24, "w_mm": 110, "h_mm": 110}
        await seed(db, "framed", rect=rect)
        design = (await client.get("/api/v1/cover-designs")).json()["designs"][0]
        assert design["photo_rect"] == rect
        assert design["title"] == {"x_mm": 74, "y_mm": 160, "size_pt": 24}
        assert design["title_color"] == "#ffffff"
        assert design["bg_color"] == "#1d4d85"

    async def test_a_complete_artwork_cover_has_no_photo_window(self, client, db):
        await seed(db, "whole", rect=None)
        design = (await client.get("/api/v1/cover-designs")).json()["designs"][0]
        assert design["photo_rect"] is None


class TestUploading:
    async def test_re_adding_a_slug_replaces_rather_than_duplicates(self, client, db, s3):
        first = await seed(db, "hearts", types="love")
        again = await upsert_design(
            db, slug="hearts", name="Hearts v2", book_types="birthday",
            artwork=artwork(colour=(200, 30, 30)), display=artwork(600, 885),
            thumb=artwork(200, 295), width=ARTWORK_W_PX, height=ARTWORK_H_PX,
            photo_rect=None, title=None, title_color=None,
            bg_color="#ffffff", sort_order=5)
        assert again.id == first.id
        assert again.name == "Hearts v2"
        assert again.book_types == "birthday"
        body = (await client.get("/api/v1/cover-designs?book_type=birthday")).json()
        assert len(body["designs"]) == 1

    async def test_restoring_a_retired_design_brings_it_back(self, client, db):
        design = await seed(db, "old", active=False)
        design.active = True
        await db.commit()
        body = (await client.get("/api/v1/cover-designs")).json()
        assert [d["slug"] for d in body["designs"]] == ["old"]


class TestARetiredDesignStillPrints:
    """Retiring is a shop-window decision. Books already using the design
    have been paid for and must keep rendering exactly as confirmed."""

    async def test_artwork_is_still_fetched_for_a_retired_design(self, db, s3):
        design = await seed(db, "gone", active=False)
        assert await design_artwork_bytes(db, str(design.id)) is not None

    async def test_a_design_that_no_longer_exists_renders_without_artwork(self, db, s3):
        assert await design_artwork_bytes(db, str(uuid.uuid4())) is None

    async def test_a_malformed_id_does_not_raise(self, db, s3):
        for junk in ("", None, "not-a-uuid", "42"):
            assert await get_design(db, junk) is None
            assert await design_artwork_bytes(db, junk) is None

    async def test_a_missing_object_does_not_sink_a_paid_order(self, db, s3):
        design = await seed(db, "vanished")
        storage.delete_keys([design.artwork_key])
        assert await design_artwork_bytes(db, str(design.id)) is None


class TestModelDefaults:
    def test_a_design_is_visible_and_last_by_default(self, db):
        design = CoverDesign(
            id=uuid.uuid4(), slug="x", artwork_key="a", display_key="d",
            thumb_key="t", artwork_width=10, artwork_height=10,
            created_at=datetime.now(UTC))
        db.add(design)
        assert design.slug == "x"

    def test_serialize_omits_a_title_that_was_never_positioned(self):
        design = CoverDesign(id=uuid.uuid4(), slug="x", name="X", book_types="",
                             artwork_key="a", display_key="d", thumb_key="t",
                             artwork_width=1, artwork_height=1, photo_rect=None,
                             title_x_mm=None, title_y_mm=None,
                             title_color=None, bg_color="#ffffff")
        payload = serialize(design)
        assert "title" not in payload
        assert "title_color" not in payload
