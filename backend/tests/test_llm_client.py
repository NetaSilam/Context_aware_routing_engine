from __future__ import annotations

import asyncio

import httpx
import pytest

from app import llm as llm_package  # noqa: F401  (ensures app.llm package import works)
from app.config import Settings
from app.llm import client as llm_client
from app.llm.client import (
    LlmError,
    LlmNotConfiguredError,
    classify_report,
    compare_for_duplicate,
    explain_route,
)


def _settings(**overrides: object) -> Settings:
    base = {
        "database_url": "postgresql+psycopg://user:password@postgres:5432/test",
        "redis_url": "redis://redis:6379/0",
        "foundation_data_version": "fixture-v1",
        "jwt_secret": "test-secret-with-at-least-32-characters",
        "auth_allowed_origin": "http://localhost:5173",
        "osrm_base_url": "http://osrm:5000/",
        "expected_osrm_graph_version": "graph-v1",
        "geocoder_base_url": "http://geocoder:5001/search",
        "geocoder_user_agent": "road-risk-tests/1.0",
        "testing": False,
        "gemini_api_key": None,
    }
    base.update(overrides)
    return Settings(**base)


def _forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise AssertionError("httpx.AsyncClient must not be constructed on the mocked path")

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _raise)


def _mock_gemini_response(monkeypatch: pytest.MonkeyPatch, response_json: object, status_code: int = 200) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=response_json, request=request)

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", fake_async_client)


def _gemini_text_response(payload: dict) -> dict:
    import json

    return {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]}


# --- mocked (settings.testing = True) path: must never touch the network ---


def test_classify_report_mock_path_never_touches_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client, "get_settings", lambda: _settings(testing=True))
    _forbid_network(monkeypatch)

    result = asyncio.run(classify_report("Deep pothole", "pothole", (34.78, 32.07)))

    assert result.hazard_type_suggested == "pothole"
    assert result.severity == "medium"


def test_compare_for_duplicate_mock_path_never_touches_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client, "get_settings", lambda: _settings(testing=True))
    _forbid_network(monkeypatch)

    same = asyncio.run(compare_for_duplicate("Pothole near the junction", "  Pothole near the junction  "))
    different = asyncio.run(compare_for_duplicate("Pothole near the junction", "Flooded underpass"))

    assert same.is_duplicate is True
    assert same.confidence == 1.0
    assert different.is_duplicate is False
    assert different.confidence == 0.0


def test_explain_route_mock_path_never_touches_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client, "get_settings", lambda: _settings(testing=True))
    _forbid_network(monkeypatch)

    explanation = asyncio.run(explain_route({"final_cost": 1.0}, {"driving_experience": "novice"}))

    assert isinstance(explanation, str)
    assert explanation.strip()


# --- real-call path requires configuration ---


@pytest.mark.parametrize(
    "call",
    [
        lambda: classify_report("Deep pothole", "pothole", None),
        lambda: compare_for_duplicate("a", "b"),
        lambda: explain_route({}, {}),
    ],
)
def test_real_call_functions_raise_when_not_configured(monkeypatch: pytest.MonkeyPatch, call) -> None:
    monkeypatch.setattr(llm_client, "get_settings", lambda: _settings(testing=False, gemini_api_key=None))

    with pytest.raises(LlmNotConfiguredError):
        asyncio.run(call())


# --- response parsing/validation against fixed sample payloads ---


def test_classify_report_parses_a_well_formed_gemini_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        llm_client, "get_settings", lambda: _settings(testing=False, gemini_api_key="real-key")
    )
    _mock_gemini_response(
        monkeypatch,
        _gemini_text_response({"hazard_type_suggested": "flooding", "severity": "high"}),
    )

    result = asyncio.run(classify_report("Water covering the road", "pothole", (34.78, 32.07)))

    assert result.hazard_type_suggested == "flooding"
    assert result.severity == "high"


def test_classify_report_rejects_a_malformed_gemini_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        llm_client, "get_settings", lambda: _settings(testing=False, gemini_api_key="real-key")
    )
    _mock_gemini_response(
        monkeypatch,
        _gemini_text_response({"hazard_type_suggested": "not-a-real-hazard-type", "severity": "high"}),
    )

    with pytest.raises(LlmError, match="invalid classification"):
        asyncio.run(classify_report("Water covering the road", "pothole", None))


def test_call_gemini_wraps_an_http_error_as_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        llm_client, "get_settings", lambda: _settings(testing=False, gemini_api_key="real-key")
    )
    _mock_gemini_response(monkeypatch, {"error": "server exploded"}, status_code=503)

    with pytest.raises(LlmError, match="temporarily unavailable"):
        asyncio.run(classify_report("Water covering the road", "pothole", None))


def test_call_gemini_wraps_an_unparseable_body_shape_as_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        llm_client, "get_settings", lambda: _settings(testing=False, gemini_api_key="real-key")
    )
    _mock_gemini_response(monkeypatch, {"candidates": []})

    with pytest.raises(LlmError, match="temporarily unavailable"):
        asyncio.run(classify_report("Water covering the road", "pothole", None))


def test_explain_route_rejects_a_response_missing_the_explanation_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        llm_client, "get_settings", lambda: _settings(testing=False, gemini_api_key="real-key")
    )
    _mock_gemini_response(monkeypatch, _gemini_text_response({"unexpected": "shape"}))

    with pytest.raises(LlmError, match="invalid route explanation"):
        asyncio.run(explain_route({"final_cost": 1.0}, {}))
