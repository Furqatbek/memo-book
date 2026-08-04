"""Liveness and readiness endpoints.

/health — the process is alive; performs no dependency checks (spec Part 5).
/ready  — DB, Redis and object storage are reachable; 503 with per-dependency
          detail when any of them is not.
"""
import asyncio

import anyio
import redis.asyncio as aioredis
from fastapi import APIRouter, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


async def _check_db(url: str, timeout: float) -> str:
    engine = create_async_engine(url, connect_args={"timeout": timeout})
    try:
        async with asyncio.timeout(timeout):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # noqa: BLE001 — readiness reports, never raises
        return f"error: {type(exc).__name__}"
    finally:
        await engine.dispose()


async def _check_redis(url: str, timeout: float) -> str:
    client = aioredis.from_url(url, socket_connect_timeout=timeout, socket_timeout=timeout)
    try:
        async with asyncio.timeout(timeout):
            await client.ping()
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return f"error: {type(exc).__name__}"
    finally:
        await client.aclose()


def _check_storage_sync(settings, timeout: float) -> str:
    import boto3
    from botocore.config import Config as BotoConfig

    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=BotoConfig(connect_timeout=timeout, read_timeout=timeout,
                          retries={"max_attempts": 1}),
    )
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return f"error: {type(exc).__name__}"


@router.get("/ready")
async def ready(response: Response) -> dict:
    settings = get_settings()
    t = settings.ready_check_timeout_s
    db, redis_status, storage = await asyncio.gather(
        _check_db(settings.database_url, t),
        _check_redis(settings.redis_url, t),
        anyio.to_thread.run_sync(_check_storage_sync, settings, t),
    )
    checks = {"database": db, "redis": redis_status, "storage": storage}
    ok = all(v == "ok" for v in checks.values())
    if not ok:
        response.status_code = 503
    return {"status": "ok" if ok else "degraded", "checks": checks}
