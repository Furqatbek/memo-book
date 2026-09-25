"""CR-003-5 — the flip video, as a thing that happens to an order.

One rule outranks everything else here, and the CR states it as a test
requirement in as many words: **a flip video failure must not affect order
state or the print render.** An order is a printed book somebody paid for.
This is a nicety. The two must never be able to touch, and most of what
follows is an attempt to make them touch.
"""
import uuid

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models.book import Book
from app.models.flip_video import FlipVideo
from app.models.outbox import OutboxMessage
from app.models.payment import PdfArtifact
from app.services import flip_video as svc
from app.services import outbox
from tests.api.conftest import ADMIN_TOKEN
from tests.api.test_admin_orders import AUTH, an_order, load


@pytest.fixture
def videos_on(monkeypatch):
    """The feature as production runs it. Off in conftest, because eager
    mode would otherwise run a real encode inside every test that reaches
    `rendered`."""
    monkeypatch.setenv("FLIP_VIDEO_ENABLED", "true")
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def paid_order(client, db) -> str:
    """An order walked to `rendered` — which is where the video is made."""
    ref = await an_order(client, db)
    resp = await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                             headers=AUTH, json={"note": "transfer seen"})
    assert resp.status_code == 200, resp.text
    return ref


async def video_for(db, ref: str) -> FlipVideo | None:
    order = await load(db, ref)
    return (await db.execute(select(FlipVideo).where(
        FlipVideo.order_id == order.id))).scalar_one_or_none()


class TestItGetsMade:
    async def test_reaching_rendered_produces_a_video(self, client, db,
                                                      videos_on):
        ref = await paid_order(client, db)
        order = await load(db, ref)
        assert order.status == "rendered"

        video = await video_for(db, ref)
        assert video is not None
        assert video.size_bytes > 0
        assert 6.0 <= video.duration_ms / 1000 <= 10.0
        assert video.storage_key.endswith("flip.mp4")

    async def test_it_is_made_once(self, client, db, videos_on):
        """The job can be retried by RQ, and an order can pass through
        `rendered` twice after a stalled-render recovery."""
        ref = await paid_order(client, db)
        order = await load(db, ref)
        before = await video_for(db, ref)

        assert await svc.generate(db, order.id) is True
        after = await video_for(db, ref)
        assert after.token == before.token
        rows = (await db.execute(select(FlipVideo).where(
            FlipVideo.order_id == order.id))).scalars().all()
        assert len(rows) == 1

    async def test_the_switch_turns_it_off(self, client, db, monkeypatch):
        monkeypatch.setenv("FLIP_VIDEO_ENABLED", "false")
        monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
        get_settings.cache_clear()
        try:
            ref = await paid_order(client, db)
            order = await load(db, ref)
            assert order.status == "rendered"      # the order is unaffected
            assert await video_for(db, ref) is None
        finally:
            get_settings.cache_clear()


class TestItCannotHurtAnOrder:
    async def test_an_encode_failure_leaves_the_order_rendered(
            self, client, db, videos_on, monkeypatch):
        """The requirement the CR names. Broken on purpose, in the place
        most likely to break in production — the encoder."""
        from app.render import flip

        def boom(pages):
            raise flip.FlipVideoError("ffmpeg exited 1: no such codec")

        monkeypatch.setattr(svc, "_encode", boom)

        ref = await paid_order(client, db)
        order = await load(db, ref)
        assert order.status == "rendered"
        assert await video_for(db, ref) is None

        # And the print files are there, which is the thing that matters.
        artifacts = (await db.execute(select(PdfArtifact).where(
            PdfArtifact.order_id == order.id))).scalars().all()
        assert {a.kind for a in artifacts} == {"interior", "cover"}

    async def test_a_storage_failure_is_the_same(self, client, db, videos_on,
                                                 monkeypatch):
        """The render is done and committed first, then storage is broken
        and the video attempted on its own. Breaking `put_bytes` before the
        render would break the render — which proves nothing about this
        code, because the print pipeline uses the same call."""
        ref = await paid_order(client, db)
        order = await load(db, ref)
        existing = await video_for(db, ref)
        if existing is not None:
            await db.delete(existing)
            await db.commit()

        from app import storage

        def boom(key, data, content_type):
            raise RuntimeError("the bucket is on fire")

        monkeypatch.setattr(storage, "put_bytes", boom)
        assert await svc.generate(db, order.id) is False

        await db.refresh(order)
        assert order.status == "rendered"
        assert await video_for(db, ref) is None

    async def test_the_printer_is_still_told(self, client, db, videos_on,
                                             monkeypatch):
        """The one message that must survive anything. A broken video that
        swallowed the printer's notification would turn a nicety into a
        book that never gets printed."""
        monkeypatch.setattr(svc, "_encode",
                            lambda pages: (_ for _ in ()).throw(
                                RuntimeError("nope")))
        await paid_order(client, db)
        topics = [m.topic for m in (await db.execute(
            select(OutboxMessage))).scalars().all()]
        assert outbox.TOPIC_ORDER_RENDERED in topics

    async def test_a_missing_order_is_not_an_error(self, db, videos_on):
        assert await svc.generate(db, uuid.uuid4()) is False


class TestTheCustomerIsTold:
    async def test_telegram_gets_the_video_itself(self, client, db,
                                                  videos_on):
        """Not a link. A file that plays where it lands is one people
        forward; a link is one more tap, and most never take it."""
        ref = await an_order(client, db)
        order = await load(db, ref)
        book = (await db.execute(select(Book).where(
            Book.id == order.book_id))).scalar_one()
        book.telegram_chat_id = 5150
        await db.commit()

        await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                          headers=AUTH, json={"note": "seen"})
        messages = [m for m in (await db.execute(
            select(OutboxMessage))).scalars().all()
            if m.topic == outbox.TOPIC_FLIP_VIDEO_TG]
        assert len(messages) == 1
        assert messages[0].payload["chat_id"] == 5150
        # A KEY, not a URL: presigned at delivery, so a message that waited
        # out an outage still plays.
        assert messages[0].payload["video_key"].endswith("flip.mp4")
        assert "http" not in messages[0].payload["video_key"]

    async def test_email_gets_a_link_because_email_cannot_do_better(
            self, client, db, videos_on):
        ref = await paid_order(client, db)
        video = await video_for(db, ref)
        progress = [m for m in (await db.execute(
            select(OutboxMessage))).scalars().all()
            if m.topic == outbox.TOPIC_ORDER_PROGRESS]
        assert progress, "no email queued for a customer with no Telegram"
        assert video.token in progress[0].payload["text"]

    async def test_the_message_asks_for_nothing(self, client, db):
        """The one thing people will not post is something that reads like
        it was written to be posted."""
        text = svc.VIDEO_MESSAGE.lower()
        for beg in ("please", "share this", "tag us", "don't forget"):
            assert beg not in text, svc.VIDEO_MESSAGE


class TestTheLink:
    async def test_it_redirects_to_the_file_and_counts_the_open(
            self, client, db, videos_on):
        ref = await paid_order(client, db)
        video = await video_for(db, ref)

        resp = await client.get(f"/v/{video.token}", follow_redirects=False)
        assert resp.status_code == 302
        assert "flip.mp4" in resp.headers["location"]
        assert "noindex" in resp.headers["x-robots-tag"]
        assert resp.headers["cache-control"] == "no-store"

        await db.refresh(video)
        assert video.download_count == 1

    async def test_every_open_is_counted_because_it_gets_forwarded(
            self, client, db, videos_on):
        ref = await paid_order(client, db)
        video = await video_for(db, ref)
        for _ in range(3):
            await client.get(f"/v/{video.token}", follow_redirects=False)
        await db.refresh(video)
        assert video.download_count == 3

    async def test_an_unknown_token_is_a_404(self, client, db):
        for bad in ("nope", "a" * 43, "x" * 200):
            resp = await client.get(f"/v/{bad}", follow_redirects=False)
            assert resp.status_code == 404

    async def test_the_token_is_not_the_order_reference(self, client, db,
                                                        videos_on):
        """A human reference is five characters from a small alphabet and
        is printed on things. It must not also be a key to a file."""
        ref = await paid_order(client, db)
        video = await video_for(db, ref)
        assert ref not in video.token
        assert len(video.token) >= 32
        resp = await client.get(f"/v/{ref}", follow_redirects=False)
        assert resp.status_code == 404


class TestWhatTheVideoShows:
    async def test_it_is_not_a_print_file(self, client, db, videos_on):
        """Low resolution, deliberately. A shareable file that could be
        printed would be the product, given away."""
        from app.render.flip import HEIGHT, WIDTH

        ref = await paid_order(client, db)
        video = await video_for(db, ref)
        assert video.storage_key.startswith("orders/")
        assert "/render/" not in video.storage_key
        # 1080x1920 is a phone screen, not a 154x216mm page at 300dpi.
        assert WIDTH * HEIGHT < 1819 * 2551

    async def test_a_long_book_is_truncated_not_sped_up(self, client, db,
                                                        videos_on):
        from app.render.flip import MAX_PAGES

        ref = await paid_order(client, db)
        video = await video_for(db, ref)
        assert video.page_count <= MAX_PAGES + 1   # + the cover
