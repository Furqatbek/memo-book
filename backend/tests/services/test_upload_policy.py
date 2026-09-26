"""The upload cap lives in a signed policy, not in a promise.

This replaced a presigned PUT, and the reason is worth restating because it
is the kind of hole that reads as a detail: a presigned PUT signs the
bucket, the key and the content type. It says NOTHING about length. So the
size a client declared when it asked for the URL was decorative — it could
promise one megabyte and send five gigabytes, and the first thing that
noticed was the worker reading the object into memory.

A POST policy is a signed document of conditions, and `content-length-range`
is one of them. The storage service checks it against the body before the
object lands.

    WHERE THIS IS ACTUALLY ENFORCED, AND WHAT THESE TESTS THEREFORE PROVE.

    Enforcement belongs to the storage service. `moto` — used by the test
    suite AND by scripts/devserver.py — does NOT enforce
    `content-length-range`: a body far over the limit is accepted with a
    204. That was measured, not assumed, and it means a test that POSTed an
    oversized file here and expected a rejection would pass while proving
    nothing at all.

    So these tests assert the part we are responsible for: that the policy
    we sign CONTAINS the right conditions, with the right numbers, on every
    path. That is also the part that realistically regresses — somebody
    edits the conditions list, or the contributor quota stops being fed in.

    The consequence to keep in mind: in dev and in tests the cap is still
    only enforced by `photos.ingest_photo`'s `head_size` check. That check
    is not a formality and must not be removed.
"""
import base64
import json
import uuid

import pytest

from app import storage
from app.services import contribute
from app.services import photos as svc
from tests.api.test_books import make_book


def policy_of(post: dict) -> dict:
    """The signed document, as the storage service will read it."""
    return json.loads(base64.b64decode(post["fields"]["policy"]))


def length_range(post: dict) -> tuple[int, int]:
    for condition in policy_of(post)["conditions"]:
        if isinstance(condition, list) and condition[0] == "content-length-range":
            return int(condition[1]), int(condition[2])
    raise AssertionError(
        "the signed policy carries no content-length-range — the upload cap "
        f"is unenforced. conditions: {policy_of(post)['conditions']}")


class TestTheSignedPolicy:
    def test_it_pins_a_length_range(self, s3):
        post = storage.presign_post("k/one", "image/jpeg", 1234)
        assert length_range(post) == (1, 1234)

    def test_it_pins_the_content_type(self, s3):
        """Otherwise the key we signed for a JPEG accepts an HTML file,
        which is then served from our own origin."""
        post = storage.presign_post("k/one", "image/jpeg", 10)
        conditions = policy_of(post)["conditions"]
        assert {"Content-Type": "image/jpeg"} in conditions
        assert post["fields"]["Content-Type"] == "image/jpeg"

    def test_it_pins_the_key(self, s3):
        """One credential, one object. A policy that let the key vary would
        be a write credential for the whole bucket."""
        post = storage.presign_post("books/abc/orig/def", "image/jpeg", 10)
        assert post["fields"]["key"] == "books/abc/orig/def"

    def test_it_is_signed_with_sigv4(self, s3):
        """SigV2 policies (`AWSAccessKeyId` + `signature`) are the
        deprecated form — removed in newer AWS regions and not what any
        current S3-compatible service is tested against. The upload cap
        rides on this signature, so it is the last thing that should be
        signed the old way."""
        fields = storage.presign_post("k", "image/jpeg", 10)["fields"]
        assert "x-amz-algorithm" in fields
        assert fields["x-amz-algorithm"] == "AWS4-HMAC-SHA256"
        assert "x-amz-signature" in fields
        assert "AWSAccessKeyId" not in fields

    def test_a_zero_byte_upload_is_outside_the_range(self, s3):
        """An empty file is never a photograph, and letting one land means
        an ingest failure instead of a refusal."""
        low, _ = length_range(storage.presign_post("k", "image/jpeg", 10))
        assert low >= 1


class TestTheOwnersUpload:
    async def test_the_policy_carries_the_global_ceiling(self, client, db, s3):
        book = await make_book(client, 16)
        _, post = await svc.issue_upload_url(
            db, uuid.UUID(book["book_id"]), book["edit_token"],
            "a.jpg", "image/jpeg", 5_000)
        assert length_range(post)[1] == svc.MAX_UPLOAD_BYTES

    async def test_not_the_size_the_client_declared(self, client, db, s3):
        """The declared size is what a lying client controls. Signing THAT
        as the ceiling would hand the cap to the attacker."""
        book = await make_book(client, 16)
        _, post = await svc.issue_upload_url(
            db, uuid.UUID(book["book_id"]), book["edit_token"],
            "a.jpg", "image/jpeg", 12)
        assert length_range(post)[1] != 12


class TestTheContributorsUpload:
    """The most abusable surface in the system gets the tighter policy: the
    book's REMAINING allowance, so a contributor cannot spend more of it
    than they were granted even by ignoring the size they declared."""

    async def _linked_book(self, client, db):
        book = await make_book(client, 16)
        resp = await client.post(
            f"/api/v1/books/{book['book_id']}/contributor-link",
            headers={"X-Edit-Token": book["edit_token"]})
        assert resp.status_code == 200
        return book, resp.json()["contributor_token"]

    async def test_the_policy_is_capped_by_what_is_left(self, client, db, s3,
                                                       monkeypatch):
        monkeypatch.setattr(contribute, "MAX_CONTRIBUTED_BYTES", 40_000)
        book, token = await self._linked_book(client, db)

        first = await client.post(
            f"/api/v1/contribute/{token}/upload-url",
            json={"filename": "a.jpg", "mime": "image/jpeg", "bytes": 30_000})
        assert first.status_code == 200
        # 30 000 of 40 000 declared and reserved, so the NEXT policy may
        # not exceed the 10 000 that remain.
        second = await client.post(
            f"/api/v1/contribute/{token}/upload-url",
            json={"filename": "b.jpg", "mime": "image/jpeg", "bytes": 5_000})
        assert second.status_code == 200
        assert length_range(second.json()["upload"])[1] == 10_000

    async def test_and_never_by_more_than_the_global_ceiling(
            self, client, db, s3, monkeypatch):
        """A generous contributor allowance must not raise the per-file
        ceiling above what ingest can actually process."""
        monkeypatch.setattr(contribute, "MAX_CONTRIBUTED_BYTES",
                            svc.MAX_UPLOAD_BYTES * 100)
        book, token = await self._linked_book(client, db)
        resp = await client.post(
            f"/api/v1/contribute/{token}/upload-url",
            json={"filename": "a.jpg", "mime": "image/jpeg", "bytes": 1_000})
        assert length_range(resp.json()["upload"])[1] == svc.MAX_UPLOAD_BYTES

    async def test_a_full_book_is_refused_before_a_policy_is_signed(
            self, client, db, s3, monkeypatch):
        """Not handed a one-byte policy to fail against. A refusal with a
        reason beats a signed credential that cannot be used."""
        monkeypatch.setattr(contribute, "MAX_CONTRIBUTED_BYTES", 1_000)
        book, token = await self._linked_book(client, db)
        await client.post(
            f"/api/v1/contribute/{token}/upload-url",
            json={"filename": "a.jpg", "mime": "image/jpeg", "bytes": 900})
        refused = await client.post(
            f"/api/v1/contribute/{token}/upload-url",
            json={"filename": "b.jpg", "mime": "image/jpeg", "bytes": 900})
        assert refused.status_code == 422
        assert "upload" not in refused.json()


class TestTheSecondLineOfDefenceIsStillThere:
    """Because in this environment it is the ONLY line. moto accepts a body
    that the policy forbids, so the ingest-time check against what actually
    landed is what catches an oversized upload here — and it is what catches
    one in production if the storage service is ever misconfigured."""

    def test_ingest_still_measures_what_arrived(self):
        import inspect

        source = inspect.getsource(svc.ingest_photo)
        assert "head_size" in source
        assert "MAX_UPLOAD_BYTES" in source

    @pytest.mark.parametrize("name", ["head_size"])
    def test_storage_can_still_measure_an_object(self, name):
        assert callable(getattr(storage, name))

    def test_moto_does_not_enforce_the_policy_so_nobody_is_misled(self, s3):
        """This test exists to be READ. It asserts the gap rather than
        hiding it: if a future moto starts enforcing the range, this fails
        and whoever sees it can delete the belt-and-braces comments with
        confidence instead of guessing."""
        import requests

        post = storage.presign_post("k/probe", "image/jpeg", 10)
        resp = requests.post(post["url"], data=post["fields"],
                             files={"file": ("a.jpg", b"x" * 5_000,
                                             "image/jpeg")})
        assert resp.status_code in (200, 204), (
            "moto now REJECTS an oversized body. Good news: the enforcement "
            "gap these tests document has closed, and the comments about it "
            "can go.")
