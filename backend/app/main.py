"""FastAPI application factory."""
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.admin import router as admin_router
from app.api.books import router as books_router
from app.api.cover_designs import router as cover_designs_router
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
    show raw translation keys (observed in production, A61).

    Markup and code therefore always revalidate: `no-cache` still lets the
    browser keep the copy, it just has to ask first, and Starlette answers
    an unchanged file with an empty 304. Media keeps a real expiry — those
    files are big, numerous (155 stickers) and effectively immutable.
    """

    # .txt and .xml are here for robots.txt and sitemap.xml (A83): small text
    # files whose entire purpose is being re-read, and the media branch would
    # have given them a week of caching on the one thing you might need to
    # change in a hurry.
    REVALIDATE_SUFFIXES = frozenset({"", ".html", ".htm", ".js", ".mjs",
                                     ".css", ".json", ".map", ".webmanifest",
                                     ".txt", ".xml"})
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
    # The interactive docs and the schema behind them are DEV ONLY (A82).
    #
    # A72 goes to some length to make the admin API unfindable: every
    # refusal is a 404 so a wrong token, a missing token and a switched-off
    # admin are indistinguishable, the comparison is constant-time, and the
    # attempts are rate-limited. `/openapi.json` published all nine admin
    # routes — paths, methods, request schemas — unauthenticated, on the same
    # host, even with ADMIN_TOKEN empty and the whole admin API answering
    # 404. The lock was excellent and the key was taped to the door.
    #
    # Serving them is a development convenience; the cost of losing it in
    # production is one `ENV=dev` away, and the cost of keeping it is that
    # A72 means nothing.
    interactive = settings.env == "dev"
    app = FastAPI(
        title=settings.app_name, version="0.1.0",
        docs_url="/docs" if interactive else None,
        redoc_url="/redoc" if interactive else None,
        openapi_url="/openapi.json" if interactive else None,
    )
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
    app.include_router(cover_designs_router)
    app.include_router(admin_router)
    # A mounted app answers `/editor/...` but NOT a bare `/editor`: Starlette
    # matches a Mount on `^/editor(?P<path>/.*)$`, and its redirect-slashes
    # fallback only fires when nothing matched at all. The site mount below
    # claims `/` and therefore claims `/editor` too, goes looking for a file
    # of that name, and answers `{"detail":"Not Found"}` — which is what a
    # person typing the address by hand gets, on the two paths most likely to
    # be typed by hand rather than followed from a link.
    #
    # 307 rather than a permanent redirect: it is what Starlette itself
    # answers for a directory inside the site mount (`/ru` -> `/ru/`), so the
    # whole site behaves the same way, and nothing is cached forever by a
    # browser if these paths ever move.
    def redirect_to_slashed(prefix: str):
        async def _redirect(request: Request) -> RedirectResponse:
            query = request.url.query
            return RedirectResponse(f"{prefix}/?{query}" if query else f"{prefix}/",
                                    status_code=307)
        return _redirect

    if settings.editor_dir and Path(settings.editor_dir).is_dir():
        app.get("/editor", include_in_schema=False)(redirect_to_slashed("/editor"))
        app.mount("/editor", WebAssets(directory=settings.editor_dir, html=True),
                  name="editor")
    if settings.admin_dir and Path(settings.admin_dir).is_dir():
        # Static markup only. Every action it offers goes through the admin
        # API, which is dead unless ADMIN_TOKEN is set (A72).
        app.get("/admin", include_in_schema=False)(redirect_to_slashed("/admin"))
        app.mount("/admin", WebAssets(directory=settings.admin_dir, html=True),
                  name="admin")
    if settings.site_dir and Path(settings.site_dir).is_dir():
        # Mounted last: everything the API and /editor don't claim.
        app.mount("/", WebAssets(directory=settings.site_dir, html=True),
                  name="site")
    return app


app = create_app()
