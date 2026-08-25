"""EDITOR_DIR / SITE_DIR static mounts: opt-in, and never shadow API routes."""
import httpx

from app.config import get_settings
from app.main import create_app


async def test_mounts_serve_static_and_api_wins(tmp_path, monkeypatch):
    site = tmp_path / "site"
    (site / "ru").mkdir(parents=True)
    (site / "index.html").write_text("<h1>site-home</h1>")
    (site / "ru" / "index.html").write_text("<h1>site-ru</h1>")
    editor = tmp_path / "editor"
    editor.mkdir()
    (editor / "index.html").write_text("<h1>the-editor</h1>")

    monkeypatch.setenv("SITE_DIR", str(site))
    monkeypatch.setenv("EDITOR_DIR", str(editor))
    get_settings.cache_clear()
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            assert "site-home" in (await c.get("/")).text
            assert "site-ru" in (await c.get("/ru/")).text
            assert "the-editor" in (await c.get("/editor/")).text
            # API routes are registered before the "/" mount and always win.
            assert (await c.get("/health")).json() == {"status": "ok"}
    finally:
        get_settings.cache_clear()


async def test_mounts_absent_by_default(client):
    resp = await client.get("/editor/")
    assert resp.status_code == 404


async def test_code_revalidates_and_media_is_cacheable(tmp_path, monkeypatch):
    """A61: a stale app.js against a fresh index.html silently breaks the
    editor, so markup/code must always revalidate; media may be held."""
    editor = tmp_path / "editor"
    (editor / "js").mkdir(parents=True)
    (editor / "stickers").mkdir()
    (editor / "index.html").write_text("<h1>editor</h1>")
    (editor / "editor.css").write_text("body{}")
    (editor / "js" / "app.js").write_text("export const x = 1;")
    (editor / "stickers" / "flag-uz.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    monkeypatch.setenv("EDITOR_DIR", str(editor))
    get_settings.cache_clear()
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            for path in ("/editor/", "/editor/index.html", "/editor/editor.css",
                         "/editor/js/app.js"):
                resp = await c.get(path)
                assert resp.status_code == 200, path
                assert resp.headers["cache-control"] == "no-cache", path

            media = await c.get("/editor/stickers/flag-uz.png")
            assert media.status_code == 200
            assert "max-age=604800" in media.headers["cache-control"]

            # Revalidation must be cheap: an unchanged file answers 304.
            js = await c.get("/editor/js/app.js")
            again = await c.get("/editor/js/app.js",
                                headers={"If-None-Match": js.headers["etag"]})
            assert again.status_code == 304
    finally:
        get_settings.cache_clear()


async def test_the_crawler_files_are_reachable(tmp_path, monkeypatch):
    """A83: robots.txt and sitemap.xml are only useful if the mount serves
    them, and they revalidate rather than sitting in a week-long cache — the
    media branch would apply otherwise, on the two files most likely to need
    changing in a hurry."""
    site = tmp_path / "site"
    site.mkdir(parents=True)
    (site / "index.html").write_text("<h1>home</h1>")
    (site / "robots.txt").write_text("User-agent: *\nAllow: /\n")
    (site / "sitemap.xml").write_text('<?xml version="1.0"?><urlset/>')

    monkeypatch.setenv("SITE_DIR", str(site))
    get_settings.cache_clear()
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            robots = await c.get("/robots.txt")
            assert robots.status_code == 200
            assert "User-agent" in robots.text
            assert robots.headers["cache-control"] == "no-cache"

            sitemap = await c.get("/sitemap.xml")
            assert sitemap.status_code == 200
            assert sitemap.headers["cache-control"] == "no-cache"
            assert "xml" in sitemap.headers["content-type"]
    finally:
        get_settings.cache_clear()
