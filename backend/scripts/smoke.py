"""Deployment smoke tests (spec Part 9.4). Run against every deployed
environment, budget ~30 seconds:

    python scripts/smoke.py https://api.example.com

Checks: /health, /ready, book creation + edit token, presigned upload URL is
actually writable, photo ingest completes, Telegram credentials (getMe, no
message sent), Alembic head matches the DB revision (when DATABASE_URL is
set in the environment). A full single-page render is NOT smoked: rendering
only triggers via payment (R8), and a dev-payment smoke would create paid
orders in production. Exit code != 0 -> roll back the deploy.
"""
import io
import os
import subprocess
import sys
import time

import httpx

TIMEOUT = 15


def make_test_jpeg() -> bytes:
    from PIL import Image

    img = Image.new("RGB", (900, 600), (30, 90, 160))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


def main(base_url: str) -> int:
    failures: list[str] = []
    started = time.monotonic()

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
        if not ok:
            failures.append(name)

    with httpx.Client(base_url=base_url, timeout=TIMEOUT) as client:
        # 1-2. health + ready
        resp = client.get("/health")
        check("GET /health", resp.status_code == 200)
        resp = client.get("/ready")
        check("GET /ready", resp.status_code == 200,
              str(resp.json().get("checks", "")))

        # 3. create a book
        resp = client.post("/api/v1/books", json={"page_count": 16})
        ok = resp.status_code == 201 and resp.json().get("edit_token")
        check("POST /books", bool(ok))
        if not ok:
            return finish(failures, started)
        book = resp.json()
        headers = {"X-Edit-Token": book["edit_token"]}

        # 4. presigned upload URL is actually writable + 5. ingest completes
        data = make_test_jpeg()
        resp = client.post(
            f"/api/v1/books/{book['book_id']}/photos/upload-url",
            json={"filename": "smoke.jpg", "mime": "image/jpeg", "bytes": len(data)},
            headers=headers)
        check("POST /photos/upload-url", resp.status_code == 200)
        issued = resp.json()
        put = httpx.put(issued["upload_url"], content=data,
                        headers={"Content-Type": "image/jpeg"}, timeout=TIMEOUT)
        check("presigned PUT writable", put.status_code in (200, 204),
              f"status {put.status_code}")
        resp = client.post(
            f"/api/v1/books/{book['book_id']}/photos/{issued['photo_id']}/complete",
            headers=headers)
        check("POST /photos/complete", resp.status_code == 200)

        deadline = time.monotonic() + 20
        status = "unknown"
        while time.monotonic() < deadline:
            photos = client.get(f"/api/v1/books/{book['book_id']}/photos",
                                headers=headers).json()["photos"]
            status = photos[0]["status"] if photos else "missing"
            if status in ("ready", "failed"):
                break
            time.sleep(1)
        check("photo ingest completes", status == "ready", f"status {status}")

    # 6. Telegram credentials valid (getMe — sends nothing)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if token:
        resp = httpx.get(f"https://api.telegram.org/bot{token}/getMe",
                         timeout=TIMEOUT)
        check("telegram getMe", resp.status_code == 200)
    else:
        print("SKIP  telegram getMe (TELEGRAM_BOT_TOKEN not set)")

    # 7. Alembic head matches DB revision
    if os.environ.get("DATABASE_URL"):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "check"],
            capture_output=True, text=True, timeout=60, check=False,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        check("alembic head == DB revision", result.returncode == 0,
              result.stderr.strip()[:120])
    else:
        print("SKIP  alembic check (DATABASE_URL not set)")

    return finish(failures, started)


def finish(failures: list[str], started: float) -> int:
    elapsed = time.monotonic() - started
    print(f"\n{'SMOKE FAILED' if failures else 'SMOKE OK'} in {elapsed:.1f}s")
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/smoke.py <base_url>")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1].rstrip("/")))
