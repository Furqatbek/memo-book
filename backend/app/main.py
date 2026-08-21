"""FastAPI application factory."""
from pathlib import Path, PurePosixPath

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.books import router as books_router
from app.api.errors import register_error_handlers
from app.api.health import router as health_router
from app.api.orders import router as orders_router
from app.api.payments import router as payments_router
from app.api.photos import router as photos_router
from app.api.preview import router as preview_router
from app.api.pricing import router as pricing_router
from app.config import get_settings
from app.logging import configure_logging


class WebAssets(StaticFiles):
    """Static files with explicit caching rules.

    Without a Cache-Control header browsers fall back to *heuristic*
    caching, and mobile browsers hold JS for hours. That mixes a freshly
    fetched index.html with a stale app.js/i18n.js — new buttons appear
    wired to code that isn't there, so features look broken and labels
    show raw translation keys (observed in production, A58).

    Markup and code therefore always revalidate: `no-cache` still lets the
    browser keep the copy, it just has to ask first, and Starlette answers
    an unchanged file with an empty 304. Media keeps a real expiry — those
    files are big, numerous (155 stickers) and effectively immutable.
    """

    REVALIDATE_SUFFIXES = frozenset({"", ".html", ".htm", ".js", ".mjs",
                                     ".css", ".json", ".map", ".webmanifest"})
    MEDIA_MAX_AGE = 7 * 24 * 3600

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        suffix = PurePosixPath(path).suffix.lower()
        if suffix in self.REVALIDATE_SUFFIXES:
            response.headers["Cache-Control"] = "no-cache"
        else:
            response.headers["Cache-Control"] = (
                f"public, max-age={self.MEDIA_MAX_AGE}")
        return response


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(debug=settings.debug)
    app = FastAPI(title=settings.app_name, version="0.1.0")
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
            allow_methods=["*"],
            allow_headers=["*"],
            max_age=600,
        )
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(books_router)
    app.include_router(photos_router)
    app.include_router(preview_router)
    app.include_router(orders_router)
    app.include_router(payments_router)
    app.include_router(pricing_router)
    if settings.editor_dir and Path(settings.editor_dir).is_dir():
        app.mount("/editor", WebAssets(directory=settings.editor_dir, html=True),
                  name="editor")
    if settings.site_dir and Path(settings.site_dir).is_dir():
        # Mounted last: everything the API and /editor don't claim.
        app.mount("/", WebAssets(directory=settings.site_dir, html=True),
                  name="site")
    return app


app = create_app()
