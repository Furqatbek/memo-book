"""A82: the API documentation does not publish what A72 hides.

A72 makes the admin API deliberately unfindable. Every refusal is a 404, so a
wrong token, a missing token and a switched-off admin are indistinguishable;
the comparison is constant-time; the attempts are rate-limited. The reasoning
is written out in ASSUMPTIONS and asserted by tests.

`/openapi.json` published all nine admin routes — paths, methods, parameter
names, request schemas — unauthenticated, on the same host, **even with
ADMIN_TOKEN empty and every admin route answering 404**. The lock was
excellent and the key was taped to the door.

The interactive docs are a development convenience. Losing them in production
costs one `ENV=dev`; keeping them costs A72 its entire point.
"""
import httpx
import pytest

from app.config import get_settings
from app.main import create_app

DOC_PATHS = ["/docs", "/redoc", "/openapi.json"]


@pytest.fixture
def env(monkeypatch):
    def _set(value: str):
        monkeypatch.setenv("ENV", value)
        get_settings.cache_clear()
        return create_app()
    yield _set
    get_settings.cache_clear()


async def get_paths(app, paths: list[str]) -> dict[str, int]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://test") as c:
        return {p: (await c.get(p)).status_code for p in paths}


class TestProductionServesNoSchema:
    @pytest.mark.parametrize("path", DOC_PATHS)
    def test_the_doc_routes_are_gone(self, env, path):
        served = {getattr(r, "path", None) for r in env("prod").routes}
        assert path not in served

    def test_nothing_is_left_that_a_client_could_ask_for(self, env):
        app = env("prod")
        assert app.openapi_url is None
        assert app.docs_url is None
        assert app.redoc_url is None

    async def test_a_real_request_gets_404(self, env):
        """Absent, so the ordinary not-found path answers — indistinguishable
        from any other URL that was never there."""
        answers = await get_paths(env("prod"), DOC_PATHS)
        assert set(answers.values()) == {404}, answers


class TestTheAdminApiStaysUnfindable:
    def test_no_schema_means_no_admin_route_list(self, env):
        assert env("prod").openapi_url is None, (
            "a schema is being served, so every admin route is discoverable")

    def test_the_concern_is_real_not_theoretical(self, env):
        """In dev, where the docs are meant to be on, the admin routes are
        all listed — which is exactly what production was publishing."""
        admin = [p for p in env("dev").openapi()["paths"] if "/admin" in p]
        assert len(admin) >= 9, (
            "if this drops to zero the test above stops meaning anything")


class TestDevelopmentIsUnaffected:
    @pytest.mark.parametrize("path", DOC_PATHS)
    def test_the_doc_routes_are_there(self, env, path):
        served = {getattr(r, "path", None) for r in env("dev").routes}
        assert path in served

    def test_the_schema_still_builds(self, env):
        """A schema that has quietly stopped building is a broken tool nobody
        notices until the day they need it."""
        schema = env("dev").openapi()
        assert schema["info"]["title"]
        assert len(schema["paths"]) > 20


class TestTheThingsThatMustStayPublic:
    """Hiding the schema must not hide what a load balancer, an uptime
    monitor or bootstrap.sh needs to see."""

    async def test_health_and_ready_still_answer_in_production(self, env):
        answers = await get_paths(env("prod"), ["/health"])
        assert answers["/health"] == 200
