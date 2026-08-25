"""Checkout + public order status (spec Part 5)."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.domain.states import OrderStatus
from app.payments.registry import available_providers, get_provider
from app.rate_limit import rate_limit
from app.services import orders as svc

router = APIRouter(prefix="/api/v1", tags=["orders"])

Session = Annotated[AsyncSession, Depends(get_session)]
EditToken = Annotated[str, Header(alias="X-Edit-Token")]


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=5, max_length=32)
    address: str = Field(min_length=5, max_length=2000)
    email: EmailStr | None = None
    confirmed_preview: bool


@router.post("/books/{book_id}/checkout", status_code=201)
async def checkout(book_id: uuid.UUID, body: CheckoutRequest, session: Session,
                   x_edit_token: EditToken):
    order = await svc.checkout(
        session, book_id, x_edit_token,
        name=body.name, phone=body.phone, address=body.address,
        email=body.email, confirmed_preview=body.confirmed_preview,
    )
    # Trust-first card pilot: confirm immediately through the full webhook
    # machinery (amount check, idempotency via the deterministic event id,
    # render trigger) — the operator verifies the actual bank transfer
    # before printing. See AUTO_CONFIRM_ORDERS.
    from app.config import get_settings

    settings = get_settings()
    if (settings.auto_confirm_orders and settings.dev_payments_enabled
            and order.status == OrderStatus.PENDING_PAYMENT.value):
        from app.services.payments import handle_webhook

        await handle_webhook(
            session, "dev",
            {"x-dev-signature": settings.dev_payment_secret},
            {"event_id": f"auto-{order.id}", "action": "pay",
             "human_ref": order.human_ref, "amount_minor": order.amount_minor},
        )
        await session.refresh(order)
    providers = available_providers()
    return {
        "human_ref": order.human_ref,
        "order_status": order.status,
        "amount_minor": order.amount_minor,
        "currency": order.currency,
        "payment": {
            "providers_available": providers,
            "init": [get_provider(name).build_checkout_payload(order)
                     for name in providers],
        },
    }


@router.get("/orders/{human_ref}",
            dependencies=[rate_limit("order-status",
                                     lambda s: s.rate_limit_order_status_per_min)])
async def order_status(human_ref: str, session: Session,
                       phone: Annotated[str, Query(min_length=5, max_length=32)]):
    """Public: reference plus the phone on the order.

    Throttled because of how it answers, not because it is slow. A wrong
    phone is deliberately indistinguishable from an unknown reference
    (`public_status`), so an attacker has no signal to work with except
    trying again — which makes the request rate the entire security
    boundary. Unthrottled, this was a free oracle over reference × phone
    (A77).
    """
    return await svc.public_status(session, human_ref, phone)
