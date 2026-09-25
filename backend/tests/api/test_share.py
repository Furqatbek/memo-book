"""CR-003-1 — the shareable draft link.

A share link is the one secret in this system that is MEANT to be
forwarded. It will end up in group chats, screenshotted, and pasted
somewhere public by somebody who did not think about it first. So the
tests here are not about whether the happy path works; they are about the
size of the blast radius when the link escapes, which it will.

What must remain true no matter who is holding the token:

  * it cannot change anything;
  * it cannot reach a print-resolution file, an original, or the
    customer's contact details;
  * revoking it works immediately, and takes the pictures with it;
  * an expired draft's link is dead, like the draft.
"""
import io
import uuid

import anyio
import pytest
from PIL import Image
from sqlalchemy import select

from app import storage
from app.models.book import Book
from app.render.preview import SHARE_MAX_EDGE_PX
from app.services import share as svc
from tests.api.test_books import auth, make_book
from tests.api.test_checkout import CUSTOMER
from tests.render.helpers import seed_rendered_book


async def shared_book(client, db, pages: int = 16) -> tuple[str, dict, str]:
    """A rendered book with a live share link. (book_id, owner headers, token)"""
    book_id = await seed_rendered_book(db, client, pages)
    row = (await db.execute(
        select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
    headers = {"X-Edit-Token": row.edit_token}
    resp = await client.post(f"/api/v1/books/{book_id}/share", headers=headers)
    assert resp.status_code == 200, resp.text
    return book_id, headers, resp.json()["share_token"]


class TestTheToken:
    async def test_it_is_thirty_two_random_bytes(self, client, db):
        _, _, token = await shared_book(client, db, 16)
        # token_urlsafe(32) is 43 characters. Anything materially shorter
        # would be guessable at the rate a rate limiter permits.
        assert len(token) >= 43

    async def test_two_books_never_share_a_token(self, client, db):
        _, _, first = await shared_book(client, db, 16)
        _, _, second = await shared_book(client, db, 16)
        assert first != second

    async def test_it_is_not_the_edit_token_or_the_telegram_token(
            self, client, db):
        """Three secrets, three powers. If any two were ever the same value,
        handing somebody the weakest would hand them the strongest."""
        book_id, headers, token = await shared_book(client, db, 16)
        row = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
        link = await client.get(f"/api/v1/books/{book_id}/telegram-link",
                                headers=headers)
        assert link.status_code == 200
        assert token != row.edit_token
        assert token not in link.text

    async def test_asking_twice_returns_the_same_link(self, client, db):
        """The owner has already sent this to their family. Opening the panel
        again must not quietly break the link they sent."""
        book_id, headers, first = await shared_book(client, db, 16)
        again = await client.post(f"/api/v1/books/{book_id}/share",
                                  headers=headers)
        assert again.status_code == 200
        assert again.json()["share_token"] == first


class TestWhatAStrangerCanDo:
    async def test_the_json_is_pages_and_nothing_else(self, client, db):
        book_id, headers, token = await shared_book(client, db, 16)
        await client.patch(f"/api/v1/books/{book_id}/email",
                           json={"email": "owner@example.com"},
                           headers=headers)

        body = (await client.get(f"/api/v1/shared/{token}")).json()
        assert set(body) == {"title", "subtitle", "page_count", "cover_url",
                             "pages"}
        assert len(body["pages"]) == 16
        blob = repr(body)
        # The things a forwarded link must never carry with it.
        row = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
        assert row.edit_token not in blob
        assert "owner@example.com" not in blob
        assert "photo_id" not in blob

    async def test_the_page_carries_noindex(self, client, db):
        _, _, token = await shared_book(client, db, 16)
        for path in (f"/api/v1/shared/{token}", f"/s/{token}"):
            resp = await client.get(path)
            assert resp.status_code == 200, path
            assert "noindex" in resp.headers["x-robots-tag"], path

    async def test_the_html_carries_this_books_cover_in_its_og_card(
            self, client, db):
        """The Telegram preview card IS the advertisement. A generic image
        here is a wasted share, which is the whole point of the feature."""
        book_id, _, token = await shared_book(client, db, 16)
        html = (await client.get(f"/s/{token}")).text
        assert 'property="og:image"' in html
        assert f"books/{book_id}/share/cover.jpg" in html

    async def test_the_images_are_low_resolution(self, client, db):
        """144 DPI is enough to admire and useless to print. A share link
        that leaked a printable file would be giving the product away."""
        book_id, _, token = await shared_book(client, db, 16)
        await client.get(f"/api/v1/shared/{token}")
        data = await anyio.to_thread.run_sync(
            storage.get_bytes, f"books/{book_id}/share/page-0.jpg")
        img = Image.open(io.BytesIO(data))
        img.load()
        # The CR sets a ceiling of 1200px on the long edge. Asserted against
        # the ceiling itself rather than against a DPI that happens to land
        # near it — which is how the first version of this was 25px over
        # while its own comment said it was inside.
        assert max(img.width, img.height) <= SHARE_MAX_EDGE_PX, (
            f"share pages are {img.width}x{img.height}, over the "
            f"{SHARE_MAX_EDGE_PX}px ceiling")
        # And not so small that the advertisement looks cheap.
        assert max(img.width, img.height) >= SHARE_MAX_EDGE_PX - 8


class TestWhatAStrangerCannotDo:
    """The CR asks for 403 on every write endpoint. This system answers 404
    instead, everywhere, on purpose (A72/A96): a wrong token is indistinct
    from a book that does not exist, so a holder of the share token cannot
    even confirm the book is real. That is strictly stronger than 403, and
    these tests assert the stronger thing."""

    @pytest.mark.parametrize("method,path,body", [
        ("patch", "/layout", {"pages": [], "cover": {}}),
        ("patch", "/page-count", {"page_count": 32}),
        ("patch", "/email", {"email": "attacker@example.com"}),
        ("post", "/auto-place", {}),
        ("post", "/preview", None),
        ("post", "/share", None),
        ("delete", "/share", None),
        ("post", "/checkout", CUSTOMER),
    ])
    async def test_the_share_token_is_not_an_edit_token(
            self, client, db, method, path, body):
        book_id, _, token = await shared_book(client, db, 16)
        call = getattr(client, method)
        kwargs = {"headers": {"X-Edit-Token": token, "If-Match": "1"}}
        if body is not None:
            kwargs["json"] = body
        resp = await call(f"/api/v1/books/{book_id}{path}", **kwargs)
        assert resp.status_code == 404, (
            f"{method.upper()} {path} answered {resp.status_code} to a share "
            "token; a read-only secret must not reach a write endpoint")

    async def test_it_cannot_read_the_book(self, client, db):
        book_id, _, token = await shared_book(client, db, 16)
        resp = await client.get(f"/api/v1/books/{book_id}",
                                headers={"X-Edit-Token": token})
        assert resp.status_code == 404

    async def test_it_cannot_reach_the_print_files_or_originals(
            self, client, db):
        """Every URL the viewer is handed points at the share derivative.
        Not the preview, not the display copy, and certainly not the 300dpi
        interior that the printer works from."""
        book_id, _, token = await shared_book(client, db, 16)
        body = (await client.get(f"/api/v1/shared/{token}")).json()
        urls = [body["cover_url"], *(p["url"] for p in body["pages"])]
        for url in urls:
            assert f"books/{book_id}/share/" in url, url
            for forbidden in ("/orig/", "/print/", "/preview/", "/display/"):
                assert forbidden not in url, f"{forbidden} reachable via {url}"

    async def test_an_unknown_token_is_a_404_not_a_hint(self, client, db):
        await shared_book(client, db, 16)
        for bad in ("nope", "a" * 43, "x" * 200):
            assert (await client.get(f"/api/v1/shared/{bad}")).status_code == 404
            assert (await client.get(f"/s/{bad}")).status_code == 404


class TestRevoking:
    async def test_off_means_off_immediately(self, client, db):
        book_id, headers, token = await shared_book(client, db, 16)
        assert (await client.get(f"/api/v1/shared/{token}")).status_code == 200

        resp = await client.delete(f"/api/v1/books/{book_id}/share",
                                   headers=headers)
        assert resp.status_code == 204
        assert (await client.get(f"/api/v1/shared/{token}")).status_code == 404
        assert (await client.get(f"/s/{token}")).status_code == 404

    async def test_the_pictures_go_too(self, client, db):
        """Leaving the images in storage would make "revoke" a lie about
        the thing the owner actually wanted removed."""
        book_id, headers, _ = await shared_book(client, db, 16)
        key = f"books/{book_id}/share/page-0.jpg"
        assert await anyio.to_thread.run_sync(storage.object_exists, key)

        await client.delete(f"/api/v1/books/{book_id}/share", headers=headers)
        assert not await anyio.to_thread.run_sync(storage.object_exists, key)
        assert not await anyio.to_thread.run_sync(
            storage.object_exists, f"books/{book_id}/share/cover.jpg")

    async def test_re_sharing_after_a_revoke_mints_a_new_token(
            self, client, db):
        """The old link stays dead. Somebody was removed from the audience
        and re-issuing their token would put them back in it."""
        book_id, headers, old = await shared_book(client, db, 16)
        await client.delete(f"/api/v1/books/{book_id}/share", headers=headers)
        again = await client.post(f"/api/v1/books/{book_id}/share",
                                  headers=headers)
        new = again.json()["share_token"]
        assert new != old
        assert (await client.get(f"/api/v1/shared/{old}")).status_code == 404
        assert (await client.get(f"/api/v1/shared/{new}")).status_code == 200


class TestExpiry:
    async def test_an_expired_draft_kills_its_share_link(self, client, db):
        """R6 deletes an expired draft's photographs. A share link that
        outlived them would serve a book of broken images — or worse, keep
        serving pictures of a family who believe their draft is gone."""
        book_id, _, token = await shared_book(client, db, 16)
        row = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
        row.status = "expired"
        await db.commit()

        assert (await client.get(f"/api/v1/shared/{token}")).status_code == 404
        assert (await client.get(f"/s/{token}")).status_code == 404


class TestStaleness:
    async def test_an_edited_book_is_re_rendered_for_the_viewer(
            self, client, db):
        """The link is meant to be live — "look at what I'm making" is the
        use case, and a viewer seeing yesterday's pages makes the owner look
        like they stopped."""
        book_id, headers, token = await shared_book(client, db, 16)
        row = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
        rendered_at = row.share_layout_version
        assert rendered_at == row.layout_version

        book = (await client.get(f"/api/v1/books/{book_id}",
                                 headers=headers)).json()
        layout = book["layout"]
        layout["cover"]["title"] = "SAMARKAND"
        patched = await client.patch(f"/api/v1/books/{book_id}/layout",
                                     json=layout,
                                     headers={**headers,
                                              "If-Match": str(book["layout_version"])})
        assert patched.status_code == 200

        body = (await client.get(f"/api/v1/shared/{token}")).json()
        assert body["title"] == "SAMARKAND"
        await db.refresh(row)
        assert row.share_layout_version > rendered_at


class TestCounting:
    async def test_views_are_counted(self, client, db):
        """The number is shown to the owner, so it has to be real. Nothing
        in this product displays a figure it made up."""
        book_id, headers, token = await shared_book(client, db, 16)
        for _ in range(3):
            await client.get(f"/api/v1/shared/{token}")
        row = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
        await db.refresh(row)
        assert row.share_view_count == 3

    async def test_an_unshared_book_has_no_link(self, client, db):
        book = await make_book(client, 16)
        row = (await db.execute(
            select(Book).where(
                Book.id == uuid.UUID(book["book_id"])))).scalar_one()
        assert row.share_token is None
        assert auth(book)["X-Edit-Token"] == row.edit_token


class TestTheUrl:
    def test_share_url_needs_no_trailing_slash_juggling(self, monkeypatch):
        from app.config import get_settings

        monkeypatch.setenv("PUBLIC_BASE_URL", "https://rspixel.uz/")
        get_settings.cache_clear()
        assert svc.share_url("abc") == "https://rspixel.uz/s/abc"
        get_settings.cache_clear()
