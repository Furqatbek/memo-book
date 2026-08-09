"""Operator CLI: confirm a received card transfer and mark the order paid.

    python scripts/confirm_payment.py --list      # orders awaiting payment
    python scripts/confirm_payment.py UB-7K3M2    # confirm this one

On the VPS:  docker compose -f docker-compose.prod.yml exec api \
                 python scripts/confirm_payment.py UB-7K3M2

Reads the order's amount from the database, then POSTs the dev-provider
webhook to the running API — so the payment goes through the exact same
machinery as an acquirer callback: signature check, amount verification,
idempotency, the paid transition, and the render enqueue. Running it twice
is safe (the second call reports duplicate).
"""
import argparse
import asyncio
import sys
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.order import Order


async def fetch_order(ref: str) -> Order:
    engine = create_async_engine(get_settings().database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            order = (await session.execute(
                select(Order).where(Order.human_ref == ref)
            )).scalar_one_or_none()
            if order is None:
                sys.exit(f"no order with reference {ref}")
            return order
    finally:
        await engine.dispose()


# Everything before the operator's own "sent to production" step — i.e.
# orders whose bank transfer may still need matching against the account.
UNVERIFIED_STATUSES = ("pending_payment", "paid", "rendering",
                       "render_failed", "rendered")


async def list_pending() -> None:
    engine = create_async_engine(get_settings().database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            orders = (await session.execute(
                select(Order).where(Order.status.in_(UNVERIFIED_STATUSES))
                .order_by(Order.created_at)
            )).scalars().all()
            if not orders:
                print("no orders awaiting payment or verification")
                return
            for o in orders:
                print(f"{o.human_ref}  {o.status:<15}"
                      f"  {o.amount_minor / 100:>12,.0f} {o.currency}"
                      f"  {o.created_at:%d.%m %H:%M}  {o.customer_name},"
                      f" {o.customer_phone}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ref", nargs="?",
                        help="order reference, e.g. UB-7K3M2")
    parser.add_argument("--list", action="store_true",
                        help="show orders awaiting payment and exit")
    parser.add_argument("--api", default="http://127.0.0.1:8000",
                        help="base URL of the running API (default: %(default)s)")
    args = parser.parse_args()
    if args.list or not args.ref:
        asyncio.run(list_pending())
        return
    ref = args.ref.strip().upper()

    settings = get_settings()
    if not settings.dev_payments_enabled or not settings.dev_payment_secret:
        sys.exit("DEV_PAYMENTS_ENABLED/DEV_PAYMENT_SECRET are not configured")

    order = asyncio.run(fetch_order(ref))
    print(f"{ref}: {order.customer_name}, {order.customer_phone} — "
          f"{order.amount_minor / 100:,.0f} {order.currency} ({order.status})")

    resp = httpx.post(
        f"{args.api}/api/v1/payments/dev/webhook",
        headers={"x-dev-signature": settings.dev_payment_secret},
        json={
            "event_id": f"operator-{uuid.uuid4()}",
            "action": "pay",
            "human_ref": ref,
            "amount_minor": order.amount_minor,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        sys.exit(f"webhook rejected: {resp.status_code} {resp.text[:300]}")
    body = resp.json()
    if body.get("duplicate"):
        print(f"{ref}: already paid — status {body['order_status']}, nothing to do")
    else:
        print(f"{ref}: {body['order_status']} — render is running; the Telegram "
              "notification follows when the PDFs are ready")


if __name__ == "__main__":
    main()
