"""Payment webhooks (spec Part 5). Provider-specific body shapes; the service
verifies the signature before anything else."""
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.domain.errors import DomainError, ErrorCode
from app.services.payments import handle_webhook

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/{provider}/webhook")
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
