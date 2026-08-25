"""A77: every route is either throttled or explicitly exempt, with a reason.

`GET /api/v1/orders/{ref}?phone=` shipped unthrottled. It is unauthenticated,
and by design a wrong phone answers exactly like an unknown reference — so an
attacker gets no signal to work with and has nothing to do but try again.
That is the correct design, and it makes the request rate the entire security
boundary. Without a limit it was a free oracle over reference × phone.

The lesson is not "throttle that one endpoint". It is that route inventories
kept in prose go stale — the admin lock test made the same promise about
covering every route and quietly stopped being true when six were added. So
this reads the router.

Adding a route now means deciding, in this file, which side it is on.
"""
import re
from pathlib import Path

import httpx
import pytest
from fastapi.routing import APIRoute

from app.config import get_settings
from app.db.session import get_session
from app.main import create_app
from app.rate_limit import limiter


@pytest.fixture
async def guessing_clients(sessionmaker, s3, monkeypatch):
    """An attacker and a customer, on different IPs, against a tight limit."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_ORDER_STATUS_PER_MIN", "3")
    get_settings.cache_clear()
    limiter.reset()
    app = create_app()

    async def _override_session():
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session

    def at(ip: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=(ip, 12345)),
            base_url="http://test")

    attacker, customer = at("10.9.9.9"), at("10.0.0.5")
    yield attacker, customer
    await attacker.aclose()
    await customer.aclose()
    limiter.reset()
    get_settings.cache_clear()

# Routes that may answer unthrottled, each with the reason it is safe. A
# route not listed here and not throttled fails the test — the point is that
# the decision has to be made rather than defaulted into.
EXEMPT = {
    # Guarded by the 32-byte edit token in a header. Guessing it is not a
    # rate problem; it is a 256-bit problem.
    "GET /api/v1/books/{book_id}": "edit token",
    "PATCH /api/v1/books/{book_id}/layout": "edit token",
    "PATCH /api/v1/books/{book_id}/page-count": "edit token",
    "PATCH /api/v1/books/{book_id}/email": "edit token",
    "POST /api/v1/books/{book_id}/auto-place": "edit token",
    "GET /api/v1/books/{book_id}/checkout-eligibility": "edit token",
    "GET /api/v1/books/{book_id}/photos": "edit token",
    "DELETE /api/v1/books/{book_id}/photos/{photo_id}": "edit token",
    "POST /api/v1/books/{book_id}/photos/{photo_id}/complete": "edit token",
    "POST /api/v1/books/{book_id}/preview": "edit token",
    "GET /api/v1/books/{book_id}/preview": "edit token",
    "POST /api/v1/books/{book_id}/checkout": "edit token",
    # The same public shop window for everybody; nothing to guess at.
    "GET /api/v1/prices": "public, identical for everyone",
    "GET /api/v1/cover-designs": "public, identical for everyone",
    # Dev-only, and 404 outside dev environments.
    "GET /api/v1/payments/dev/config": "dev environments only",
}


def _routes() -> list[tuple[str, bool]]:
    """(("METHOD /path"), is_throttled) for every API route the app serves."""
    app = create_app()

    def walk(obj):
        for route in getattr(obj, "routes", []) or []:
            if isinstance(route, APIRoute):
                yield route
            elif type(route).__name__ == "_IncludedRouter":
                yield from walk(route.original_router)

    found = []
    for route in walk(app.router):
        if not route.path.startswith("/api/"):
            continue
        deps = " ".join(repr(d.call) for d in route.dependant.dependencies)
        throttled = "rate" in deps.lower()
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            found.append((f"{method} {route.path}", throttled))
    assert found, "no API routes found — did the router shape change?"
    return found


class TestEveryRouteHasBeenConsidered:
    def test_nothing_is_unthrottled_by_accident(self):
        unguarded = [name for name, throttled in _routes()
                     if not throttled and name not in EXEMPT]
        assert not unguarded, (
            "these routes are neither rate-limited nor listed as exempt: "
            f"{unguarded}. Add a limit, or add them to EXEMPT with the reason "
            "guessing at them is not a volume problem.")

    def test_the_exempt_list_has_no_ghosts(self):
        """An exemption for a route that no longer exists is a note about
        nothing, and it hides the next one that does need reading."""
        live = {name for name, _ in _routes()}
        stale = set(EXEMPT) - live
        assert not stale, f"exemptions for routes that do not exist: {stale}"

    def test_an_exempt_route_that_gained_a_limit_leaves_the_list(self):
        """Otherwise the list slowly becomes fiction."""
        throttled = {name for name, t in _routes() if t}
        contradictory = throttled & set(EXEMPT)
        assert not contradictory, (
            f"{contradictory} are throttled AND listed as exempt — drop them "
            "from EXEMPT")


class TestTheOneThatShipped:
    def test_the_public_order_lookup_is_throttled(self):
        """Named on its own so a regression says what broke, not just that a
        set differs. This is the endpoint that was open."""
        route = dict(_routes())["GET /api/v1/orders/{human_ref}"]
        assert route, "the public order lookup lost its rate limit"

    def test_its_limit_is_low_enough_to_matter(self):
        """A limit set high enough to be comfortable is not a limit. A
        customer refreshing their own order does it a handful of times."""
        from app.config import get_settings

        assert get_settings().rate_limit_order_status_per_min <= 60

    def test_the_limit_is_configurable_from_the_environment(self):
        """Every other limit is; one that is not becomes the one nobody can
        turn down when it is being abused."""
        source = Path("app/config.py").read_text(encoding="utf-8")
        assert re.search(r"^\s*rate_limit_order_status_per_min:\s*int",
                         source, re.M)


class TestTheLimitActuallyBites:
    """The inventory above proves a limit is attached. These prove it works
    on the endpoint it was attached for, and that it is per-IP — a global
    counter would let one attacker lock every real customer out."""

    async def test_guessing_is_cut_off(self, guessing_clients):
        attacker, _ = guessing_clients
        for _ in range(3):
            resp = await attacker.get("/api/v1/orders/UB-XXXXX",
                                      params={"phone": "+998901112233"})
            assert resp.status_code == 404          # wrong ref, as designed
        blocked = await attacker.get("/api/v1/orders/UB-XXXXX",
                                     params={"phone": "+998901112233"})
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "RATE_LIMITED"

    async def test_one_attacker_cannot_lock_out_a_real_customer(
            self, guessing_clients):
        """The failure mode of a global limit: an attacker hammering the
        endpoint takes the order page down for everybody who paid."""
        attacker, customer = guessing_clients
        for _ in range(5):
            await attacker.get("/api/v1/orders/UB-XXXXX",
                               params={"phone": "+998901112233"})
        resp = await customer.get("/api/v1/orders/UB-XXXXX",
                                  params={"phone": "+998901112233"})
        assert resp.status_code == 404, "a real customer was collaterally blocked"
