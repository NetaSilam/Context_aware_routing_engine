from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


def scoring_payload() -> dict[str, object]:
    return {
        "candidates": [
            {
                "candidate_index": 0,
                "distance_m": 1_000,
                "duration_seconds": 120,
                "matched_route_length_m": 900,
                "accident_score": 2.7,
                "historical_accident_density_per_km": 3,
                "coverage": 0.9,
            },
            {
                "candidate_index": 1,
                "distance_m": 1_100,
                "duration_seconds": 130,
                "matched_route_length_m": 770,
                "accident_score": 0.77,
                "historical_accident_density_per_km": 1,
                "coverage": 0.7,
            },
        ],
        "context": {
            "driving_experience": "novice",
            "vehicle_type": "car",
            "submitted_at": "2026-01-15T20:00:00+02:00",
        },
        "reference_risk_p95": 10,
        "risk_data_version": "risk-data-v7",
        "low_coverage_threshold": 0.8,
    }


def test_scoring_endpoint_is_absent_when_testing_is_disabled(monkeypatch) -> None:
    monkeypatch.setenv("TESTING", "false")
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            response = client.post(
                "/api/testing/score-route-candidates", json=scoring_payload()
            )
        assert response.status_code == 404
    finally:
        get_settings.cache_clear()


def test_scoring_endpoint_exposes_pure_contract_only_when_testing_is_enabled(
    monkeypatch,
) -> None:
    monkeypatch.setenv("TESTING", "true")
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            response = client.post("/api/testing/score-route-candidates", json=scoring_payload())
        assert response.status_code == 200
        body = response.json()
        assert body["chosen_index"] == 1
        assert body["risk_choice_available"] is True
        assert body["formula_version"] == "route-scoring-v1"
        assert body["risk_data_version"] == "risk-data-v7"
        assert body["safety_weight"] == pytest.approx(0.7)
        assert body["time_weight"] == pytest.approx(0.3)
        assert body["safety_factor_contributions"] == {
            "base": 0.4,
            "novice": 0.2,
            "motorcycle": 0.0,
            "truck": 0.0,
            "night": 0.1,
        }
        assert body["candidates"][1]["warning"] is not None
    finally:
        get_settings.cache_clear()


def test_scoring_endpoint_applies_the_safety_preference_multiplier(monkeypatch) -> None:
    monkeypatch.setenv("TESTING", "true")
    get_settings.cache_clear()
    try:
        payload = scoring_payload()
        payload["context"]["driving_experience"] = "experienced"  # type: ignore[index]
        payload["context"]["safety_preference"] = "high"  # type: ignore[index]
        with TestClient(create_app()) as client:
            response = client.post("/api/testing/score-route-candidates", json=payload)
        assert response.status_code == 200
        body = response.json()
        # Automatic weight here is 0.5 (base 0.4 + night 0.1); "high" is 1.3x -> 0.65,
        # comfortably under the 0.90 cap so this actually exercises the multiplier.
        assert body["safety_weight"] == pytest.approx(0.5 * 1.3)
        assert body["safety_preference"] == "high"
        assert body["safety_preference_multiplier"] == pytest.approx(1.3)
    finally:
        get_settings.cache_clear()


def test_scoring_endpoint_rejects_invalid_reference_and_naive_timestamp(
    monkeypatch,
) -> None:
    monkeypatch.setenv("TESTING", "true")
    get_settings.cache_clear()
    try:
        payload = scoring_payload()
        payload["reference_risk_p95"] = 0
        payload["context"]["submitted_at"] = "2026-01-15T20:00:00"  # type: ignore[index]
        with TestClient(create_app()) as client:
            response = client.post("/api/testing/score-route-candidates", json=payload)
        assert response.status_code == 422
    finally:
        get_settings.cache_clear()


def test_scoring_endpoint_rejects_duplicate_candidate_indexes(monkeypatch) -> None:
    monkeypatch.setenv("TESTING", "true")
    get_settings.cache_clear()
    try:
        payload = scoring_payload()
        payload["candidates"][1]["candidate_index"] = 0  # type: ignore[index]
        with TestClient(create_app()) as client:
            response = client.post("/api/testing/score-route-candidates", json=payload)
        assert response.status_code == 422
    finally:
        get_settings.cache_clear()
