"""Checkout + public order status (spec Part 5)."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.domain.states import OrderStatus
from app.payments.registry import available_providers, get_provider
from app.rate_limit import rate_limit
from app.services import orders as svc
from app.services import receipts as svc_receipts

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


@router.post("/orders/{human_ref}/receipt",
             dependencies=[rate_limit("order-status",
                                      lambda s: s.rate_limit_order_status_per_min)])
async def upload_receipt(
    human_ref: str, session: Session,
    phone: Annotated[str, Form(min_length=5, max_length=32)],
    receipt: UploadFile = File(...),
):
    """The customer attaches proof of their transfer (A100).

    Same door as the status page: reference plus the phone on the order, and
    a wrong phone is indistinguishable from an unknown reference. It shares
    that endpoint's rate limit for the same reason — guessing is the only
    attack available, so the request rate is the whole security boundary
    (A77).

    The phone arrives as a FORM field rather than a query parameter. This is
    a POST either way, but a query string ends up in access logs and
    referrers, and there is no reason to write a customer's phone number
    there on every upload.
    """
    # Read one byte past the limit, and no further: this endpoint is open to
    # anyone holding a reference, so an unbounded read is an invitation.
    raw = await receipt.read(svc_receipts.RECEIPT_MAX_BYTES + 1)
    order = await svc.order_for_receipt(session, human_ref, phone)
    await svc_receipts.attach_receipt(session, order, raw)
    return {
        "receipt_uploaded_at": order.receipt_uploaded_at,
        "receipt_bytes": order.receipt_bytes,
        "receipt_content_type": order.receipt_content_type,
    }
