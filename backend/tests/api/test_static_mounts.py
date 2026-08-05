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
