"""Celery app configuration for the video-rendering queue.

Broker and backend URLs are read from the environment so the same code
runs against local Redis in dev and a real Redis host in production.
"""
from __future__ import annotations

import os

from celery import Celery

REDIS_BROKER_URL = os.environ.get("VIDEO_QUEUE_REDIS_BROKER_URL", "redis://localhost:6379/0")
REDIS_BACKEND_URL = os.environ.get("VIDEO_QUEUE_REDIS_BACKEND_URL", "redis://localhost:6379/1")

app = Celery(
    "video_pipeline",
    broker=REDIS_BROKER_URL,
    backend=REDIS_BACKEND_URL,
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_concurrency=int(os.environ.get("VIDEO_QUEUE_WORKER_CONCURRENCY", "4")),
    task_track_started=True,
    # Celery's per-task `rate_limit` is enforced independently by each worker
    # process, so N workers would together exceed the configured rate by a
    # factor of N. The actual cap on the render API is enforced globally
    # inside the task via a Redis-backed counter shared by every worker
    # (see `rate_limiter.py`), not via Celery's `rate_limit`.
    result_expires=3600,
)
