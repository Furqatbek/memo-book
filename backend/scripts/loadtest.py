"""Pre-launch load test (spec Part 9.6) — run before launch, NOT in CI:

    python scripts/loadtest.py <base_url> --uploads 50

Measures: 50 concurrent presigned-upload flows (issue URL -> PUT -> complete
-> poll ready) with latency percentiles. Render throughput (10 concurrent
96-page renders) must be measured on the worker host itself by enqueueing
paid orders in a staging environment — rendering is payment-triggered (R8)
and deliberately has no public endpoint to hammer.
"""
import argparse
import asyncio
import io
import statistics
import time

import httpx


def make_jpeg(seed: int) -> bytes:
    from PIL import Image

    img = Image.new("RGB", (1600, 1100), ((seed * 37) % 255, 90, 160))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


async def one_upload(client: httpx.AsyncClient, book: dict, seed: int) -> float:
    headers = {"X-Edit-Token": book["edit_token"]}
    data = make_jpeg(seed)
    start = time.monotonic()
    issued = (await client.post(
        f"/api/v1/books/{book['book_id']}/photos/upload-url",
        json={"filename": f"l{seed}.jpg", "mime": "image/jpeg", "bytes": len(data)},
        headers=headers)).json()
    async with httpx.AsyncClient(timeout=60) as direct:
        await direct.put(issued["upload_url"], content=data,
                         headers={"Content-Type": "image/jpeg"})
    await client.post(
        f"/api/v1/books/{book['book_id']}/photos/{issued['photo_id']}/complete",
        headers=headers)
    while True:
        photos = (await client.get(
            f"/api/v1/books/{book['book_id']}/photos",
            headers=headers)).json()["photos"]
        mine = next(p for p in photos if p["photo_id"] == issued["photo_id"])
        if mine["status"] in ("ready", "failed", "duplicate"):
            break
        await asyncio.sleep(0.5)
    return time.monotonic() - start


async def main(base_url: str, uploads: int) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=60) as client:
        book = (await client.post("/api/v1/books",
                                  json={"page_count": 96})).json()
        started = time.monotonic()
        durations = await asyncio.gather(
            *(one_upload(client, book, i) for i in range(uploads)))
        wall = time.monotonic() - started

    durations.sort()
    print(f"{uploads} concurrent uploads in {wall:.1f}s wall")
    print(f"p50 {statistics.median(durations):.2f}s | "
          f"p95 {durations[int(len(durations) * 0.95) - 1]:.2f}s | "
          f"max {durations[-1]:.2f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("--uploads", type=int, default=50)
    args = parser.parse_args()
    asyncio.run(main(args.base_url.rstrip("/"), args.uploads))
