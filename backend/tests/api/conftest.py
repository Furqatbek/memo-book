"""Fixtures shared across the API tests.

`admin` lives here rather than in one test module because three others need
it, and importing a fixture between test modules works but reads as a
redefinition to every linter — and, worse, makes it look as though one
test file owns a thing that four of them depend on.
"""
import pytest

from app.config import get_settings

ADMIN_TOKEN = "test-admin-token"


@pytest.fixture
def admin(monkeypatch):
    """The admin API switched on. An empty token disables the whole surface
    (A72), so this is the difference between the console existing and every
    one of its routes answering 404."""
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def browsers(sessionmaker, s3, monkeypatch):
    """A factory for INDEPENDENT browsers against the same app.

    The default `client` is one browser with one cookie jar. Anything about
    several people — distinct contributors, attribution per visitor — is
    untestable with it: one jar makes ten people look like one, and the
    test passes while the cap it claims to check does nothing.
    """
    import contextlib

    import httpx

    from app.db.session import get_session
    from app.main import create_app

    monkeypatch.setenv("TASK_EAGER", "true")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("PRICES_CONFIRMED", "true")
    monkeypatch.setenv("FLIP_VIDEO_ENABLED", "false")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://test")
    get_settings.cache_clear()
    app = create_app()

    async def _override_session():
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session

    async with contextlib.AsyncExitStack() as stack:
        async def new_browser():
            transport = httpx.ASGITransport(app=app)
            return await stack.enter_async_context(
                httpx.AsyncClient(transport=transport,
                                  base_url="http://test"))

        yield new_browser
    get_settings.cache_clear()
