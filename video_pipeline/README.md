# video_pipeline

Standalone Celery/Redis queue for background video rendering. This is
separate infrastructure, not wired into any skill or into `lib/`: skills in
this bundle call synchronous clients (Publora, Pixfaro) directly, while this
package requires a running Redis instance and a `celery worker` process.

## Why not just `requests.post()`

The render API enforces a strict rate limit. This queue decouples prompt
generation from rendering, retries on transient failures with backoff, and
caps throughput globally (not per-worker) so scaling worker count never
exceeds the API's real limit.

## Setup

```bash
pip install -r video_pipeline/requirements.txt
```

Config (environment variables, all optional with defaults suited to local dev):

| Variable | Default | Purpose |
|---|---|---|
| `VIDEO_QUEUE_REDIS_BROKER_URL` | `redis://localhost:6379/0` | Celery broker |
| `VIDEO_QUEUE_REDIS_BACKEND_URL` | `redis://localhost:6379/1` | Celery result backend |
| `VIDEO_QUEUE_WORKER_CONCURRENCY` | `4` | Concurrent tasks per worker process |
| `VIDEO_RENDER_API_URL` | `https://api.example.com/v1/render` | Render endpoint |
| `VIDEO_RENDER_API_KEY` | (unset) | Bearer token for the render API |
| `VIDEO_RENDER_RATE_LIMIT_PER_MINUTE` | `2` | Global cap shared by every worker, see below |

## Running

```bash
redis-server
celery -A video_pipeline.celery_app worker --loglevel=info
python -m video_pipeline.dispatcher video_pipeline/sample_manifest.json
```

## Design notes (fixes over the original sketch)

1. **Global rate limit, not per-worker.** Celery's own `rate_limit=` is
   enforced independently inside each worker process, so running N workers
   multiplies the effective throughput by N and can blow past the API's real
   limit. `rate_limiter.py` keeps the counter in Redis instead, shared by
   every worker, so `VIDEO_RENDER_RATE_LIMIT_PER_MINUTE` is a true global cap
   regardless of how many workers are running.
2. **Idempotent dispatch.** `dedup.py` marks a reel ID as dispatched (and
   later as completed) in Redis. Re-running `dispatcher.py` over the same
   manifest after a crash skips reels already queued or rendered instead of
   double-dispatching them.
3. **429 handled by reading `Retry-After`.** `tasks.py` makes the real HTTP
   request (`raise_for_status()` is live, not commented out) and, on a 429,
   retries after exactly the duration the server asked for rather than a
   generic backoff.
4. **One retry mechanism per error path.** The 429 path above is the only
   place the task calls `self.retry()` manually, because it needs a specific
   countdown the decorator can't express. Every other retryable error
   (connection errors, timeouts, non-429 HTTP errors) is left alone to
   propagate out of the task function, where the task's own
   `autoretry_for=(...)` + `retry_backoff=True` takes over. The original
   sketch wrapped the whole call in `try/except` and called `self.retry()`
   on anything, which fired immediately with no countdown and bypassed the
   configured backoff entirely.
