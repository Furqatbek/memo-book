"""Delivery and watchdog loop.  Run with:  python -m app.workers.outbox

Two jobs on two cadences, in one process because they are the same concern —
making sure nothing that should have happened quietly did not:

* every POLL_INTERVAL_S, deliver due outbox messages with the backoff
  recorded on each row;
* every WATCHDOG_INTERVAL_S, look for renders that stopped making progress
  and move them somewhere loud and retryable (A76). A paid order stuck in
  `rendering` has nobody else watching it: the render worker that owned it is
  gone, and the nightly lifecycle job is up to a day away.

Safe to run more than one instance only if you accept duplicate sends
(at-least-once either way).
"""
import asyncio
import time

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.services.fulfillment import reap_stalled_renders
from app.services.outbox import deliver_pending

log = structlog.get_logger()

POLL_INTERVAL_S = 10
WATCHDOG_INTERVAL_S = 300


async def run_forever() -> None:
    """One engine for the life of the process.

    The previous shape built an engine and tore it down on every poll, which
    at a 10-second interval meant a fresh connection roughly 8,600 times a
    day to save nothing.
    """
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    next_watchdog = 0.0
    try:
        while True:
            async with maker() as session:
                await deliver_pending(session)

                now = time.monotonic()
                if now >= next_watchdog:
                    next_watchdog = now + WATCHDOG_INTERVAL_S
                    reaped = await reap_stalled_renders(session)
                    if reaped:
                        log.warning("watchdog.reaped_stalled_renders",
                                    count=reaped)
            await asyncio.sleep(POLL_INTERVAL_S)
    finally:
        await engine.dispose()


async def run_once() -> int:
    """A single delivery pass. Kept for tests and for one-shot cron use."""
    engine = create_async_engine(get_settings().database_url)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            return await deliver_pending(session)
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
