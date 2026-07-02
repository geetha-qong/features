"""Cross-worker startup coordination (FEATURES #121).

When the web container runs with more than one uvicorn worker
(``--workers N``), every worker process re-imports ``webapp.main`` and would
therefore run the import-time startup side-effects N times in parallel:

  - ``run_migrations()``      — kept per-worker on purpose; it is race-safe
                               (existence/column-state probes) and MUST finish
                               before that worker serves a request touching a
                               new column.
  - ``start_watchdog()``      — spawns a background reaper thread; N of them
                               would contend and double-reap.
  - LS webhook reconcile      — N concurrent Label-Studio API sweeps; wasteful
                               and can double-register / double-enqueue.
  - stale-job reset, super-admin promote, agent-memory init — idempotent, but
                               no reason to run them N times.

``should_run_startup_tasks()`` elects exactly ONE worker (the first to win a
Redis ``SET NX``) to run those one-shot side-effects. Everyone else skips them.

Fallbacks (always run the tasks rather than silently skipping them all):
  - No ``REDIS_URL``  → local / single-worker dev: return True.
  - Redis unreachable → degrade to "run them here" so a Redis blip can never
    leave the deploy with NO watchdog at all. NOTE: in this degraded mode the
    "exactly one worker" guarantee does NOT hold — every worker returns True and
    runs the tasks. That is the intended trade-off (the gated tasks are all
    idempotent; a duplicated run is wasteful but safe, whereas zero runs is not).

The lock carries a short TTL (default 30s) and is never explicitly released.
That window comfortably covers uvicorn's near-instant worker spawn, while
expiring long before any realistic redeploy (deploys take minutes), so the
next container start re-elects a fresh leader.
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_STARTUP_LOCK_KEY = "qong:web:startup-leader"
_STARTUP_LOCK_TTL_S = 30


def should_run_startup_tasks(
    lock_key: str = _STARTUP_LOCK_KEY,
    ttl_s: int = _STARTUP_LOCK_TTL_S,
    redis_url: Optional[str] = None,
) -> bool:
    """Return True iff this worker should run one-shot startup side-effects.

    Exactly one worker wins per container boot; the rest get False. Degrades to
    True when Redis is absent or unreachable so the tasks are never all skipped.
    """
    url = redis_url if redis_url is not None else os.environ.get("REDIS_URL")
    if not url:
        # Local dev / single worker with no broker — just run them.
        return True
    try:
        import redis  # local import: keeps the module importable without redis

        conn = redis.Redis.from_url(url)
        acquired = conn.set(lock_key, str(os.getpid()), nx=True, ex=ttl_s)
        if acquired:
            logger.info("startup leader-lock acquired (pid=%s) — running one-shot tasks", os.getpid())
            return True
        logger.info("startup leader-lock held by another worker — skipping one-shot tasks")
        return False
    except Exception as e:  # connection refused, auth, etc.
        logger.warning(
            "startup leader-lock unavailable (%s) — running one-shot tasks in this worker", e
        )
        return True
