import asyncio

import pytest
from fastapi.testclient import TestClient

from app import health
from app.main import create_app


def test_liveness_does_not_require_dependency_connections() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_readiness_reports_an_unavailable_required_dependency(monkeypatch) -> None:
    async def unavailable_database() -> dict[str, str]:
        raise ConnectionError("test database unavailable")

    async def available_redis() -> dict[str, str]:
        return {"status": "ready"}

    async def available_osrm(_: str | None) -> dict[str, str]:
        return {"status": "ready"}

    async def available_osrm_service() -> dict[str, str]:
        return {"status": "ready"}

    async def available_queue_worker() -> dict[str, str]:
        return {"status": "ready"}

    monkeypatch.setattr(health, "_database_readiness", unavailable_database)
    monkeypatch.setattr(health, "_redis_readiness", available_redis)
    monkeypatch.setattr(health, "_osrm_compatibility_readiness", available_osrm)
    monkeypatch.setattr(health, "_osrm_service_readiness", available_osrm_service)
    monkeypatch.setattr(health, "_queue_worker_readiness", available_queue_worker)

    with TestClient(create_app()) as client:
        ready_response = client.get("/health/ready")
        live_response = client.get("/health/live")

    assert ready_response.status_code == 503
    assert ready_response.json() == {
        "status": "not_ready",
        "checks": {
            "database": {
                "status": "unavailable",
                "reason": "test database unavailable",
            },
            "redis": {"status": "ready"},
            "osrm": {"status": "ready"},
            "data_compatibility": {"status": "ready"},
            "queue_worker": {"status": "ready"},
        },
    }
    assert live_response.status_code == 200


class _FakeInspect:
    def __init__(self, replies: dict[str, dict[str, str]]) -> None:
        self._replies = replies

    def ping(self) -> dict[str, dict[str, str]]:
        return self._replies


class _FakeControl:
    def __init__(self, replies: dict[str, dict[str, str]]) -> None:
        self._replies = replies

    def inspect(self, timeout: float | None = None) -> _FakeInspect:
        return _FakeInspect(self._replies)


class _FakeCelery:
    def __init__(self, name: str, broker: str, replies: dict[str, dict[str, str]]) -> None:
        self.control = _FakeControl(replies)

    def close(self) -> None:
        pass


def _fake_celery_factory(replies: dict[str, dict[str, str]]):
    def factory(name: str, broker: str) -> _FakeCelery:
        return _FakeCelery(name, broker, replies)

    return factory


class _FakeRedis:
    async def scard(self, _key: str) -> int:
        return 0


def test_queue_worker_readiness_ignores_an_llm_worker_only_ping_reply(monkeypatch) -> None:
    # Celery's inspect().ping() broadcasts to every worker sharing the broker, including the
    # unrelated llm-worker (app/llm/tasks.py). Readiness must not treat that reply as proof the
    # routing worker is alive — see docs/CODEBASE_MAP.md's "Important boundaries".
    monkeypatch.setattr(
        health, "Celery", _fake_celery_factory({"celery@llm-worker-abc123": {"ok": "pong"}})
    )
    monkeypatch.setattr(health, "get_redis", lambda: _FakeRedis())

    with pytest.raises(RuntimeError, match="no route worker responded"):
        asyncio.run(health._queue_worker_readiness())


def test_queue_worker_readiness_accepts_a_genuine_route_worker_reply(monkeypatch) -> None:
    monkeypatch.setattr(
        health,
        "Celery",
        _fake_celery_factory(
            {
                "celery@llm-worker-abc123": {"ok": "pong"},
                "celery@a1b2c3d4e5f6": {"ok": "pong"},
            }
        ),
    )
    monkeypatch.setattr(health, "get_redis", lambda: _FakeRedis())

    result = asyncio.run(health._queue_worker_readiness())

    assert result["status"] == "ready"
    assert result["workers"] == 1
