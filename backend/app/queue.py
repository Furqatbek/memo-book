"""Job queue seam. Real deployments enqueue to RQ/Redis; when TASK_EAGER is
set (tests, single-process dev) the caller runs the job inline instead."""
import uuid

from app.config import get_settings

INGEST_QUEUE = "ingest"


def eager() -> bool:
    return get_settings().task_eager


def enqueue_ingest(photo_id: uuid.UUID) -> None:
    from redis import Redis
    from rq import Queue

    settings = get_settings()
    q = Queue(INGEST_QUEUE, connection=Redis.from_url(settings.redis_url))
    q.enqueue("app.workers.ingest.run", str(photo_id))
