from __future__ import annotations

import os

import httpx
import pytest


pytestmark = pytest.mark.integration

if os.getenv("RUN_GATEWAY_INTEGRATION") != "true":
    pytest.skip("requires the final Nginx Compose gateway", allow_module_level=True)


GATEWAY_URL = os.environ["GATEWAY_TEST_URL"]
API_URL = "http://api:8000"


def test_nginx_serves_the_compiled_application_and_proxies_api() -> None:
    page = httpx.get(f"{GATEWAY_URL}/", timeout=5)
    protected_api = httpx.get(f"{GATEWAY_URL}/api/auth/me", timeout=5)

    assert page.status_code == 200
    assert 'id="root"' in page.text
    assert "/assets/" in page.text
    assert protected_api.status_code == 401
    assert protected_api.json() == {"detail": "Authentication required."}


def test_gateway_keeps_test_routes_hidden_and_enforces_request_bound() -> None:
    hidden = httpx.post(f"{GATEWAY_URL}/api/testing/score-route-candidates", json={})
    oversized = httpx.post(
        f"{GATEWAY_URL}/api/auth/signup",
        content=b"x" * 17_000,
        headers={"content-type": "application/json"},
    )

    assert hidden.status_code == 404
    assert oversized.status_code == 413


def test_internal_readiness_reports_live_dependencies_and_worker_capacity() -> None:
    readiness = httpx.get(f"{API_URL}/health/ready", timeout=5)
    metrics = httpx.get(f"{API_URL}/health/metrics", timeout=5)

    assert readiness.status_code == 200
    checks = readiness.json()["checks"]
    assert set(checks) == {"database", "redis", "osrm", "data_compatibility", "queue_worker"}
    assert all(check["status"] == "ready" for check in checks.values())
    assert checks["queue_worker"]["workers"] >= 1
    assert checks["queue_worker"]["queue_capacity"] >= checks["queue_worker"]["queue_depth"]
    assert metrics.status_code == 200
    assert set(metrics.json()["metrics"]) == {
        "uptime_seconds", "upstream_failures", "queue_depth", "queue_capacity"
    }
