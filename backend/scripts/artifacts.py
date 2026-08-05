"""Print (or download) an order's print-PDF artifacts — the local-dev
equivalent of the Telegram production message.

    python scripts/artifacts.py UB-7K3M2                # print signed URLs
    python scripts/artifacts.py UB-7K3M2 --save ./out   # download the PDFs

Environment resolution:
  --dev                use scripts/devserver.py defaults (SQLite dev.db +
                       the in-process moto S3 on :9421) — for when the
                       devserver is running in another terminal
  (otherwise)          the normal env vars / .env, so inside the Docker
                       containers it just works:
                       docker compose -f docker-compose.local.yml exec api \\
                           python scripts/artifacts.py UB-7K3M2
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

URL_EXPIRY_S = 7 * 24 * 3600


async def run(ref: str, save_dir: str | None) -> None:
    from app import storage
    from app.config import get_settings
    from app.models.order import Order
    from app.models.payment import PdfArtifact

    engine = create_async_engine(get_settings().database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            order = (await session.execute(
                select(Order).where(Order.human_ref == ref)
            )).scalar_one_or_none()
            if order is None:
                sys.exit(f"no order with reference {ref}")
            artifacts = list((await session.execute(
                select(PdfArtifact).where(PdfArtifact.order_id == order.id)
            )).scalars())
            if not artifacts:
                sys.exit(f"{ref} is '{order.status}' — no artifacts yet "
                         "(they appear once the order is rendered)")
            print(f"{ref}: {order.status}")
            for artifact in artifacts:
                size_mb = artifact.size_bytes / 1e6
                url = storage.presign_get(artifact.storage_key, expires_in=URL_EXPIRY_S)
                print(f"\n  {artifact.kind}  ({size_mb:.1f} MB, 7-day link):\n  {url}")
                if save_dir:
                    out = Path(save_dir)
                    out.mkdir(parents=True, exist_ok=True)
                    path = out / f"{ref}-{artifact.kind}.pdf"
                    path.write_bytes(storage.get_bytes(artifact.storage_key))
                    print(f"  saved -> {path}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ref", help="order reference, e.g. UB-7K3M2")
    parser.add_argument("--save", metavar="DIR", help="also download the PDFs here")
    parser.add_argument("--dev", action="store_true",
                        help="target a running scripts/devserver.py stack")
    args = parser.parse_args()
    if args.dev:
        backend = Path(__file__).resolve().parents[1]
        os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{backend / 'dev.db'}")
        os.environ.setdefault("S3_ENDPOINT_URL", "http://127.0.0.1:9421")
        os.environ.setdefault("S3_ACCESS_KEY", "test")
        os.environ.setdefault("S3_SECRET_KEY", "test")
    asyncio.run(run(args.ref.strip().upper(), args.save))
