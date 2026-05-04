"""RQ queue wiring — cpu and gpu queues backed by Redis."""
import os
from typing import Optional
import redis
from rq import Queue

_redis_conn: Optional[redis.Redis] = None
cpu_q: Optional[Queue] = None
gpu_q: Optional[Queue] = None


def _init() -> None:
    global _redis_conn, cpu_q, gpu_q
    if cpu_q is not None:
        return
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    _redis_conn = redis.Redis.from_url(url)
    cpu_q = Queue("cpu", connection=_redis_conn)
    gpu_q = Queue("gpu", connection=_redis_conn)


def get_cpu_queue() -> Queue:
    _init()
    return cpu_q


def get_gpu_queue() -> Queue:
    _init()
    return gpu_q
