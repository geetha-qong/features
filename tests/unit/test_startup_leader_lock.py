"""Unit tests for the multi-worker startup leader-lock (FEATURES #121).

`should_run_startup_tasks` must elect exactly ONE worker to run the one-shot
startup side-effects (watchdog, LS reconcile) and degrade safely when Redis is
absent or unreachable (run them rather than skip them all).
"""
import sys
import types

from webapp.startup import should_run_startup_tasks


def test_no_redis_url_runs_tasks(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert should_run_startup_tasks(redis_url=None) is True


def test_explicit_empty_url_runs_tasks():
    assert should_run_startup_tasks(redis_url="") is True


def _install_fake_redis(monkeypatch, store):
    """Install a fake `redis` module whose Redis.set honours NX against `store`."""
    class _FakeRedis:
        def __init__(self, *a, **k):
            pass

        def set(self, key, value, nx=False, ex=None):
            if nx and key in store:
                return None  # someone already holds it
            store[key] = value
            return True

    fake = types.ModuleType("redis")
    fake.Redis = type("Redis", (), {"from_url": staticmethod(lambda url: _FakeRedis())})
    monkeypatch.setitem(sys.modules, "redis", fake)


def test_first_worker_wins_rest_skip(monkeypatch):
    store: dict = {}
    _install_fake_redis(monkeypatch, store)
    # First worker to acquire the lock runs the tasks…
    assert should_run_startup_tasks(redis_url="redis://x:6379/0") is True
    # …subsequent workers see the held lock and skip.
    assert should_run_startup_tasks(redis_url="redis://x:6379/0") is False
    assert should_run_startup_tasks(redis_url="redis://x:6379/0") is False


def test_distinct_lock_keys_are_independent(monkeypatch):
    store: dict = {}
    _install_fake_redis(monkeypatch, store)
    assert should_run_startup_tasks(lock_key="a", redis_url="redis://x") is True
    assert should_run_startup_tasks(lock_key="b", redis_url="redis://x") is True
    assert should_run_startup_tasks(lock_key="a", redis_url="redis://x") is False


def test_redis_failure_degrades_to_running(monkeypatch):
    """A Redis blip must never leave the deploy with NO worker running startup."""
    def _boom(url):
        raise ConnectionError("redis down")

    fake = types.ModuleType("redis")
    fake.Redis = type("Redis", (), {"from_url": staticmethod(_boom)})
    monkeypatch.setitem(sys.modules, "redis", fake)
    assert should_run_startup_tasks(redis_url="redis://x:6379/0") is True
