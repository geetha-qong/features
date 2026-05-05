"""RQ worker that processes the 'cpu' queue."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rq import Worker, Queue
import redis


def main() -> None:
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    conn = redis.Redis.from_url(redis_url)
    worker = Worker(queues=[Queue("cpu", connection=conn)], connection=conn)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
