"""RQ worker that processes the 'cpu' queue.

Run:
    rq worker cpu --url redis://localhost:6379/0

Or via docker compose:
    docker compose run --rm cpu-worker
"""
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rq import Worker, Queue, Connection
import redis


def main() -> None:
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    conn = redis.Redis.from_url(redis_url)
    with Connection(conn):
        worker = Worker(queues=["cpu"], connection=conn)
        worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
