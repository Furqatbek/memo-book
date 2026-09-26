"""A98: how long a signed URL stays good.

The bucket is private, so every image the browser shows is a presigned URL
with a deadline baked into it. Those deadlines are the kind of constant that
looks arbitrary and is not: each one is sized to the thing it has to
outlive, and getting one wrong fails silently and late.

Display URLs were an hour, and the editor asks for them exactly once — when
the book loads. So a customer who spent ninety minutes arranging their book
watched every thumbnail turn into a broken icon, with nothing on screen to
say why. Nothing errored server-side; the URLs simply aged out while the
page held them.

These tests read the deadline back out of the signature, so they measure
what a browser would actually be handed.
"""
import time
from urllib.parse import parse_qs, urlparse

import pytest

from app import storage

HOUR = 3600


def lifetime_s(url: str) -> int:
    """Seconds of life left in a signed URL, read from the URL itself.

    Both signature versions are handled because the answer must not depend
    on which one boto happens to use: SigV2 carries an absolute `Expires`
    timestamp, SigV4 a relative `X-Amz-Expires`.
    """
    query = parse_qs(urlparse(url).query)
    if "X-Amz-Expires" in query:
        return int(query["X-Amz-Expires"][0])
    return int(query["Expires"][0]) - int(time.time())


def about(seconds: int, hours: float, tolerance_s: int = 90) -> bool:
    return abs(seconds - hours * HOUR) <= tolerance_s


class TestDisplayUrls:
    def test_they_outlive_a_long_editing_session(self, s3):
        """The bug this exists to prevent. Ninety minutes is an ordinary
        amount of time to spend on a photo book, and it used to be enough to
        break every image on the page."""
        assert lifetime_s(storage.presign_get("books/b/photo.jpg")) > 4 * HOUR

    def test_they_last_a_day(self, s3):
        assert about(lifetime_s(storage.presign_get("books/b/photo.jpg")), 24)

    def test_the_default_is_what_callers_get(self, s3):
        """Nearly every caller takes the default — the photos service, the
        preview service and the cover catalogue all call presign_get with
        one argument — so the default IS the customer-facing value."""
        assert about(lifetime_s(storage.presign_get("k")),
                     storage.DISPLAY_URL_EXPIRY_S / HOUR)


class TestUploadCredentials:
    def test_the_policy_expires_within_the_hour(self, s3):
        """An upload credential lets anyone holding it put bytes in our
        bucket. It is used the instant it is issued, so it has no business
        outliving the upload."""
        import base64
        import json

        post = storage.presign_post("books/b/up.jpg", "image/jpeg", 1_000)
        policy = json.loads(base64.b64decode(post["fields"]["policy"]))
        # The expiry is inside the signed document, not in a query string.
        assert policy["expiration"]
        assert storage.UPLOAD_URL_EXPIRY_S <= HOUR

    def test_a_write_credential_never_lives_as_long_as_a_read_one(self, s3):
        assert storage.UPLOAD_URL_EXPIRY_S < storage.DISPLAY_URL_EXPIRY_S

    def test_there_is_no_way_left_to_mint_an_unbounded_upload(self):
        """`presign_put` signed the key and the content type and nothing
        about length, which is what made a declared size decorative. It is
        gone rather than deprecated: left in place it is a loaded gun for
        the next person who needs an upload URL in a hurry."""
        assert not hasattr(storage, "presign_put")


class TestPrintFileUrls:
    def test_they_last_the_week_the_printer_is_promised(self, s3):
        """The Telegram message and the admin console both say "7-day
        link", and the message is the printer's job sheet — it has to still
        work when they get to it."""
        from app.services.admin_orders import ARTIFACT_URL_EXPIRY_S

        url = storage.presign_get("books/b/render/interior.pdf",
                                  ARTIFACT_URL_EXPIRY_S)
        assert about(lifetime_s(url), 24 * 7, tolerance_s=300)

    def test_the_two_telegram_and_console_promise_the_same_week(self):
        """They are separate constants in separate modules, and a printer
        told seven days by one and given four by the other would find out
        on day five."""
        from app.services.admin_orders import ARTIFACT_URL_EXPIRY_S as console
        from app.services.telegram import ARTIFACT_URL_EXPIRY_S as telegram

        assert console == telegram == 7 * 24 * HOUR


class TestNobodyAsksForMoreThanSigV4Allows:
    """SigV4 caps a presigned URL at seven days and REJECTS anything longer
    rather than shortening it. `presign_get` clamps so an invalid URL cannot
    be minted — but a clamp that fires is a caller that was wrong, so this
    names the rule instead of leaving the clamp to absorb it silently."""

    def test_the_ceiling_is_the_protocols_own(self):
        assert storage.MAX_PRESIGN_EXPIRY_S == 7 * 24 * HOUR

    @pytest.mark.parametrize("module,name", [
        ("app.services.admin_orders", "ARTIFACT_URL_EXPIRY_S"),
        ("app.services.telegram", "ARTIFACT_URL_EXPIRY_S"),
        ("app.services.outbox", "REMINDER_PHOTO_EXPIRY_S"),
        ("app.services.share", "VIEW_URL_EXPIRY_S"),
        ("app.services.flip_video", "URL_EXPIRY_S"),
    ])
    def test_every_expiry_constant_is_within_it(self, module, name):
        import importlib

        value = getattr(importlib.import_module(module), name)
        assert value <= storage.MAX_PRESIGN_EXPIRY_S, (
            f"{module}.{name} is {value}s; SigV4 refuses anything over "
            f"{storage.MAX_PRESIGN_EXPIRY_S}s. Anything that must outlive a "
            "week needs a route of ours that re-signs on each visit.")

    def test_the_clamp_catches_one_that_slips_through(self, s3):
        url = storage.presign_get("k", 99 * 24 * HOUR)
        assert lifetime_s(url) <= storage.MAX_PRESIGN_EXPIRY_S


class TestTheOrderingHolds:
    @pytest.mark.parametrize("shorter,longer", [
        ("upload", "display"),
        ("display", "artifact"),
    ])
    def test_each_deadline_is_sized_to_what_it_must_outlive(
            self, s3, shorter, longer):
        """Upload (one request) < display (one sitting) < print file (the
        printer's week). If this ever inverts, one of them was changed
        without thinking about the others."""
        from app.services.admin_orders import ARTIFACT_URL_EXPIRY_S

        spans = {
            "upload": storage.UPLOAD_URL_EXPIRY_S,
            "display": storage.DISPLAY_URL_EXPIRY_S,
            "artifact": ARTIFACT_URL_EXPIRY_S,
        }
        assert spans[shorter] < spans[longer]
