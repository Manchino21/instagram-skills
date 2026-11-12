"""Reads a JSON prompt manifest and queues a render task per entry.

Re-running the same manifest (e.g. after a crash) skips entries already
queued, so it is safe to re-run without piling up duplicate renders.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import redis

from .celery_app import app
from .dedup import mark_dispatched_if_new
from .tasks import render_video_task


def dispatch_render_batch(manifest_items: list[dict]) -> list[dict]:
    redis_client = redis.Redis.from_url(app.conf.broker_url)
    dispatched_jobs = []

    for item in manifest_items:
        reel_id = item["id"]
        if not mark_dispatched_if_new(redis_client, reel_id):
            print(f"Skipping '{item.get('title', reel_id)}' -> already dispatched")
            continue

        result = render_video_task.delay(item)
        dispatched_jobs.append({"reel_id": reel_id, "task_id": result.id})
        print(f"Dispatched '{item.get('title', reel_id)}' -> Task ID: {result.id}")

    print(f"\nQueued {len(dispatched_jobs)} new task(s) "
          f"({len(manifest_items) - len(dispatched_jobs)} already dispatched, skipped).")
    return dispatched_jobs


def load_manifest(path: str) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m video_pipeline.dispatcher <manifest.json>")
        sys.exit(1)

    dispatch_render_batch(load_manifest(sys.argv[1]))
