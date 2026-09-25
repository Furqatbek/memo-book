"""RQ job entrypoint for the flip video. Start with:  rq worker flip

Its own worker, on its own queue, because encoding is minutes of CPU for
something nobody paid for and it must never be in front of a print job
somebody did (CR-003-5).
"""
import asyncio
import uuid

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings

log = structlog.get_logger()


def run(order_id: str) -> None:
    asyncio.run(_run(uuid.UUID(order_id)))


async def _run(order_id: uuid.UUID) -> None:
    from app.services.flip_video import generate

    engine = create_async_engine(get_settings().database_url)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            # `generate` catches its own failures and answers False; this
            # is the belt for the braces — an exception escaping here would
            # be an RQ retry of a job whose only job is to be optional.
            try:
                await generate(session, order_id)
            except Exception as exc:  # noqa: BLE001 — job boundary
                log.warning("flip_video.job_failed", order_id=str(order_id),
                            error=str(exc)[:300])
    finally:
        await engine.dispose()
