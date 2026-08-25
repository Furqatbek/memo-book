"""A72: the admin console's API, and above all its lock.

The security properties here are the ones worth testing hardest: an admin
surface that is open by accident is worse than no admin surface at all.
"""
import io

import pytest
from PIL import Image

from app.config import get_settings
from app.services.cover_designs import (
    ARTWORK_H_PX,
    ARTWORK_W_PX,
    MIN_ARTWORK_W_PX,
    aspect_note,
    build_renditions,
)

TOKEN = "test-admin-token"
AUTH = {"X-Admin-Token": TOKEN}

def _admin_routes() -> list[tuple[str, str]]:
    """Every admin route, read from the router rather than typed out here.

    This list used to be written by hand, with a comment promising that a new
    route could not quietly skip the lock. Then the orders section (A73)
    added seven routes and none of them were added to the list, so for the
    whole of its life the most important assertion in this file was not
    running against the part of the API that hands out customer addresses and
    print files. Deriving it removes the promise and keeps the property.
    """
    from app.api.admin import router

    placeholders = {"design_id": "00000000-0000-0000-0000-000000000001",
                    "human_ref": "UB-NOPE1"}
    found: list[tuple[str, str]] = []
    for route in router.routes:
        path = route.path
        for name, value in placeholders.items():
            path = path.replace("{" + name + "}", value)
        assert "{" not in path, (
            f"{route.path} has a path parameter this test cannot fill in — "
            "add it to `placeholders`")
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            found.append((method, path))
    assert found, "no admin routes found — did the router move?"
    return sorted(found)


ROUTES = _admin_routes()


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def no_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def artwork(w: int = ARTWORK_W_PX, h: int = ARTWORK_H_PX) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), (30, 90, 160)).save(out, format="JPEG", quality=85)
    return out.getvalue()


def upload(**over) -> dict:
    data = {"slug": "hearts", "name": "Gold hearts", "book_types": "love",
            "bg_color": "#7a2740", "sort_order": "10"}
    data.update(over)
    return data


class TestTheLock:
    @pytest.mark.parametrize("method,path", ROUTES)
    async def test_no_configured_token_means_no_admin_api(self, client, no_admin,
                                                          method, path):
        """A deploy that forgets ADMIN_TOKEN must fail closed. This is the
        single most important assertion in the file."""
        resp = await client.request(method, path, headers=AUTH)
        assert resp.status_code == 404

    @pytest.mark.parametrize("method,path", ROUTES)
    async def test_every_route_needs_the_token(self, client, admin, method, path):
        assert (await client.request(method, path)).status_code == 404

    @pytest.mark.parametrize("method,path", ROUTES)
    async def test_a_wrong_token_is_refused(self, client, admin, method, path):
        resp = await client.request(method, path,
                                    headers={"X-Admin-Token": "not-the-token"})
        assert resp.status_code == 404

    async def test_failure_is_indistinguishable_from_a_missing_route(
            self, client, admin, no_admin):
        """404 rather than 401: the console is not an oracle for whether an
        admin API lives here."""
        wrong = await client.get("/api/v1/admin/ping",
                                 headers={"X-Admin-Token": "wrong"})
        nowhere = await client.get("/api/v1/admin/no-such-thing", headers=AUTH)
        assert wrong.status_code == nowhere.status_code == 404

    async def test_a_near_miss_token_is_still_refused(self, client, admin):
        for bad in (TOKEN[:-1], TOKEN + "x", TOKEN.upper(), " " + TOKEN):
            resp = await client.get("/api/v1/admin/ping",
                                    headers={"X-Admin-Token": bad})
            assert resp.status_code == 404, bad

    async def test_the_public_gallery_is_unaffected(self, client, no_admin):
        """Turning the admin API off must not take the shop window with it."""
        assert (await client.get("/api/v1/cover-designs")).status_code == 200


class TestSignIn:
    async def test_ping_returns_what_the_console_needs_to_draw_its_form(
            self, client, admin):
        body = (await client.get("/api/v1/admin/ping", headers=AUTH)).json()
        assert body["ok"] is True
        assert body["book_types"] == ["love", "travel", "birthday", "memory"]
        art = body["artwork"]
        assert (art["w_px"], art["h_px"]) == (ARTWORK_W_PX, ARTWORK_H_PX)
        assert art["min_w_px"] == MIN_ARTWORK_W_PX


class TestUploading:
    async def test_it_creates_a_design_customers_can_see(self, client, admin):
        resp = await client.post(
            "/api/v1/admin/cover-designs", headers=AUTH, data=upload(),
            files={"artwork": ("a.jpg", artwork(), "image/jpeg")})
        assert resp.status_code == 201
        created = resp.json()
        assert created["slug"] == "hearts"
        assert created["book_types"] == ["love"]
        assert created["active"] is True

        shop = (await client.get("/api/v1/cover-designs?book_type=love")).json()
        assert [d["slug"] for d in shop["designs"]] == ["hearts"]

    async def test_artwork_below_the_minimum_is_refused_with_a_reason(
            self, client, admin):
        resp = await client.post(
            "/api/v1/admin/cover-designs", headers=AUTH, data=upload(),
            files={"artwork": ("small.jpg", artwork(400, 590), "image/jpeg")})
        assert resp.status_code == 422
        assert "minimum" in resp.text

    async def test_a_file_that_is_not_an_image_is_refused(self, client, admin):
        resp = await client.post(
            "/api/v1/admin/cover-designs", headers=AUTH, data=upload(),
            files={"artwork": ("x.jpg", b"definitely not a jpeg", "image/jpeg")})
        assert resp.status_code == 422

    async def test_geometry_arrives_as_json_and_is_stored(self, client, admin):
        resp = await client.post(
            "/api/v1/admin/cover-designs", headers=AUTH,
            data=upload(photo_rect='{"x_mm":19,"y_mm":24,"w_mm":110,"h_mm":110}',
                        title='{"x_mm":74,"y_mm":158,"size_pt":24}',
                        title_color="#ffffff"),
            files={"artwork": ("a.jpg", artwork(), "image/jpeg")})
        body = resp.json()
        assert body["photo_rect"] == {"x_mm": 19, "y_mm": 24,
                                      "w_mm": 110, "h_mm": 110}
        assert body["title"] == {"x_mm": 74, "y_mm": 158, "size_pt": 24}

    async def test_malformed_geometry_is_refused_rather_than_stored(
            self, client, admin):
        resp = await client.post(
            "/api/v1/admin/cover-designs", headers=AUTH,
            data=upload(photo_rect="{not json"),
            files={"artwork": ("a.jpg", artwork(), "image/jpeg")})
        assert resp.status_code == 422

    async def test_a_bad_colour_is_refused(self, client, admin):
        resp = await client.post(
            "/api/v1/admin/cover-designs", headers=AUTH,
            data=upload(bg_color="red"),
            files={"artwork": ("a.jpg", artwork(), "image/jpeg")})
        assert resp.status_code == 422

    async def test_slugs_are_cleaned_not_trusted(self, client, admin):
        """A slug becomes a storage key, so it may not carry a path."""
        resp = await client.post(
            "/api/v1/admin/cover-designs", headers=AUTH,
            data=upload(slug="../../etc/Passwd Design!"),
            files={"artwork": ("a.jpg", artwork(), "image/jpeg")})
        assert resp.status_code == 201
        # Everything but letters, digits, "-" and "_" is dropped, so no
        # traversal and no spaces survive into the object key.
        assert resp.json()["slug"] == "etcpasswddesign"

    async def test_re_uploading_a_slug_replaces_it(self, client, admin):
        for name in ("First", "Second"):
            await client.post("/api/v1/admin/cover-designs", headers=AUTH,
                              data=upload(name=name),
                              files={"artwork": ("a.jpg", artwork(), "image/jpeg")})
        listing = (await client.get("/api/v1/admin/cover-designs",
                                    headers=AUTH)).json()["designs"]
        assert len(listing) == 1
        assert listing[0]["name"] == "Second"


class TestEditing:
    async def _make(self, client) -> dict:
        resp = await client.post(
            "/api/v1/admin/cover-designs", headers=AUTH, data=upload(),
            files={"artwork": ("a.jpg", artwork(), "image/jpeg")})
        return resp.json()

    async def test_settings_change_without_re_uploading_artwork(
            self, client, admin):
        design = await self._make(client)
        resp = await client.patch(
            f"/api/v1/admin/cover-designs/{design['design_id']}", headers=AUTH,
            json={"name": "Renamed", "book_types": ["travel", "birthday"],
                  "sort_order": 5, "photo_rect": {"x_mm": 10, "y_mm": 10,
                                                  "w_mm": 100, "h_mm": 100}})
        body = resp.json()
        assert body["name"] == "Renamed"
        assert body["book_types"] == ["travel", "birthday"]
        assert body["sort_order"] == 5
        assert body["photo_rect"]["w_mm"] == 100

    async def test_clearing_the_photo_window_makes_a_whole_artwork_cover(
            self, client, admin):
        design = await self._make(client)
        resp = await client.patch(
            f"/api/v1/admin/cover-designs/{design['design_id']}", headers=AUTH,
            json={"photo_rect": None})
        assert resp.json()["photo_rect"] is None

    async def test_retiring_hides_it_from_customers_but_keeps_the_row(
            self, client, admin):
        design = await self._make(client)
        resp = await client.delete(
            f"/api/v1/admin/cover-designs/{design['design_id']}", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["active"] is False

        shop = (await client.get("/api/v1/cover-designs")).json()
        assert shop["designs"] == []
        console = (await client.get("/api/v1/admin/cover-designs",
                                    headers=AUTH)).json()
        assert len(console["designs"]) == 1      # still there to restore

    async def test_restoring_puts_it_back(self, client, admin):
        design = await self._make(client)
        await client.delete(f"/api/v1/admin/cover-designs/{design['design_id']}",
                            headers=AUTH)
        await client.patch(f"/api/v1/admin/cover-designs/{design['design_id']}",
                           headers=AUTH, json={"active": True})
        shop = (await client.get("/api/v1/cover-designs")).json()
        assert [d["slug"] for d in shop["designs"]] == ["hearts"]

    async def test_editing_something_that_does_not_exist_is_404(
            self, client, admin):
        missing = "00000000-0000-0000-0000-0000000000ff"
        resp = await client.patch(f"/api/v1/admin/cover-designs/{missing}",
                                  headers=AUTH, json={"name": "x"})
        assert resp.status_code == 404


class TestSharedValidation:
    """The console and the CLI must accept exactly the same artwork, or the
    founder learns the difference from a printed book."""

    def test_renditions_come_back_smallest_last(self):
        full, display, thumb, w, h = build_renditions(artwork())
        assert (w, h) == (ARTWORK_W_PX, ARTWORK_H_PX)
        assert len(full) > len(display) > len(thumb)

    def test_a_too_small_file_raises_a_readable_message(self):
        with pytest.raises(ValueError, match="prints soft"):
            build_renditions(artwork(500, 700))

    def test_junk_raises_a_readable_message(self):
        with pytest.raises(ValueError, match="not an image"):
            build_renditions(b"nope")

    def test_the_right_aspect_draws_no_complaint(self):
        assert aspect_note(ARTWORK_W_PX, ARTWORK_H_PX) is None

    def test_a_wrong_aspect_says_what_will_happen(self):
        note = aspect_note(ARTWORK_W_PX, ARTWORK_W_PX)
        assert note and "centre-cropped" in note
