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
