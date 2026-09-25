"""The contributor journey, end to end — CR-003-6.

The CR asks for this one by name:

    contributor uploads -> the photo appears in the owner's pool flagged
    as contributed -> the owner places it -> it renders in the final PDF.

Worth having as one test rather than five, because what breaks is never a
step. Each half works and the picture still never reaches the page: the
flag is set but the layout validator rejects the id, or it places and the
renderer cannot find the file. The join is the thing.

Two browsers throughout. A contributor with the owner's cookies is not a
contributor.
"""
import io
import uuid

import anyio
from PIL import Image
from sqlalchemy import select

from app import storage
from app.domain.events import EventType
from app.models.funnel_event import FunnelEvent
from app.models.photo import Photo
from tests.render.helpers import fixture_photo_bytes, full_bleed_page


async def put_upload(book_id: str, photo_id: str, data: bytes) -> None:
    """What the browser's presigned PUT would have done."""
    await anyio.to_thread.run_sync(
        storage.put_bytes, f"books/{book_id}/orig/{photo_id}", data,
        "image/jpeg")


class TestTheWholeJourney:
    async def test_a_friends_photo_ends_up_printed_in_the_book(
            self, db, browsers):
        owner = await browsers()
        friend = await browsers()

        # 1. The owner starts a book and asks for photos.
        book = (await owner.post("/api/v1/books",
                                 json={"page_count": 16})).json()
        book_id = book["book_id"]
        auth = {"X-Edit-Token": book["edit_token"]}
        link = await owner.post(f"/api/v1/books/{book_id}/contributor-link",
                                headers=auth)
        assert link.status_code == 200, link.text
        token = link.json()["contributor_token"]

        # 2. The friend opens the link and adds a photograph. They never
        #    see the book, and they never hold the edit token.
        page = await friend.get(f"/c/{token}")
        assert page.status_code == 200
        assert book["edit_token"] not in page.text

        photo_bytes = fixture_photo_bytes(2000, 1500, seed=7)
        issued = await friend.post(
            f"/api/v1/contribute/{token}/upload-url",
            json={"filename": "bek-on-the-pass.jpg", "mime": "image/jpeg",
                  "bytes": len(photo_bytes), "contributor_name": "Bek"})
        assert issued.status_code == 200, issued.text
        photo_id = issued.json()["photo_id"]
        await put_upload(book_id, photo_id, photo_bytes)
        done = await friend.post(f"/api/v1/contribute/{token}/complete",
                                 json={"photo_id": photo_id})
        assert done.status_code == 200, done.text

        # 3. It appears in the OWNER's pool, flagged, and usable.
        listed = (await owner.get(f"/api/v1/books/{book_id}/photos",
                                  headers=auth)).json()["photos"]
        mine = next(p for p in listed if str(p["photo_id"]) == photo_id)
        assert mine["contributed"] is True
        assert mine["contributor_name"] == "Bek"
        assert mine["status"] == "ready", mine
        assert mine["thumb_url"], "no thumbnail: ingest did not run"

        # 4. The owner places it, exactly as they would their own.
        current = (await owner.get(f"/api/v1/books/{book_id}",
                                   headers=auth)).json()
        layout = current["layout"]
        layout["pages"][0] = full_bleed_page(0, photo_id)
        saved = await owner.patch(
            f"/api/v1/books/{book_id}/layout", json=layout,
            headers={**auth,
                     "If-Match": str(current["layout_version"])})
        assert saved.status_code == 200, saved.text

        # 5. And it is what actually gets drawn on page one.
        from app.render.preview import render_preview_page

        photo = (await db.execute(select(Photo).where(
            Photo.id == uuid.UUID(photo_id)))).scalar_one()
        original = await anyio.to_thread.run_sync(
            storage.get_bytes, photo.original_key)
        drawn = await anyio.to_thread.run_sync(
            render_preview_page, layout["pages"][0], {photo_id: original})
        img = Image.open(io.BytesIO(drawn))
        img.load()
        # A blank page is pure white; the friend's photograph is not.
        assert img.convert("L").getextrema()[0] < 240, (
            "the contributed photo did not reach the page")

    async def test_the_contributor_is_counted_as_a_lead_not_a_customer(
            self, db, browsers):
        """Each contributor experiences the product before buying anything,
        which is the point of the feature — so the event exists, and it is
        about the OWNER's book rather than a book the contributor does not
        have."""
        owner = await browsers()
        friend = await browsers()
        book = (await owner.post("/api/v1/books",
                                 json={"page_count": 16})).json()
        book_id = uuid.UUID(book["book_id"])
        token = (await owner.post(
            f"/api/v1/books/{book['book_id']}/contributor-link",
            headers={"X-Edit-Token": book["edit_token"]}
        )).json()["contributor_token"]

        issued = await friend.post(
            f"/api/v1/contribute/{token}/upload-url",
            json={"filename": "a.jpg", "mime": "image/jpeg", "bytes": 400})
        photo_id = issued.json()["photo_id"]
        await put_upload(str(book_id), photo_id,
                         fixture_photo_bytes(800, 600, seed=3))
        await friend.post(f"/api/v1/contribute/{token}/complete",
                          json={"photo_id": photo_id})

        kinds = (await db.execute(
            select(FunnelEvent.event_type).where(
                FunnelEvent.book_id == book_id))).scalars().all()
        assert EventType.CONTRIBUTOR_LINK_CREATED.value in kinds
        assert EventType.CONTRIBUTOR_UPLOAD.value in kinds

    async def test_the_cta_starts_a_book_attributed_to_the_contribution(
            self, db, browsers):
        """A contributor who liked the experience is the cheapest lead
        there is. If the report cannot tell them from search traffic,
        nobody will know that."""
        owner = await browsers()
        friend = await browsers()
        book = (await owner.post("/api/v1/books",
                                 json={"page_count": 16})).json()
        token = (await owner.post(
            f"/api/v1/books/{book['book_id']}/contributor-link",
            headers={"X-Edit-Token": book["edit_token"]}
        )).json()["contributor_token"]

        page = await friend.get(f"/c/{token}")
        assert "utm_source=contribute" in page.text

        # They follow that link and start their own book.
        await friend.get("/health?utm_source=contribute&utm_medium=share"
                         "&utm_campaign=contribute")
        theirs = await friend.post("/api/v1/books", json={"page_count": 16})
        started = (await db.execute(
            select(FunnelEvent).where(
                FunnelEvent.book_id == uuid.UUID(theirs.json()["book_id"]),
                FunnelEvent.event_type == EventType.BOOK_STARTED.value)
        )).scalar_one()
        assert started.source == "contribute"
        assert started.campaign == "contribute"
