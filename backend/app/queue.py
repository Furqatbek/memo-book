"""Job queue seam. Real deployments enqueue to RQ/Redis; when TASK_EAGER is
set (tests, single-process dev) the caller runs the job inline instead."""
import uuid

from app.config import get_settings

INGEST_QUEUE = "ingest"
PREVIEW_QUEUE = "preview"
RENDER_QUEUE = "render"
# A queue of its own, and that is the whole point (CR-003-5). The flip video
# is minutes of encoding for something nobody paid for; sharing the render
# queue would let it sit in front of a print job somebody did.
FLIP_QUEUE = "flip"


def eager() -> bool:
    return get_settings().task_eager


def _enqueue(queue_name: str, job_path: str, arg: str) -> None:
    from redis import Redis
    from rq import Queue

    settings = get_settings()
    q = Queue(queue_name, connection=Redis.from_url(settings.redis_url))
    q.enqueue(job_path, arg)


def enqueue_ingest(photo_id: uuid.UUID) -> None:
    _enqueue(INGEST_QUEUE, "app.workers.ingest.run", str(photo_id))


def enqueue_preview(book_id: uuid.UUID) -> None:
    _enqueue(PREVIEW_QUEUE, "app.workers.preview.run", str(book_id))


def enqueue_order_render(order_id: uuid.UUID) -> None:
    _enqueue(RENDER_QUEUE, "app.workers.render.run", str(order_id))


def enqueue_flip_video(order_id: uuid.UUID) -> None:
    _enqueue(FLIP_QUEUE, "app.workers.flip_video.run", str(order_id))
