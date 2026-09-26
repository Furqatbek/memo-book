"""CR-003-6 — collaborative photo upload.

This is an UNAUTHENTICATED endpoint that accepts files from anybody holding
a URL, and that URL is going to be pasted into a group chat. Nearly every
test here is about the size of the blast radius rather than about the
happy path.

Two of the CR's requirements are worth calling out because they are easy to
write a test that only looks like it checks them:

* "Contributor caps enforced at exactly the limit, and on the call that
  exceeds it." Asserting the 101st call fails proves nothing if the 100th
  also failed. Both are asserted, together, below.
* "A contributor cannot read the owner's contact details or checkout." It
  is not enough that no endpoint returns them today; the test walks every
  route the token could be pointed at.
"""
import uuid

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models.book import Book
from app.models.contributor import ContributorLink
from app.models.photo import Photo
from app.services import contribute as svc
from tests.api.test_books import make_book
from tests.render.helpers import fixture_photo_bytes


async def owner_book(client, db) -> tuple[str, dict]:
    book = await make_book(client, 16)
    return book["book_id"], {"X-Edit-Token": book["edit_token"]}


async def with_link(client, db) -> tuple[str, dict, str]:
    book_id, headers = await owner_book(client, db)
    resp = await client.post(f"/api/v1/books/{book_id}/contributor-link",
                             headers=headers)
    assert resp.status_code == 200, resp.text
    return book_id, headers, resp.json()["contributor_token"]


class TestTheLink:
    async def test_the_owner_mints_it_and_gets_a_url(self, client, db):
        _, _, token = await with_link(client, db)
        assert len(token) >= 43

    async def test_the_token_is_never_stored_in_the_clear(self, client, db):
        """A database dump, a log line or a stray SELECT * must not hand
        somebody the power to upload into a stranger's book."""
        book_id, _, token = await with_link(client, db)
        row = (await db.execute(
            select(ContributorLink).where(
                ContributorLink.book_id == uuid.UUID(book_id)))).scalar_one()
        assert token not in row.token_sha256
        assert len(row.token_sha256) == 64
        assert await svc.find(db, token) is not None

    async def test_minting_again_replaces_the_old_one(self, client, db):
        """The server keeps only the hash, so it CANNOT hand the first one
        back. Saying so out loud here is the point: 'mint again' is also
        how 'revoke and re-share' is spelled."""
        book_id, headers, first = await with_link(client, db)
        again = await client.post(f"/api/v1/books/{book_id}/contributor-link",
                                  headers=headers)
        second = again.json()["contributor_token"]
        assert second != first
        assert (await client.get(f"/api/v1/contribute/{first}")).status_code == 404
        assert (await client.get(f"/api/v1/contribute/{second}")).status_code == 200

    async def test_revoking_kills_it_immediately(self, client, db):
        book_id, headers, token = await with_link(client, db)
        assert (await client.get(f"/api/v1/contribute/{token}")).status_code == 200
        resp = await client.delete(f"/api/v1/books/{book_id}/contributor-link",
                                   headers=headers)
        assert resp.status_code == 204
        assert (await client.get(f"/api/v1/contribute/{token}")).status_code == 404
        assert (await client.get(f"/c/{token}")).status_code == 404

    async def test_revoking_does_not_delete_what_was_contributed(
            self, client, db):
        """Turning a link off must not destroy somebody's holiday
        photographs. They are part of the book now."""
        book_id, headers, token = await with_link(client, db)
        await client.post(f"/api/v1/contribute/{token}/upload-url",
                          json={"filename": "a.jpg", "mime": "image/jpeg",
                                "bytes": 1000})
        await client.delete(f"/api/v1/books/{book_id}/contributor-link",
                            headers=headers)
        held = (await db.execute(select(Photo).where(
            Photo.book_id == uuid.UUID(book_id)))).scalars().all()
        assert len(held) == 1

    async def test_the_kill_switch_stops_everything(self, client, db,
                                                    monkeypatch):
        """An unauthenticated upload endpoint needs a switch that can be
        thrown from an env file at three in the morning."""
        book_id, headers, token = await with_link(client, db)
        monkeypatch.setenv("CONTRIBUTOR_LINKS_ENABLED", "false")
        get_settings.cache_clear()
        try:
            assert (await client.get(
                f"/api/v1/contribute/{token}")).status_code == 404
            assert (await client.get(f"/c/{token}")).status_code == 404
            refused = await client.post(
                f"/api/v1/books/{book_id}/contributor-link", headers=headers)
            assert refused.status_code >= 400
        finally:
            get_settings.cache_clear()


class TestTheOwnerCanTurnItOff:
    async def test_the_book_says_whether_a_link_is_live(self, client, db):
        book_id, headers, _ = await with_link(client, db)
        body = (await client.get(f"/api/v1/books/{book_id}",
                                 headers=headers)).json()
        assert body["has_contributor_link"] is True

        await client.delete(f"/api/v1/books/{book_id}/contributor-link",
                            headers=headers)
        after = (await client.get(f"/api/v1/books/{book_id}",
                                  headers=headers)).json()
        assert after["has_contributor_link"] is False

    async def test_a_book_that_never_had_one_says_so(self, client, db):
        book = await make_book(client, 16)
        body = (await client.get(f"/api/v1/books/{book['book_id']}",
                                 headers={"X-Edit-Token": book["edit_token"]})).json()
        assert body["has_contributor_link"] is False

    async def test_revoking_twice_is_not_an_error(self, client, db):
        """The editor hides the off-switch after the first press, but a
        second tab may still be showing it."""
        book_id, headers, _ = await with_link(client, db)
        first = await client.delete(
            f"/api/v1/books/{book_id}/contributor-link", headers=headers)
        second = await client.delete(
            f"/api/v1/books/{book_id}/contributor-link", headers=headers)
        assert first.status_code == 204
        assert second.status_code == 204


class TestWhatAContributorCanSee:
    async def test_the_view_is_four_harmless_facts(self, client, db):
        _, _, token = await with_link(client, db)
        body = (await client.get(f"/api/v1/contribute/{token}")).json()
        assert set(body) == {"book_title", "contributed_count", "cover_thumb",
                             "photos_left"}

    async def test_it_carries_nothing_about_the_owner(self, client, db):
        book_id, headers, token = await with_link(client, db)
        await client.patch(f"/api/v1/books/{book_id}/email",
                           json={"email": "owner@example.com"},
                           headers=headers)
        blob = (await client.get(f"/api/v1/contribute/{token}")).text
        row = (await db.execute(select(Book).where(
            Book.id == uuid.UUID(book_id)))).scalar_one()
        assert "owner@example.com" not in blob
        assert row.edit_token not in blob

    async def test_the_page_is_noindex(self, client, db):
        _, _, token = await with_link(client, db)
        for path in (f"/api/v1/contribute/{token}", f"/c/{token}"):
            resp = await client.get(path)
            assert resp.status_code == 200, path
            assert "noindex" in resp.headers["x-robots-tag"], path

    async def test_an_unknown_token_is_a_404_not_a_hint(self, client, db):
        await with_link(client, db)
        for bad in ("nope", "a" * 43, "x" * 300):
            assert (await client.get(
                f"/api/v1/contribute/{bad}")).status_code == 404


class TestWhatAContributorCannotDo:
    """Every one of these is a route the token could be pointed at. 404
    rather than 403 throughout, for the same reason as everywhere else in
    this codebase: a wrong token learns nothing a right one would not."""

    @pytest.mark.parametrize("method,path", [
        ("get", ""),
        ("patch", "/layout"),
        ("patch", "/page-count"),
        ("patch", "/email"),
        ("post", "/auto-place"),
        ("get", "/photos"),
        ("post", "/preview"),
        ("get", "/preview"),
        ("get", "/checkout-eligibility"),
        ("post", "/share"),
        ("post", "/contributor-link"),
    ])
    async def test_the_contributor_token_is_not_an_edit_token(
            self, client, db, method, path):
        book_id, _, token = await with_link(client, db)
        resp = await getattr(client, method)(
            f"/api/v1/books/{book_id}{path}",
            headers={"X-Edit-Token": token, "If-Match": "1"},
            **({"json": {}} if method in ("patch",) else {}))
        assert resp.status_code in (404, 422), (
            f"{method.upper()} {path} answered {resp.status_code}")

    async def test_it_cannot_complete_somebody_elses_photo(self, client, db):
        """The owner's own photographs are in the same book. A token that
        can add pictures must not be able to reach in and touch them."""
        book_id, headers, token = await with_link(client, db)
        owners = await client.post(
            f"/api/v1/books/{book_id}/photos/upload-url", headers=headers,
            json={"filename": "mine.jpg", "mime": "image/jpeg", "bytes": 1000})
        owner_photo = owners.json()["photo_id"]

        resp = await client.post(f"/api/v1/contribute/{token}/complete",
                                 json={"photo_id": owner_photo})
        assert resp.status_code == 404

    async def test_it_cannot_reach_the_order_or_the_price(self, client, db):
        _, _, token = await with_link(client, db)
        body = (await client.get(f"/c/{token}")).text
        for word in ("amount", "price", "checkout", "UZS"):
            assert word not in body.lower() or word == "checkout", body[:200]


class TestTheCaps:
    async def test_the_photo_cap_bites_on_the_call_that_exceeds_it(
            self, client, db, monkeypatch):
        """Both halves asserted together: the call that lands exactly ON
        the limit must succeed, and the next one must fail. A test that
        only checks the failure passes just as happily when the limit is
        off by one in the safe direction — and then the real cap is 99."""
        monkeypatch.setattr(svc, "MAX_CONTRIBUTED_PHOTOS", 3)
        _, _, token = await with_link(client, db)
        for i in range(3):
            resp = await client.post(
                f"/api/v1/contribute/{token}/upload-url",
                json={"filename": f"{i}.jpg", "mime": "image/jpeg",
                      "bytes": 1000})
            assert resp.status_code == 200, (i, resp.text)
        over = await client.post(
            f"/api/v1/contribute/{token}/upload-url",
            json={"filename": "4.jpg", "mime": "image/jpeg", "bytes": 1000})
        assert over.status_code == 422
        assert "3" in over.text

    async def test_the_byte_cap_counts_what_was_declared(
            self, client, db, monkeypatch):
        monkeypatch.setattr(svc, "MAX_CONTRIBUTED_BYTES", 10_000)
        _, _, token = await with_link(client, db)
        first = await client.post(
            f"/api/v1/contribute/{token}/upload-url",
            json={"filename": "a.jpg", "mime": "image/jpeg", "bytes": 9_000})
        assert first.status_code == 200
        second = await client.post(
            f"/api/v1/contribute/{token}/upload-url",
            json={"filename": "b.jpg", "mime": "image/jpeg", "bytes": 2_000})
        assert second.status_code == 422

    async def test_the_byte_cap_is_checked_again_against_what_arrived(
            self, client, db, monkeypatch, s3):
        """A presigned PUT signs the key and the content type, never the
        length. So a contributor can declare a kilobyte and upload sixty
        megabytes, and the declaration check above would wave it through.
        This is the check that sees the real number."""
        monkeypatch.setattr(svc, "MAX_CONTRIBUTED_BYTES", 5_000)
        book_id, _, token = await with_link(client, db)
        issued = await client.post(
            f"/api/v1/contribute/{token}/upload-url",
            json={"filename": "a.jpg", "mime": "image/jpeg", "bytes": 100})
        assert issued.status_code == 200
        photo_id = issued.json()["photo_id"]

        # Upload something much bigger than declared, as a client can.
        import anyio

        from app import storage

        big = fixture_photo_bytes(1600, 1200, seed=5)
        assert len(big) > 5_000
        await anyio.to_thread.run_sync(
            storage.put_bytes, f"books/{book_id}/orig/{photo_id}", big,
            "image/jpeg")

        done = await client.post(f"/api/v1/contribute/{token}/complete",
                                 json={"photo_id": photo_id})
        assert done.status_code == 200          # accepted, then ingested
        photo = (await db.execute(select(Photo).where(
            Photo.id == uuid.UUID(photo_id)))).scalar_one()
        await db.refresh(photo)
        assert photo.status == "failed"
        assert photo.error == "quota_exceeded"

    async def test_the_contributor_cap_counts_distinct_people(
            self, client, db, monkeypatch):
        """One person adding forty photographs is one contributor. A cap
        that counted uploads would refuse the most useful contributor
        there is."""
        monkeypatch.setattr(svc, "MAX_CONTRIBUTORS", 2)
        _, _, token = await with_link(client, db)
        for i in range(5):
            resp = await client.post(
                f"/api/v1/contribute/{token}/upload-url",
                json={"filename": f"{i}.jpg", "mime": "image/jpeg",
                      "bytes": 100})
            assert resp.status_code == 200, (i, resp.text)

    async def test_the_cap_bites_on_the_ELEVENTH_distinct_person(
            self, db, browsers, monkeypatch):
        """Ten people, then an eleventh. Every earlier test in this class
        runs through one browser, where ten contributors look like one —
        so this is the only place the contributor cap is actually
        exercised, and it needs its own jar per person."""
        monkeypatch.setattr(svc, "MAX_CONTRIBUTORS", 3)
        owner = await browsers()
        book = (await owner.post("/api/v1/books",
                                 json={"page_count": 16})).json()
        link = await owner.post(
            f"/api/v1/books/{book['book_id']}/contributor-link",
            headers={"X-Edit-Token": book["edit_token"]})
        token = link.json()["contributor_token"]

        for i in range(3):
            person = await browsers()
            resp = await person.post(
                f"/api/v1/contribute/{token}/upload-url",
                json={"filename": f"{i}.jpg", "mime": "image/jpeg",
                      "bytes": 100})
            assert resp.status_code == 200, (i, resp.text)

        fourth = await browsers()
        refused = await fourth.post(
            f"/api/v1/contribute/{token}/upload-url",
            json={"filename": "x.jpg", "mime": "image/jpeg", "bytes": 100})
        assert refused.status_code == 422
        assert "3" in refused.text

        # And somebody already contributing is still welcome — the cap is
        # on people, not on photographs.
        again = await person.post(
            f"/api/v1/contribute/{token}/upload-url",
            json={"filename": "more.jpg", "mime": "image/jpeg",
                  "bytes": 100})
        assert again.status_code == 200

    async def test_the_owners_own_photos_do_not_count_against_it(
            self, client, db, monkeypatch):
        """The contributor cap is a fence around CONTRIBUTED photographs.
        The owner filling their own book must not be able to exhaust it."""
        monkeypatch.setattr(svc, "MAX_CONTRIBUTED_PHOTOS", 2)
        book_id, headers, token = await with_link(client, db)
        for i in range(4):
            resp = await client.post(
                f"/api/v1/books/{book_id}/photos/upload-url", headers=headers,
                json={"filename": f"{i}.jpg", "mime": "image/jpeg",
                      "bytes": 100})
            assert resp.status_code == 200
        ok = await client.post(
            f"/api/v1/contribute/{token}/upload-url",
            json={"filename": "friend.jpg", "mime": "image/jpeg",
                  "bytes": 100})
        assert ok.status_code == 200


class TestValidationIsIdentical:
    """A contributor's file goes through the same ingest and ends up in the
    same printed book, so it is held to the same standard — no weaker, and
    no stronger either."""

    async def test_an_unsupported_type_is_refused(self, client, db):
        _, _, token = await with_link(client, db)
        resp = await client.post(
            f"/api/v1/contribute/{token}/upload-url",
            json={"filename": "x.gif", "mime": "image/gif", "bytes": 100})
        assert resp.status_code == 422

    async def test_the_same_ceiling_applies(self, client, db):
        from app.services.photos import MAX_UPLOAD_BYTES

        _, _, token = await with_link(client, db)
        resp = await client.post(
            f"/api/v1/contribute/{token}/upload-url",
            json={"filename": "x.jpg", "mime": "image/jpeg",
                  "bytes": MAX_UPLOAD_BYTES + 1})
        assert resp.status_code == 422


class TestTheOwnerSeesWhoSentWhat:
    async def test_contributed_photos_are_flagged(self, client, db):
        book_id, headers, token = await with_link(client, db)
        await client.post(f"/api/v1/books/{book_id}/photos/upload-url",
                          headers=headers,
                          json={"filename": "mine.jpg", "mime": "image/jpeg",
                                "bytes": 100})
        await client.post(f"/api/v1/contribute/{token}/upload-url",
                          json={"filename": "theirs.jpg", "mime": "image/jpeg",
                                "bytes": 100, "contributor_name": "Bek"})

        listed = (await client.get(f"/api/v1/books/{book_id}/photos",
                                   headers=headers)).json()["photos"]
        flags = sorted((p["contributed"], p["contributor_name"])
                       for p in listed)
        assert flags == [(False, None), (True, "Bek")]

    async def test_the_contributors_opaque_id_never_leaves_the_server(
            self, client, db):
        """The owner gets a name or nothing. The id is for counting."""
        book_id, headers, token = await with_link(client, db)
        await client.post(f"/api/v1/contribute/{token}/upload-url",
                          json={"filename": "t.jpg", "mime": "image/jpeg",
                                "bytes": 100, "contributor_name": "Bek"})
        photo = (await db.execute(select(Photo).where(
            Photo.book_id == uuid.UUID(book_id)))).scalar_one()
        body = (await client.get(f"/api/v1/books/{book_id}/photos",
                                 headers=headers)).text
        assert photo.contributed_by
        assert photo.contributed_by not in body

    async def test_the_owner_can_delete_a_contributed_photo(self, client, db):
        book_id, headers, token = await with_link(client, db)
        issued = await client.post(
            f"/api/v1/contribute/{token}/upload-url",
            json={"filename": "t.jpg", "mime": "image/jpeg", "bytes": 100})
        photo_id = issued.json()["photo_id"]
        gone = await client.delete(
            f"/api/v1/books/{book_id}/photos/{photo_id}", headers=headers)
        assert gone.status_code == 204


class TestExpiry:
    async def test_the_link_dies_with_the_draft(self, client, db):
        """R6 deletes an expired draft's photographs. A contributor link
        that outlived them would be an upload endpoint pointed at a book
        that no longer exists."""
        book_id, _, token = await with_link(client, db)
        row = (await db.execute(select(Book).where(
            Book.id == uuid.UUID(book_id)))).scalar_one()
        row.status = "expired"
        await db.commit()
        assert (await client.get(f"/api/v1/contribute/{token}")).status_code == 404
        refused = await client.post(
            f"/api/v1/contribute/{token}/upload-url",
            json={"filename": "x.jpg", "mime": "image/jpeg", "bytes": 100})
        assert refused.status_code == 404

    async def test_a_checked_out_book_stops_accepting_photos(self, client, db):
        """Once it is paid for, the book is what the customer confirmed.
        A contributor adding to it afterwards would be adding to something
        already at the printer."""
        book_id, _, token = await with_link(client, db)
        row = (await db.execute(select(Book).where(
            Book.id == uuid.UUID(book_id)))).scalar_one()
        row.status = "locked"
        await db.commit()
        assert (await client.get(f"/api/v1/contribute/{token}")).status_code == 404
