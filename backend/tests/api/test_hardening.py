"""Milestone 13: rate limiting + error envelope audit."""
import httpx
import pytest

from app.api.errors import STATUS_BY_CODE
from app.config import get_settings
from app.domain.errors import ErrorCode
from app.rate_limit import limiter


@pytest.fixture
async def limited_clients(sessionmaker, s3, monkeypatch):
    """Two clients from different IPs against an app with tight limits."""
    from app.db.session import get_session
    from app.main import create_app

    monkeypatch.setenv("TASK_EAGER", "true")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_BOOK_CREATE_PER_MIN", "3")
    get_settings.cache_clear()
    limiter.reset()
    app = create_app()

    async def _override_session():
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session

    async def make(ip: str) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app, client=(ip, 12345))
        return httpx.AsyncClient(transport=transport, base_url="http://test")

    a, b = await make("10.0.0.1"), await make("10.0.0.2")
    yield a, b
    await a.aclose()
    await b.aclose()
    get_settings.cache_clear()
    limiter.reset()


class TestRateLimiting:
    async def test_burst_hits_429_with_envelope(self, limited_clients):
        a, _ = limited_clients
        for _ in range(3):
            assert (await a.post("/api/v1/books",
                                 json={"page_count": 16})).status_code == 201
        resp = await a.post("/api/v1/books", json={"page_count": 16})
        assert resp.status_code == 429
        assert resp.json()["error"]["code"] == "RATE_LIMITED"

    async def test_limits_are_per_ip(self, limited_clients):
        a, b = limited_clients
        for _ in range(3):
            await a.post("/api/v1/books", json={"page_count": 16})
        assert (await a.post("/api/v1/books",
                             json={"page_count": 16})).status_code == 429
        # A different IP is unaffected.
        assert (await b.post("/api/v1/books",
                             json={"page_count": 16})).status_code == 201


class TestErrorEnvelopeAudit:
    def test_every_error_code_has_a_status_mapping(self):
        unmapped = [code for code in ErrorCode if code not in STATUS_BY_CODE]
        assert unmapped == [], f"codes without a status mapping: {unmapped}"

    # Domain errors are almost always the caller's problem, so 4xx is the
    # rule. The exceptions are listed here rather than allowed by a looser
    # bound, so adding a 5xx is a deliberate edit and the reason is written
    # down next to it.
    SERVER_SIDE = {
        # Nobody has confirmed the price list yet, so there is nothing the
        # customer could have sent that would have worked (A74).
        ErrorCode.PRICES_NOT_CONFIRMED: 503,
    }

    def test_statuses_are_sane(self):
        for code, status in STATUS_BY_CODE.items():
            if code in self.SERVER_SIDE:
                assert status == self.SERVER_SIDE[code], (
                    f"{code} maps to {status}, not the "
                    f"{self.SERVER_SIDE[code]} recorded here")
                continue
            assert 400 <= status < 500, f"{code} maps to {status}"

    def test_the_server_side_list_is_not_a_dumping_ground(self):
        """Every entry above must still be an error, and must still exist."""
        for code, status in self.SERVER_SIDE.items():
            assert code in STATUS_BY_CODE, f"{code} is no longer mapped"
            assert 500 <= status < 600, (
                f"{code} is listed as server-side but maps to {status} — "
                "move it out of SERVER_SIDE")

    async def test_unknown_book_returns_envelope(self, client):
        resp = await client.get(
            "/api/v1/books/00000000-0000-0000-0000-000000000000",
            headers={"X-Edit-Token": "x"})
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"
