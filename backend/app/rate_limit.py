"""Per-IP rate limiting (spec Part 11) on the abuse-prone endpoints: book
creation, upload-URL issuance, payment webhooks, the admin console and the
public order lookup.

"Abuse-prone" here means one of two things, and the second is easy to miss:
an endpoint that is expensive to serve, or an endpoint whose ONLY defence is
that guessing takes many tries. The admin console and the order lookup are
the second kind — both answer a wrong guess exactly as they answer a
nonexistent one, which is the right design and is worth nothing if the
attacker can guess a million times a minute (A77). `test_rate_limit_coverage`
holds the list to that reasoning.

In-process sliding window — sufficient for a single-instance MVP; swap the
backing store for Redis when the API scales horizontally (the dependency
surface stays the same).
"""
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import Depends, Request

from app.config import Settings, get_settings
from app.domain.errors import DomainError, ErrorCode

WINDOW_S = 60.0


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_s: float = WINDOW_S) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - window_s:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def rate_limit(scope: str, limit_for: Callable[[Settings], int]):
    async def dependency(request: Request) -> None:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return
        ip = request.client.host if request.client else "unknown"
        if not limiter.allow(f"{scope}:{ip}", limit_for(settings)):
            raise DomainError(ErrorCode.RATE_LIMITED,
                              "too many requests — slow down",
                              {"scope": scope, "window_s": int(WINDOW_S)})
    return Depends(dependency)
