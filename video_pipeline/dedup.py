"""Idempotency helpers so re-running a manifest does not re-queue or
re-render jobs that were already dispatched or already completed.
"""
from __future__ import annotations

import redis

DISPATCHED_TTL_SECONDS = 24 * 3600
COMPLETED_TTL_SECONDS = 7 * 24 * 3600


def mark_dispatched_if_new(redis_client: "redis.Redis", reel_id: str) -> bool:
    """Return True and record `reel_id` as dispatched, or False if it already was."""
    return bool(redis_client.set(f"render:dispatched:{reel_id}", "1",
                                  nx=True, ex=DISPATCHED_TTL_SECONDS))


def is_completed(redis_client: "redis.Redis", reel_id: str) -> bool:
    return redis_client.exists(f"render:completed:{reel_id}") == 1


def mark_completed(redis_client: "redis.Redis", reel_id: str) -> None:
    redis_client.set(f"render:completed:{reel_id}", "1", ex=COMPLETED_TTL_SECONDS)
