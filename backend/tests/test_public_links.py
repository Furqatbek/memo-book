"""Links that are meant to leave the building.

A share link, a contributor link, a review link and a flip-video link all
exist to be sent to somebody else. `/s/abc123` is not a link in a chat
window — it is a piece of text — so a relative one is not a degraded link,
it is a broken feature, and it fails in the worst possible place: silently,
in a customer's clipboard, discovered by their family after they sent it.

These tests hold the four of them to the same rule, and they exist as one
file rather than four assertions scattered about because the NEXT feature
that mints a public link is the one likely to get it wrong.
"""
import pytest

from app.config import get_settings
from app.domain.errors import DomainError
from app.services import contribute, flip_video, reviews, share
from app.services import public_links as links

MINTERS = [
    ("share", share.share_url, "/s/"),
    ("contributor", contribute.contribute_url, "/c/"),
    ("review", reviews.review_url, "/r/"),
    ("flip video", flip_video.video_url, "/v/"),
]


@pytest.fixture
def base(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://rspixel.uz")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def no_base(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestEveryPublicLinkIsAbsolute:
    @pytest.mark.parametrize("name,fn,prefix", MINTERS)
    def test_it_carries_the_origin(self, base, name, fn, prefix):
        url = fn("abc123")
        assert url == f"https://rspixel.uz{prefix}abc123", name

    @pytest.mark.parametrize("name,fn,prefix", MINTERS)
    def test_and_refuses_rather_than_falling_back(self, no_base, name, fn,
                                                  prefix):
        """A relative fallback is the bug this file exists to prevent. It
        looks like it works everywhere except the one place the link is
        actually used."""
        with pytest.raises(DomainError) as caught:
            fn("abc123")
        assert "PUBLIC_BASE_URL" in str(caught.value.details)

    def test_a_trailing_slash_does_not_double_up(self, monkeypatch):
        monkeypatch.setenv("PUBLIC_BASE_URL", "https://rspixel.uz/")
        get_settings.cache_clear()
        try:
            assert share.share_url("x") == "https://rspixel.uz/s/x"
        finally:
            get_settings.cache_clear()


class TestTheEditorIsToldRatherThanShownAnError:
    async def test_the_campaign_endpoint_says_whether_links_work(
            self, client, base):
        body = (await client.get("/api/v1/campaign")).json()
        assert body["sharing"] == {"available": True}

    async def test_and_says_so_when_they_do_not(self, client, no_base):
        """The editor hides the share and contributor buttons on this
        answer. A customer must never read the words PUBLIC_BASE_URL —
        they cannot fix it, and a button that produces a config message is
        worse than a button that is not there."""
        body = (await client.get("/api/v1/campaign")).json()
        assert body["sharing"] == {"available": False}


class TestTheHelper:
    def test_configured_reflects_the_setting(self, base):
        assert links.configured() is True

    def test_and_is_false_when_empty(self, no_base):
        assert links.configured() is False

    def test_a_path_without_a_leading_slash_still_works(self, base):
        assert links.absolute("s/x") == "https://rspixel.uz/s/x"
