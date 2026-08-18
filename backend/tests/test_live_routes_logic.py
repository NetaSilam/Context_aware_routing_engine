from __future__ import annotations

import psycopg
import pytest
from fastapi import HTTPException

from app.config import Settings
from app.corridor_matcher import CorridorMatch
from app.routing import live_routes
from app.routing.live_routes import RerouteRequest, RerouteScoringContext
from app.routing.osrm_client import (
    OsrmErrorCode,
    OsrmLineString,
    OsrmNoRoute,
    OsrmProtocolError,
    OsrmRouteCandidate,
    OsrmRoutes,
    OsrmTransientError,
)


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://test:test@invalid.test:5432/test",
        redis_url="redis://invalid.test:6379/0",
        foundation_data_version="test-v1",
        jwt_secret="test-secret-with-at-least-32-characters",
        auth_allowed_origin="http://testserver",
        osrm_base_url="http://invalid.test:5000/",
        expected_osrm_graph_version="test-graph-v1",
        geocoder_base_url="http://invalid.test:5001/search",
        geocoder_user_agent="test-agent/1.0",
    )


def _reroute_request() -> RerouteRequest:
    return RerouteRequest(
        current_longitude=34.78,
        current_latitude=32.08,
        destination_longitude=34.79,
        destination_latitude=32.09,
        scoring_context=RerouteScoringContext(
            driving_experience="novice",
            vehicle_type="car",
            avoid_tolls=False,
            avoid_highways=False,
            safety_preference="balanced",
            reference_risk_p95=10,
            risk_data_version="test-risk-v1",
        ),
    )


def _osrm_routes() -> OsrmRoutes:
    candidate = OsrmRouteCandidate(
        distance=1000,
        duration=120,
        geometry=OsrmLineString(
            type="LineString", coordinates=[(34.78, 32.08), (34.79, 32.09)]
        ),
    )
    return OsrmRoutes(candidates=(candidate,))


class _FakeOsrmClient:
    """Configurable stand-in for OsrmClient: raises `fail_times` transient errors
    before returning `routes` (or the configured OsrmNoRoute/protocol error)."""

    fail_times = 0
    calls = 0
    protocol_error: OsrmProtocolError | None = None
    routes: OsrmRoutes | OsrmNoRoute | None = None

    def __init__(self, settings: Settings) -> None:
        del settings

    def __enter__(self) -> "_FakeOsrmClient":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def request_routes(self, **kwargs: object):
        del kwargs
        type(self).calls += 1
        if type(self).protocol_error is not None:
            raise type(self).protocol_error
        if type(self).calls <= type(self).fail_times:
            raise OsrmTransientError(OsrmErrorCode.TIMEOUT, "simulated timeout")
        return type(self).routes if type(self).routes is not None else _osrm_routes()


@pytest.fixture(autouse=True)
def reset_fake_osrm_client() -> None:
    _FakeOsrmClient.fail_times = 0
    _FakeOsrmClient.calls = 0
    _FakeOsrmClient.protocol_error = None
    _FakeOsrmClient.routes = None


def test_osrm_retry_succeeds_after_one_transient_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_routes, "OsrmClient", _FakeOsrmClient)
    _FakeOsrmClient.fail_times = 1

    result = live_routes._request_osrm_routes_with_retry(
        _settings(),
        origin_longitude=34.78,
        origin_latitude=32.08,
        destination_longitude=34.79,
        destination_latitude=32.09,
        avoid_highways=False,
        avoid_tolls=False,
    )

    assert isinstance(result, OsrmRoutes)
    assert _FakeOsrmClient.calls == 2


def test_osrm_retry_gives_up_after_two_transient_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_routes, "OsrmClient", _FakeOsrmClient)
    _FakeOsrmClient.fail_times = 2

    with pytest.raises(OsrmTransientError):
        live_routes._request_osrm_routes_with_retry(
            _settings(),
            origin_longitude=34.78,
            origin_latitude=32.08,
            destination_longitude=34.79,
            destination_latitude=32.09,
            avoid_highways=False,
            avoid_tolls=False,
        )
    assert _FakeOsrmClient.calls == 2


def test_compute_reroute_maps_exhausted_osrm_retry_to_typed_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_routes, "get_settings", _settings)
    monkeypatch.setattr(live_routes, "OsrmClient", _FakeOsrmClient)
    _FakeOsrmClient.fail_times = 99

    with pytest.raises(HTTPException) as excinfo:
        live_routes._compute_reroute(_reroute_request())

    assert excinfo.value.status_code == 503
    assert excinfo.value.detail["retryable"] is True
    assert excinfo.value.detail["error_code"] == "osrm_timeout"


def test_compute_reroute_maps_osrm_protocol_error_to_502_non_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_routes, "get_settings", _settings)
    monkeypatch.setattr(live_routes, "OsrmClient", _FakeOsrmClient)
    _FakeOsrmClient.protocol_error = OsrmProtocolError(
        OsrmErrorCode.INVALID_RESPONSE, "malformed"
    )

    with pytest.raises(HTTPException) as excinfo:
        live_routes._compute_reroute(_reroute_request())

    assert excinfo.value.status_code == 502
    assert excinfo.value.detail["retryable"] is False


def test_compute_reroute_maps_no_route_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_routes, "get_settings", _settings)
    monkeypatch.setattr(live_routes, "OsrmClient", _FakeOsrmClient)
    _FakeOsrmClient.routes = OsrmNoRoute()

    with pytest.raises(HTTPException) as excinfo:
        live_routes._compute_reroute(_reroute_request())

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["error_code"] == "no_route"


class _FakeConnection:
    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeConnectionPool:
    """Stand-in for the psycopg_pool.ConnectionPool: `.connection()` is where a
    checkout can fail, mirroring how `psycopg.connect()` used to be the failure point
    before reroute requests started reusing a pooled connection."""

    def __init__(self, checkout) -> None:
        self._checkout = checkout

    def connection(self) -> _FakeConnection:
        return self._checkout()


def test_db_retry_succeeds_after_one_operational_error(monkeypatch: pytest.MonkeyPatch) -> None:
    connect_calls = {"count": 0}

    def fake_checkout() -> _FakeConnection:
        connect_calls["count"] += 1
        if connect_calls["count"] == 1:
            raise psycopg.OperationalError("simulated connection drop")
        return _FakeConnection()

    monkeypatch.setattr(live_routes, "_get_db_pool", lambda settings: _FakeConnectionPool(fake_checkout))
    monkeypatch.setattr(
        live_routes,
        "match_route_candidates",
        lambda connection, matcher_inputs, **kwargs: [
            CorridorMatch(
                candidate_index=candidate.candidate_index,
                route_distance_m=candidate.distance_m,
                matched_route_length_m=candidate.distance_m,
                accident_score=0.0,
                historical_accident_density_per_km=0.0,
                coverage=1.0,
                low_coverage=False,
            )
            for candidate in matcher_inputs
        ],
    )

    matches = live_routes._match_route_candidates_with_retry(_settings(), [])
    assert matches == []
    assert connect_calls["count"] == 2


def test_compute_reroute_maps_exhausted_db_retry_to_typed_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_routes, "get_settings", _settings)
    monkeypatch.setattr(live_routes, "OsrmClient", _FakeOsrmClient)

    def always_fails() -> _FakeConnection:
        raise psycopg.OperationalError("database unreachable")

    monkeypatch.setattr(live_routes, "_get_db_pool", lambda settings: _FakeConnectionPool(always_fails))

    with pytest.raises(HTTPException) as excinfo:
        live_routes._compute_reroute(_reroute_request())

    assert excinfo.value.status_code == 503
    assert excinfo.value.detail["error_code"] == "database_unavailable"


def test_compute_reroute_happy_path_returns_scored_candidate_with_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_routes, "get_settings", _settings)
    monkeypatch.setattr(live_routes, "OsrmClient", _FakeOsrmClient)
    monkeypatch.setattr(
        live_routes,
        "match_route_candidates",
        lambda connection, matcher_inputs, **kwargs: [
            CorridorMatch(
                candidate_index=candidate.candidate_index,
                route_distance_m=candidate.distance_m,
                matched_route_length_m=candidate.distance_m * 0.9,
                accident_score=1.0,
                historical_accident_density_per_km=1.0,
                coverage=0.9,
                low_coverage=False,
            )
            for candidate in matcher_inputs
        ],
    )
    monkeypatch.setattr(live_routes, "_get_db_pool", lambda settings: _FakeConnectionPool(_FakeConnection))

    result = live_routes._compute_reroute(_reroute_request())

    assert result["schema_version"] == "reroute-result-v1"
    assert result["chosen_index"] == 0
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["steps"] == []
    assert result["risk_data_version"] == "test-risk-v1"


def test_reroute_request_rejects_unknown_fields() -> None:
    payload = _reroute_request().model_dump()
    payload["extra_field"] = "not allowed"

    with pytest.raises(Exception):
        RerouteRequest.model_validate(payload)
