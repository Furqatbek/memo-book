"""One-command local stack, no Docker required:

    python scripts/devserver.py [--port 8000] [--fresh]

- SQLite instead of Postgres (schema created directly from the models)
- in-process moto S3 server on :9421 (real presigned URLs, browser-reachable)
- queue jobs run inline (TASK_EAGER) — no Redis, no workers
- the static editor is served at /editor from ../editor

This is a development convenience; production runs Postgres + MinIO/S3 +
Redis workers per README. Photos and the database persist in backend/dev.db
and the moto process's memory (objects vanish on restart; --fresh resets
the database to match).
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
EDITOR = BACKEND.parent / "editor"
S3_PORT = 9421


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--fresh", action="store_true", help="start with an empty database")
    args = parser.parse_args()

    db_path = BACKEND / "dev.db"
    if args.fresh and db_path.exists():
        db_path.unlink()

    # Settings are read at import time — configure before importing the app.
    os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    os.environ.setdefault("TASK_EAGER", "true")
    os.environ.setdefault("S3_ENDPOINT_URL", f"http://127.0.0.1:{S3_PORT}")
    os.environ.setdefault("S3_ACCESS_KEY", "test")
    os.environ.setdefault("S3_SECRET_KEY", "test")
    os.environ.setdefault("EDITOR_DIR", str(EDITOR))
    os.environ.setdefault("ADMIN_DIR", str(BACKEND.parent / "admin"))
    # The marketing site at `/`, which is where production serves it — Caddy
    # puts the site, the editor and the API on one hostname. Dev left this
    # unset, so `/` was a 404 here and the site had to be served separately
    # on another port. That made the two DIFFERENT ORIGINS, which is a
    # material difference: the front page reads the editor's localStorage to
    # know whether you have a book on the go (A105), and cross-origin it
    # never could.
    os.environ.setdefault("SITE_DIR", str(BACKEND.parent))
    # A local console needs a token; production sets its own in .env.
    os.environ.setdefault("ADMIN_TOKEN", "dev-admin")
    # Telegram order control needs a webhook secret to exist at all
    # (A97). A dev default lets the browser check drive the real
    # linking flow; production sets its own or stays switched off.
    os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "dev-telegram-secret")
    # The customer-facing recovery link (Change 2) needs a bot to point at
    # and an absolute base to link back to. Dev values so the browser check
    # can drive the real deep-link flow; production sets its own or leaves
    # the offer switched off, which the editor handles by hiding it.
    os.environ.setdefault("TELEGRAM_BOT_USERNAME", "rspixel_dev_bot")
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dev-bot-token")
    os.environ.setdefault("PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    # 60/min is right in production — it exists to make guessing the token
    # expensive, and one operator never comes close. The browser checks drive
    # the console far faster than a person can, and three admin checks in the
    # same minute trip it, which reads as a broken feature rather than a
    # working rate limiter. The limiter itself is covered by test_hardening.
    os.environ.setdefault("RATE_LIMIT_ADMIN_PER_MIN", "1000")
    # Dev sells happily at placeholder prices — there is no money here (A74).
    os.environ.setdefault("PRICES_CONFIRMED", "true")

    import threading

    from moto.moto_server.werkzeug_app import (
        DomainDispatcherApplication,
        create_backend_app,
    )
    from werkzeug.serving import make_server

    moto_app = DomainDispatcherApplication(create_backend_app)

    def s3_app(environ, start_response):
        # Real S3 never authenticates CORS preflights; moto does and 403s them
        # (the presigned signature is bound to PUT, not OPTIONS). Dropping the
        # query string routes preflights into moto's bucket-CORS handler.
        if environ.get("REQUEST_METHOD") == "OPTIONS":
            environ["QUERY_STRING"] = ""
        return moto_app(environ, start_response)

    s3_server = make_server("127.0.0.1", S3_PORT, s3_app, threaded=True)
    threading.Thread(target=s3_server.serve_forever, daemon=True).start()

    import boto3

    s3 = boto3.client(
        "s3", endpoint_url=f"http://127.0.0.1:{S3_PORT}",
        aws_access_key_id="test", aws_secret_access_key="test", region_name="us-east-1",
    )
    from app.config import get_settings

    settings = get_settings()
    s3.create_bucket(Bucket=settings.s3_bucket)
    # The browser PUTs photo bytes straight to storage — it needs CORS there.
    s3.put_bucket_cors(
        Bucket=settings.s3_bucket,
        CORSConfiguration={"CORSRules": [{
            "AllowedOrigins": ["*"],
            "AllowedMethods": ["GET", "PUT", "HEAD"],
            "AllowedHeaders": ["*"],
            "MaxAgeSeconds": 600,
        }]},
    )

    from sqlalchemy.ext.asyncio import create_async_engine

    import app.main  # noqa: F401 — imports every model so create_all sees them
    from app.db.base import Base

    async def create_schema() -> None:
        engine = create_async_engine(settings.database_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(create_schema())

    import uvicorn

    print(f"\n  API + editor:  http://127.0.0.1:{args.port}/editor/")
    print(f"  Swagger:       http://127.0.0.1:{args.port}/docs")
    print(f"  S3 (moto):     http://127.0.0.1:{S3_PORT}")
    print(f"  dev payment signature: {settings.dev_payment_secret}\n")
    sys.path.insert(0, str(BACKEND))
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
