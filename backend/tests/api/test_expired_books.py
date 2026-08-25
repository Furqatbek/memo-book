"""A78: an expired book says it expired.

`ErrorCode.BOOK_EXPIRED` was mapped to HTTP 410 from the first milestone and
raised by nothing. An expired draft answered `BOOK_LOCKED` — "book is locked
and can no longer be edited" — which is the message a book gets after it has
been *bought*. A customer coming back to an abandoned draft was told, in
effect, that they had already ordered it.

The editor has carried three branches handling BOOK_EXPIRED all along. None
of them could ever fire.

What makes this worth a 410 rather than a 404: R6 deletes the photos from
storage when the book expires. There is nothing left to serve, and "not
found" invites the customer to go looking for a link that will never work
again.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.domain.states import BookStatus
from app.models.book import Book
from app.services.lifecycle import expire_drafts
from tests.api.test_books import auth, make_book


@pytest.fixture
async def expired_book(client, db):
    """A real draft run through the real nightly expiry job."""
    book = await make_book(client)
    book_id = book["book_id"]
    row = (await db.execute(
        select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
    row.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db.commit()

    assert await expire_drafts(db) == 1
    await db.refresh(row)
    assert row.status == BookStatus.EXPIRED.value
    return book_id, book


class TestReadingAnExpiredBook:
    async def test_it_is_gone_not_locked(self, client, expired_book):
        book_id, book = expired_book
        resp = await client.get(f"/api/v1/books/{book_id}", headers=auth(book))
        assert resp.status_code == 410
        assert resp.json()["error"]["code"] == "BOOK_EXPIRED"

    async def test_the_message_explains_rather_than_accuses(
            self, client, expired_book):
        """"Locked" reads as "you already bought this". The photos are the
        part the customer needs to know about."""
        book_id, book = expired_book
        message = (await client.get(f"/api/v1/books/{book_id}",
                                    headers=auth(book))).json()["error"]["message"]
        assert "expired" in message.lower()
        assert "photo" in message.lower()

    async def test_a_wrong_token_still_looks_like_a_missing_book(
            self, client, expired_book):
        """Expiry must not become an oracle for which book ids exist: auth
        comes first, and a bad token answers 404 as it always did."""
        book_id, book = expired_book
        resp = await client.get(f"/api/v1/books/{book_id}",
                                headers=auth({"edit_token": "not-the-token"}))
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"


class TestEditingAnExpiredBook:
    async def test_layout_changes_say_expired(self, client, expired_book):
        book_id, book = expired_book
        resp = await client.patch(
            f"/api/v1/books/{book_id}/layout",
            json={"pages": [], "cover": {}, "version": 1},
            headers={**auth(book), "If-Match": "1"})
        assert resp.status_code == 410
        assert resp.json()["error"]["code"] == "BOOK_EXPIRED"

    async def test_checkout_says_expired(self, client, expired_book):
        """The worst version of the old behaviour: being told the book is
        locked while trying to buy it."""
        book_id, book = expired_book
        resp = await client.post(
            f"/api/v1/books/{book_id}/checkout",
            json={"name": "A", "phone": "+998901112233",
                  "address": "Tashkent 1", "confirmed_preview": True},
            headers=auth(book))
        assert resp.status_code == 410
        assert resp.json()["error"]["code"] == "BOOK_EXPIRED"


class TestALiveBookIsUnaffected:
    async def test_a_draft_still_opens(self, client):
        book = await make_book(client)
        assert (await client.get(f"/api/v1/books/{book['book_id']}",
                                 headers=auth(book))).status_code == 200

    async def test_a_locked_book_still_says_locked(self, client, db):
        """The two must stay distinguishable — one means "you bought this",
        the other means "this is gone"."""
        book = await make_book(client)
        book_id = book["book_id"]
        row = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
        row.status = BookStatus.LOCKED.value
        await db.commit()

        resp = await client.patch(
            f"/api/v1/books/{book_id}/layout",
            json={"pages": [], "cover": {}, "version": 1},
            headers={**auth(book), "If-Match": "1"})
        assert resp.status_code == 423
        assert resp.json()["error"]["code"] == "BOOK_LOCKED"


class TestTheCodeIsNotDeadAgain:
    def test_the_editor_still_handles_it(self):
        """The editor's BOOK_EXPIRED branches were unreachable for the whole
        life of the feature. If the backend ever stops sending the code, they
        go back to being decoration — so assert both ends exist."""
        from pathlib import Path

        editor = Path(__file__).resolve().parents[3] / "editor" / "js" / "app.js"
        assert "BOOK_EXPIRED" in editor.read_text(encoding="utf-8"), (
            "the editor no longer handles BOOK_EXPIRED")
