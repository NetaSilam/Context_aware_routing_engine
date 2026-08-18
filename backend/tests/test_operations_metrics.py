from __future__ import annotations

import pytest
from redis.exceptions import RedisError

from app import operations
from app.operations import BoundedOperationsMetrics


class _FakeRedis:
    """In-memory INCR/GET stand-in — real counting semantics, not a rigged always-pass."""

    def __init__(self) -> None:
        self.store: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    def get(self, key: str) -> int | None:
        return self.store.get(key)


class _FailingRedis:
    def incr(self, key: str) -> int:
        raise RedisError("simulated redis outage")

    def get(self, key: str) -> int | None:
        raise RedisError("simulated redis outage")


def test_upstream_failures_accumulate_via_the_shared_redis_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRedis()
    monkeypatch.setattr(operations, "_get_sync_redis", lambda: fake)

    metrics = BoundedOperationsMetrics()
    metrics.record_upstream_failure()
    metrics.record_upstream_failure()
    snapshot = metrics.snapshot(queue_depth=0, queue_capacity=10)

    assert snapshot["upstream_failures"] == 2
    assert fake.store[operations._UPSTREAM_FAILURES_KEY] == 2


def test_upstream_failures_are_visible_across_separate_metrics_instances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulates two API replicas: each gets its own BoundedOperationsMetrics instance,
    # but both must see the same count since it's the whole point of moving off
    # in-process memory.
    fake = _FakeRedis()
    monkeypatch.setattr(operations, "_get_sync_redis", lambda: fake)

    BoundedOperationsMetrics().record_upstream_failure()
    second_replica_snapshot = BoundedOperationsMetrics().snapshot(queue_depth=0, queue_capacity=10)

    assert second_replica_snapshot["upstream_failures"] == 1


def test_record_upstream_failure_does_not_raise_when_redis_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(operations, "_get_sync_redis", lambda: _FailingRedis())

    BoundedOperationsMetrics().record_upstream_failure()  # must not raise


def test_snapshot_reports_a_distinct_sentinel_when_redis_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(operations, "_get_sync_redis", lambda: _FailingRedis())

    snapshot = BoundedOperationsMetrics().snapshot(queue_depth=3, queue_capacity=10)

    assert snapshot["upstream_failures"] == -1
    assert snapshot["queue_depth"] == 3
