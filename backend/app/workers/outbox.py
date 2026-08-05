"""Standalone outbox delivery worker. Run with:  python -m app.workers.outbox
Polls for due messages and delivers them with the backoff recorded on each
row. Safe to run more than one instance only if you accept duplicate sends
(at-least-once either way)."""
import asyncio
import time

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.services.outbox import deliver_pending

POLL_INTERVAL_S = 10


async def run_once() -> int:
    engine = create_async_engine(get_settings().database_url)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            return await deliver_pending(session)
    finally:
        await engine.dispose()


def main() -> None:
    while True:
        asyncio.run(run_once())
        time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
