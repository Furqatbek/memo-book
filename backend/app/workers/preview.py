"""RQ job entrypoint for preview rendering. Start with:  rq worker preview"""
import asyncio
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.services.preview import run_preview


def run(book_id: str) -> None:
    asyncio.run(_run(uuid.UUID(book_id)))


async def _run(book_id: uuid.UUID) -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            await run_preview(session, book_id)
    finally:
        await engine.dispose()
