"""The anonymous session and its attribution — Change 3.

Two first-party cookies, both set by middleware so they exist before any
JavaScript runs and regardless of whether it runs at all:

  `mb_sid`   an opaque random id. Not a customer identifier, not derived
             from anything about the visitor, and never joined to a name,
             phone or address — it exists to string one person's steps
             together into a funnel and nothing else.

  `mb_attr`  where they came from: utm_source, utm_medium, utm_campaign,
             or the referring host when there are no utm parameters.

FIRST LANDING WINS. Attribution is written once and then left alone. If it
were overwritten on every request, a customer who arrives from a New Year
ad, leaves, and comes back a week later by typing the address would be
recorded as direct traffic — and the campaign that actually paid for them
would show a cost per acquisition with the acquisition missing.

Both cookies are HttpOnly: the page never needs to read them, only the
server does, so there is no reason to expose them to script.
"""
import json
import secrets
from urllib.parse import urlsplit

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

SID_COOKIE = "mb_sid"
ATTR_COOKIE = "mb_attr"
# Long enough to cover "saw the ad, ordered a fortnight later", short enough
# that it is not a permanent identifier.
MAX_AGE_S = 180 * 24 * 3600
UTM_PARAMS = {"source": "utm_source", "medium": "utm_medium",
              "campaign": "utm_campaign"}
FIELD_MAX = 128


def _clean(value: str | None) -> str | None:
    """Anything from a query string is a stranger's input. Trim it, and drop
    control characters so nothing odd reaches a log line or a report."""
    if not value:
        return None
    value = "".join(c for c in value if c.isprintable()).strip()
    return value[:FIELD_MAX] or None


def attribution_from(request: Request) -> dict:
    """What this request says about where the visitor came from."""
    found = {k: _clean(request.query_params.get(p)) for k, p in UTM_PARAMS.items()}
    if any(found.values()):
        return {k: v for k, v in found.items() if v}
    referer = request.headers.get("referer")
    if referer:
        host = _clean(urlsplit(referer).hostname)
        # Our own pages are not a source; every internal click would
        # otherwise overwrite the campaign that brought them here.
        if host and host not in (request.url.hostname, "localhost", "127.0.0.1"):
            return {"source": host, "medium": "referral"}
    return {}


def stored_attribution(request: Request) -> dict:
    raw = request.cookies.get(ATTR_COOKIE)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: _clean(str(v)) for k, v in data.items()
            if k in UTM_PARAMS and v}


def session_id_of(request: Request) -> str | None:
    """The id for this request, whether it arrived on a cookie or was minted
    by the middleware a moment ago."""
    return getattr(request.state, "funnel_sid", None) or request.cookies.get(SID_COOKIE)


class FunnelSessionMiddleware(BaseHTTPMiddleware):
    """Mint the session on first contact and remember where it came from.

    This sits in front of the static mounts as well as the API, which is the
    point: the cookie is set by the first marketing page a visitor opens, so
    the visit and every later step share one id — including the ones written
    by the server during checkout, long after the ad was clicked.
    """

    def __init__(self, app, secure: bool = True) -> None:
        super().__init__(app)
        self.secure = secure

    async def dispatch(self, request: Request, call_next):
        sid = request.cookies.get(SID_COOKIE)
        fresh = not sid
        if fresh:
            sid = secrets.token_urlsafe(24)
        request.state.funnel_sid = sid

        attribution = stored_attribution(request)
        landing = {} if attribution else attribution_from(request)
        request.state.funnel_attribution = attribution or landing

        response: Response = await call_next(request)

        opts = dict(max_age=MAX_AGE_S, httponly=True, samesite="lax",
                    secure=self.secure, path="/")
        if fresh:
            response.set_cookie(SID_COOKIE, sid, **opts)
        if landing:
            response.set_cookie(ATTR_COOKIE, json.dumps(landing,
                                                        separators=(",", ":")),
                                **opts)
        return response


def tracking_of(request: Request) -> tuple[str | None, dict]:
    """(session id, attribution) for an endpoint that wants to emit."""
    return (session_id_of(request),
            getattr(request.state, "funnel_attribution", None)
            or stored_attribution(request))


async def record(request: Request, session, event, **kw) -> bool:
    """Emit one event with this request's session and attribution.

    Kept to a single call at the emission site so that adding a funnel
    event to an endpoint never turns into three lines of bookkeeping that
    somebody later copies wrongly.
    """
    from app.services import funnel  # circular at module scope: api -> service

    sid, attribution = tracking_of(request)
    return await funnel.emit(session, event, session_id=sid,
                             attribution=attribution, **kw)
