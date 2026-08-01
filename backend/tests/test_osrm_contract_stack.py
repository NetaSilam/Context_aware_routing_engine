from __future__ import annotations

import os

import pytest

from app.config import Settings
from app.routing.osrm_client import (
    OsrmClient,
    OsrmErrorCode,
    OsrmNoRoute,
    OsrmProtocolError,
    OsrmRoutes,
    OsrmTransientError,
)


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_OSRM_CONTRACT_INTEGRATION") != "true",
        reason="requires the deterministic fake OSRM Compose service",
    ),
]


BASE_URL = os.getenv("OSRM_CONTRACT_BASE_URL", "http://fake-osrm:5000")


def settings_for(scenario: str, *, timeout: float = 0.5) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://test:test@invalid.test:5432/test",
        redis_url="redis://invalid.test:6379/0",
        foundation_data_version="test-v1",
        jwt_secret="test-secret-with-at-least-32-characters",
        auth_allowed_origin="http://testserver",
        osrm_base_url=f"{BASE_URL}/{scenario}/",
        osrm_connect_timeout_seconds=0.5,
        osrm_response_timeout_seconds=timeout,
        osrm_max_connections=4,
        osrm_max_keepalive_connections=2,
    )


def request(scenario: str, *, timeout: float = 0.5, **preferences: bool):
    with OsrmClient(settings_for(scenario, timeout=timeout)) as client:
        return client.request_routes(
            origin_longitude=34.78,
            origin_latitude=32.08,
            destination_longitude=34.79,
            destination_latitude=32.09,
            avoid_highways=preferences.get("avoid_highways", False),
            avoid_tolls=preferences.get("avoid_tolls", False),
        )


@pytest.mark.parametrize(
    ("preferences", "expected_distance"),
    [
        ({}, 1000),
        ({"avoid_highways": True}, 1100),
        ({"avoid_tolls": True}, 1200),
        ({"avoid_highways": True, "avoid_tolls": True}, 1300),
    ],
)
def test_real_http_request_serializes_contract_and_preferences(
    preferences: dict[str, bool], expected_distance: float
) -> None:
    result = request("normal", **preferences)

    assert isinstance(result, OsrmRoutes)
    assert len(result.candidates) == 3
    assert result.candidates[0].distance == expected_distance
    assert result.risk_choice_available is True


def test_one_candidate_is_accepted() -> None:
    result = request("one-route")

    assert isinstance(result, OsrmRoutes)
    assert len(result.candidates) == 1
    assert result.risk_choice_available is False


def test_success_response_without_routes_is_a_protocol_failure() -> None:
    with pytest.raises(OsrmProtocolError) as captured:
        request("missing-routes")

    assert captured.value.code == OsrmErrorCode.INVALID_RESPONSE
    assert captured.value.retryable is False


@pytest.mark.parametrize("scenario", ["no-route", "no-candidates"])
def test_no_route_responses_are_stable_non_retryable_results(scenario: str) -> None:
    result = request(scenario)

    assert isinstance(result, OsrmNoRoute)
    assert result.code == OsrmErrorCode.NO_ROUTE
    assert result.retryable is False


def test_delayed_response_inside_configured_timeout_succeeds() -> None:
    assert isinstance(request("delay", timeout=0.5), OsrmRoutes)


def test_timeout_is_transient() -> None:
    with pytest.raises(OsrmTransientError) as captured:
        request("timeout", timeout=0.01)

    assert captured.value.code == OsrmErrorCode.TIMEOUT
    assert captured.value.retryable is True


def test_server_error_is_transient() -> None:
    with pytest.raises(OsrmTransientError) as captured:
        request("server-error")

    assert captured.value.code == OsrmErrorCode.SERVER_ERROR
    assert captured.value.retryable is True


@pytest.mark.parametrize(
    ("scenario", "expected_code"),
    [
        ("unsupported-option", OsrmErrorCode.UNSUPPORTED_OPTION),
        ("malformed-json", OsrmErrorCode.INVALID_RESPONSE),
        ("invalid-geometry", OsrmErrorCode.INVALID_GEOMETRY),
    ],
)
def test_protocol_failures_are_controlled_and_non_retryable(
    scenario: str, expected_code: OsrmErrorCode
) -> None:
    with pytest.raises(OsrmProtocolError) as captured:
        request(scenario)

    assert captured.value.code == expected_code
    assert captured.value.retryable is False
