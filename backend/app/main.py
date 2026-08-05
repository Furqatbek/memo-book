"""FastAPI application factory."""
from pathlib import Path

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
from app.config import get_settings
from app.logging import configure_logging


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
    if settings.editor_dir and Path(settings.editor_dir).is_dir():
        app.mount("/editor", StaticFiles(directory=settings.editor_dir, html=True),
                  name="editor")
    return app


app = create_app()
