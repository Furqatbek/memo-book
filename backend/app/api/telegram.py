"""The Telegram bot's inbound webhook (A96).

Exactly one route, and it is the only way into the system that is not the
customer API or the admin console. It follows the admin API's lock (A72) to
the letter, for the same reasons:

* **Not configured means it does not exist.** With no webhook secret the
  route answers 404, so a deployment that has never heard of this feature
  has no extra surface at all — which is every deployment until someone sets
  the variable on purpose.
* **404, never 401 or 403.** A wrong secret learns nothing a right one
  would not. This endpoint is not an oracle for whether an RS Pixel bot
  lives here.
* Comparison is constant-time.

Past the lock, a valid Telegram delivery always gets a 200 even when the
update is nonsense or the action is refused: Telegram redelivers anything
else, and an update that can never succeed would be retried forever.
"""
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_session
from app.rate_limit import rate_limit
from app.services import telegram_control

router = APIRouter(prefix="/api/v1/telegram", tags=["telegram"])

Session = Annotated[AsyncSession, Depends(get_session)]

# Indistinguishable from a route that was never registered.
_GONE = HTTPException(status_code=404, detail="Not Found")

SECRET_HEADER = "x-telegram-bot-api-secret-token"


async def require_telegram(request: Request) -> None:
    from app.services.telegram import control_enabled

    settings = get_settings()
    # The secret alone decides whether this route exists. WHO may act is a
    # per-press database check (A97): a chat where nobody is linked yet can
    # still receive `/link`, which is how anybody becomes linked at all.
    if not control_enabled():
        raise _GONE
    supplied = request.headers.get(SECRET_HEADER) or ""
    if not secrets.compare_digest(supplied, settings.telegram_webhook_secret):
        raise _GONE


@router.post("/webhook",
             dependencies=[Depends(require_telegram),
                           rate_limit("webhook",
                                      lambda s: s.rate_limit_webhook_per_min)])
async def webhook(request: Request, session: Session) -> dict:
    try:
        update = await request.json()
    except Exception:
        # Not raising: whatever sent this had the secret, so it is Telegram,
        # and Telegram will resend a body we rejected.
        return {"ok": True, "ignored": "body was not JSON"}
    if not isinstance(update, dict):
        return {"ok": True, "ignored": "body was not a JSON object"}
    return await telegram_control.handle_update(session, update)
