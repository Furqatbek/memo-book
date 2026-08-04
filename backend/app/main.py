"""FastAPI application factory."""
from fastapi import FastAPI

from app.api.books import router as books_router
from app.api.errors import register_error_handlers
from app.api.health import router as health_router
from app.config import get_settings
from app.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(debug=settings.debug)
    app = FastAPI(title=settings.app_name, version="0.1.0")
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(books_router)
    return app


app = create_app()
