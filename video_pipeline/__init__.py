"""Standalone Celery/Redis video-rendering queue.

Not wired into any skill or into `lib/`. This is separate background-worker
infrastructure (requires a running Redis instance and `celery worker`
process), unlike the synchronous clients in `lib/`, which skills call
directly. See `video_pipeline/README.md` for setup.
"""
