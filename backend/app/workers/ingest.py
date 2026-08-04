"""RQ job entrypoint for photo ingest. The worker process owns its own event
loop and DB sessions. Start a worker with:  rq worker ingest
"""
import asyncio
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.services.photos import ingest_photo


def run(photo_id: str) -> None:
    asyncio.run(_run(uuid.UUID(photo_id)))


async def _run(photo_id: uuid.UUID) -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            await ingest_photo(session, photo_id)
    finally:
        await engine.dispose()
