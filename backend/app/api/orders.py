"""Checkout + public order status (spec Part 5)."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
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
    return {
        "human_ref": order.human_ref,
        "order_status": order.status,
        "amount_minor": order.amount_minor,
        "currency": order.currency,
        # Payment init data — providers are wired in Milestone 9; the
        # frontend polls the public status endpoint meanwhile.
        "payment": {
            "providers_available": [],
            "amount_minor": order.amount_minor,
            "currency": order.currency,
        },
    }


@router.get("/orders/{human_ref}")
async def order_status(human_ref: str, session: Session,
                       phone: Annotated[str, Query(min_length=5, max_length=32)]):
    return await svc.public_status(session, human_ref, phone)
