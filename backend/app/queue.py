"""Job queue seam. Real deployments enqueue to RQ/Redis; when TASK_EAGER is
set (tests, single-process dev) the caller runs the job inline instead."""
import uuid

from app.config import get_settings

INGEST_QUEUE = "ingest"
PREVIEW_QUEUE = "preview"


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
