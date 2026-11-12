"""Global rate limiting shared across every worker process.

Celery's own `rate_limit=` is enforced per worker process, so it does not
cap total throughput once more than one worker is running. This module
enforces a real global cap by keeping the counter in Redis, where every
worker reads and writes the same key.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import redis


@dataclass
class RateLimitExceeded(Exception):
    """Raised when the shared budget for the current window is used up."""

    retry_after_seconds: float

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"rate limit exceeded, retry after {self.retry_after_seconds:.1f}s"


def acquire(redis_client: "redis.Redis", key: str, limit: int, window_seconds: int) -> None:
    """Consume one slot of `key`'s shared budget for the current window.

    Uses a fixed-window counter: all workers incrementing the same Redis key
    see the same count, so the limit holds regardless of worker count.
    Raises `RateLimitExceeded` with the time left in the window if the
    budget for this window is already spent.
    """
    now = time.time()
    window_start = int(now // window_seconds) * window_seconds
    window_key = f"ratelimit:{key}:{window_start}"

    pipe = redis_client.pipeline()
    pipe.incr(window_key, 1)
    pipe.expire(window_key, window_seconds + 5)
    count, _ = pipe.execute()

    if count > limit:
        retry_after = (window_start + window_seconds) - now
        raise RateLimitExceeded(retry_after_seconds=max(retry_after, 1.0))
