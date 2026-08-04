"""RQ job entrypoint for order rendering. Start with:  rq worker render
Run 1-2 workers per container with a hard memory limit (spec Part 7)."""
import asyncio
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.services.fulfillment import run_order_render


def run(order_id: str) -> None:
    asyncio.run(_run(uuid.UUID(order_id)))


async def _run(order_id: uuid.UUID) -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            await run_order_render(session, order_id)
    finally:
        await engine.dispose()
