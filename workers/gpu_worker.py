"""
RQ worker for the 'gpu' queue — runs on the Windows GPU box.

Setup (Windows PowerShell, once):
    pip install rq redis requests

Run (foreground):
    set REDIS_URL=redis://100.127.190.88:6379/0
    python workers/gpu_worker.py

Run as background service via NSSM:
    nssm install QongGpuWorker "C:\Python311\python.exe" "C:\qong_poc\workers\gpu_worker.py"
    nssm set QongGpuWorker AppEnvironmentExtra REDIS_URL=redis://100.127.190.88:6379/0
    nssm set QongGpuWorker AppDirectory C:\qong_poc
    nssm start QongGpuWorker

The worker consumes jobs from the 'gpu' queue.  Each job calls
run_inference(job_id, tile_paths) and returns a list of detection dicts.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rq import Worker, Queue
import redis


def main() -> None:
    redis_url = os.environ.get("REDIS_URL", "redis://100.127.190.88:6379/0")
    conn = redis.Redis.from_url(redis_url)
    print(f"Connecting to Redis at {redis_url} ...")
    conn.ping()
    print("Redis OK — listening on 'gpu' queue")
    worker = Worker(queues=[Queue("gpu", connection=conn)], connection=conn)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
