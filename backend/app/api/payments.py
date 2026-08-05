"""Payment webhooks (spec Part 5). Provider-specific body shapes; the service
verifies the signature before anything else."""
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_session
from app.domain.errors import DomainError, ErrorCode
from app.rate_limit import rate_limit
from app.services.payments import handle_webhook

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/dev/config")
async def dev_config():
    """DEV ENVIRONMENTS ONLY: hands the editor the simulated-payment
    signature so local one-click payment needs no typing. Gated on
    ENV=dev — a production pilot runs ENV=prod with dev payments still
    enabled, and must never expose the secret."""
    settings = get_settings()
    if settings.env != "dev" or not settings.dev_payments_enabled:
        raise DomainError(ErrorCode.NOT_FOUND, "not available")
    return {"dev_payment_secret": settings.dev_payment_secret}


@router.post("/{provider}/webhook",
             dependencies=[rate_limit("webhook",
                                      lambda s: s.rate_limit_webhook_per_min)])
async def webhook(provider: str, request: Request, session: Session):
    try:
        body = await request.json()
    except Exception as exc:
        raise DomainError(ErrorCode.VALIDATION_ERROR,
                          "webhook body must be JSON") from exc
    if not isinstance(body, dict):
        raise DomainError(ErrorCode.VALIDATION_ERROR,
                          "webhook body must be a JSON object")
    headers = {k.lower(): v for k, v in request.headers.items()}
    return await handle_webhook(session, provider, headers, body)
