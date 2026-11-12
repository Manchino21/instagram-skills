"""Worker task for rendering a single video reel.

Retry strategy has two distinct paths, kept separate so they do not fight
each other:

- A 429 from the render API means "come back later, I told you how long":
  we read `Retry-After` and retry with that exact countdown.
- Everything else transient (timeouts, connection errors, 5xx) is left to
  `autoretry_for`, which already has its own exponential backoff
  configured on the task decorator. We do not also catch and re-raise
  those manually, since a manual `self.retry()` has no countdown of its
  own and would retry immediately, bypassing the configured backoff.
"""
from __future__ import annotations

import os

import redis
import requests

from .celery_app import app
from .dedup import is_completed, mark_completed
from .rate_limiter import RateLimitExceeded, acquire

VIDEO_RENDER_API_URL = os.environ.get("VIDEO_RENDER_API_URL", "https://api.example.com/v1/render")
VIDEO_RENDER_API_KEY = os.environ.get("VIDEO_RENDER_API_KEY", "")
RATE_LIMIT_PER_MINUTE = int(os.environ.get("VIDEO_RENDER_RATE_LIMIT_PER_MINUTE", "2"))
DEFAULT_RETRY_AFTER_SECONDS = 30

_redis_client: "redis.Redis | None" = None


def _get_redis() -> "redis.Redis":
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(app.conf.broker_url)
    return _redis_client


@app.task(
    bind=True,
    autoretry_for=(
        requests.exceptions.HTTPError,
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
    ),
    retry_kwargs={"max_retries": 5},
    retry_backoff=True,
    retry_backoff_max=600,
)
def render_video_task(self, prompt_data: dict):
    """Render a single vertical video reel from a prompt manifest entry."""
    reel_id = prompt_data["id"]
    redis_client = _get_redis()

    if is_completed(redis_client, reel_id):
        print(f"[{self.request.id}] {reel_id} already completed, skipping")
        return {"status": "skipped_already_completed", "reel_id": reel_id}

    try:
        acquire(redis_client, key="render_api", limit=RATE_LIMIT_PER_MINUTE, window_seconds=60)
    except RateLimitExceeded as exc:
        raise self.retry(countdown=exc.retry_after_seconds, max_retries=None)

    print(f"[{self.request.id}] Starting render for: {prompt_data.get('title')}")

    try:
        response = requests.post(
            VIDEO_RENDER_API_URL,
            json={
                "prompt": prompt_data.get("prompt"),
                "aspect_ratio": "9:16",
                "duration": 10,
            },
            headers={"Authorization": f"Bearer {VIDEO_RENDER_API_KEY}"},
            timeout=45,
        )
        response.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 429:
            # The server told us exactly how long to wait: honor that
            # instead of Celery's generic exponential backoff.
            retry_after = float(exc.response.headers.get("Retry-After", DEFAULT_RETRY_AFTER_SECONDS))
            print(f"[{self.request.id}] 429 from render API, retrying in {retry_after}s")
            raise self.retry(exc=exc, countdown=retry_after, max_retries=5)
        # Any other HTTP error (4xx/5xx) propagates and is caught by
        # autoretry_for, which applies the configured exponential backoff.
        raise

    result = response.json()
    mark_completed(redis_client, reel_id)
    return {
        "status": "success",
        "reel_id": reel_id,
        "video_url": result.get("video_url"),
    }
