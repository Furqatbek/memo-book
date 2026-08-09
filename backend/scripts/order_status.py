"""Operator CLI: advance an order through the fulfilment statuses.

    python scripts/order_status.py UB-7K3M2 sent_to_production
    python scripts/order_status.py UB-7K3M2 shipped
    python scripts/order_status.py UB-7K3M2 delivered
    python scripts/order_status.py UB-7K3M2 cancelled   # before production only

On the VPS:  docker compose -f docker-compose.prod.yml exec api \
                 python scripts/order_status.py UB-7K3M2 shipped

Goes through apply_transition — the state machine and the audit trail
(order_events) apply exactly as they do for automatic transitions.
`cancelled` also unlocks the book back to draft so the customer can keep
editing or re-order. Marking an order PAID is deliberately not offered
here: payment goes through the webhook so its side effects (render
enqueue, idempotency) are honoured.
"""
import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.domain.errors import DomainError
from app.domain.states import OrderStatus
from app.models.order import Order
from app.services.orders import apply_transition, cancel_order

TARGETS = ["sent_to_production", "shipped", "delivered", "cancelled"]


async def run(ref: str, target: str) -> None:
    engine = create_async_engine(get_settings().database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            order = (await session.execute(
                select(Order).where(Order.human_ref == ref)
            )).scalar_one_or_none()
            if order is None:
                sys.exit(f"no order with reference {ref}")
            before = order.status
            try:
                if target == "cancelled":
                    # Cancels the order AND unlocks the book for editing.
                    await cancel_order(session, order.id,
                                       note="operator CLI cancel")
                    await session.refresh(order)
                else:
                    effects = apply_transition(session, order,
                                               OrderStatus(target),
                                               note="operator CLI")
                    if effects:
                        sys.exit(f"refusing: entering {target} demands "
                                 f"effects {effects} this CLI cannot execute")
                    await session.commit()
            except DomainError as exc:
                sys.exit(f"refused: {exc.message}")
            print(f"{ref}: {before} -> {order.status}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ref", help="order reference, e.g. UB-7K3M2")
    parser.add_argument("target", choices=TARGETS)
    args = parser.parse_args()
    asyncio.run(run(args.ref.strip().upper(), args.target))
