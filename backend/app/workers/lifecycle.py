"""Nightly lifecycle runner. Schedule with cron:
    python -m app.workers.lifecycle
Runs expiry (R6), reminders (R7) and one outbox delivery pass, then exits.
"""
import asyncio

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.services.lifecycle import run_nightly

log = structlog.get_logger()


async def run_once() -> dict:
    engine = create_async_engine(get_settings().database_url)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            return await run_nightly(session)
    finally:
        await engine.dispose()


def main() -> None:
    result = asyncio.run(run_once())
    log.info("lifecycle.nightly_done", **result)


if __name__ == "__main__":
    main()
