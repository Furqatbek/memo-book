"""Shared fixtures. Database selection:

- TEST_DATABASE_URL set        -> that database (CI provides real Postgres)
- local Postgres on :5432 up   -> postgresql+asyncpg://memobook:memobook@127.0.0.1/memobook
- otherwise                    -> in-memory SQLite (schema via metadata; the
                                  JSONB column degrades to JSON transparently)
"""
import os
import socket

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_session


def _port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _test_db_url() -> str | None:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        return url
    if _port_open("127.0.0.1", 5432):
        return "postgresql+asyncpg://memobook:memobook@127.0.0.1:5432/memobook"
    return None


@pytest.fixture
async def engine():
    url = _test_db_url()
    if url:
        eng = create_async_engine(url)
    else:
        eng = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture
async def sessionmaker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def db(sessionmaker):
    async with sessionmaker() as session:
        yield session


@pytest.fixture
async def client(sessionmaker):
    from app.main import create_app

    app = create_app()

    async def _override_session():
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
