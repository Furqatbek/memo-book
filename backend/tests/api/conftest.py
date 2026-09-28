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
def email_on():
    """A deployment where mail can actually be delivered.

    There is no mail transport, in any deployment, and nothing queues a
    message it cannot send — so in production every customer is reached
    through the Telegram bot or not at all.

    The email code still exists and is still the fallback the day a provider
    is integrated, so it stays under test. A module that asks for this
    fixture is saying "assume mail works"; the tests for what happens when
    it does not turn it back off explicitly, by name, so the two cases are
    both visible rather than one of them being the silent default.

    `send_email` itself still raises. This is only about whether callers are
    willing to QUEUE — the outbox's own failure handling is tested
    separately and should keep seeing a transport that throws.

    It holds its OWN MonkeyPatch rather than the shared `monkeypatch`
    fixture, and that is not fussiness: a test that calls
    `monkeypatch.undo()` to put back something it broke on purpose — the
    attention tests do, to repair a deliberately broken render — would
    otherwise silently switch mail off halfway through and fail on a row
    about unreachable customers that has nothing to do with what it tests.
    """
    from _pytest.monkeypatch import MonkeyPatch

    from app.services import email

    own = MonkeyPatch()
    own.setattr(email, "configured", lambda: True)
    yield
    own.undo()


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
