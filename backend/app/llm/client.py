from __future__ import annotations

import json
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.config import get_settings

# Kept in sync by hand with app/forum/routes.py's HazardType — not imported from there to avoid
# a forum <-> llm import cycle once the forum module enqueues LLM jobs (ticket 4).
HazardType = Literal[
    "pothole",
    "flooding",
    "broken_signal",
    "poor_lighting",
    "illegal_speed_bump",
    "crash",
    "other",
]
Severity = Literal["low", "medium", "high"]


class LlmError(Exception):
    """A controlled LLM provider or response-parsing failure."""


class LlmNotConfiguredError(LlmError):
    """Raised when a real Gemini call is attempted without GEMINI_API_KEY set."""


# Deterministic mock-path failure simulation, gated by settings.testing — mirrors
# route_job_tasks.py's `_test_crash_once` marker convention for testing fail-open/fail-closed
# behavior without depending on a real provider outage.
TEST_FAILURE_MARKER = "__llm_test_force_failure__"


def _raise_if_test_failure_requested(*texts: str) -> None:
    if any(TEST_FAILURE_MARKER in text for text in texts):
        raise LlmError("Simulated provider failure (test marker present).")


class TriageResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hazard_type_suggested: HazardType
    severity: Severity


class DuplicateJudgment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    is_duplicate: bool
    confidence: float


def _require_real_call_configured() -> None:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise LlmNotConfiguredError(
            "GEMINI_API_KEY is required to call Gemini when TESTING is not set"
        )


async def _call_gemini(prompt: str) -> Any:
    settings = get_settings()
    timeout = httpx.Timeout(
        connect=settings.gemini_request_timeout_seconds,
        read=settings.gemini_request_timeout_seconds,
        write=settings.gemini_request_timeout_seconds,
        pool=settings.gemini_request_timeout_seconds,
    )
    url = (
        f"{str(settings.gemini_base_url).rstrip('/')}/v1beta/models/"
        f"{settings.gemini_model}:generateContent"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, params={"key": settings.gemini_api_key}, json=body)
        response.raise_for_status()
        payload = response.json()
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise LlmError("The LLM provider is temporarily unavailable.") from exc


def _format_coordinates(coordinates: tuple[float, float] | None) -> str:
    if coordinates is None:
        return "unknown"
    longitude, latitude = coordinates
    return f"{longitude},{latitude}"


async def classify_report(
    body: str, hazard_type: HazardType, coordinates: tuple[float, float] | None
) -> TriageResult:
    if get_settings().testing:
        _raise_if_test_failure_requested(body)
        return TriageResult(hazard_type_suggested=hazard_type, severity="medium")
    _require_real_call_configured()
    prompt = (
        "Classify this road hazard report. Respond with strict JSON matching "
        '{"hazard_type_suggested": one of '
        '["pothole","flooding","broken_signal","poor_lighting","illegal_speed_bump","crash","other"], '
        '"severity": one of ["low","medium","high"]}.\n'
        f"Reporter-selected hazard type: {hazard_type}\n"
        f"Coordinates: {_format_coordinates(coordinates)}\n"
        f"Report text: {body}\n"
    )
    raw = await _call_gemini(prompt)
    try:
        return TriageResult.model_validate(raw)
    except ValidationError as exc:
        raise LlmError("The LLM provider returned an invalid classification.") from exc


async def compare_for_duplicate(report_a: str, report_b: str) -> DuplicateJudgment:
    if get_settings().testing:
        _raise_if_test_failure_requested(report_a, report_b)
        is_duplicate = report_a.strip().casefold() == report_b.strip().casefold()
        return DuplicateJudgment(is_duplicate=is_duplicate, confidence=1.0 if is_duplicate else 0.0)
    _require_real_call_configured()
    prompt = (
        "Do these two road hazard reports describe the same real-world hazard? Respond with "
        'strict JSON matching {"is_duplicate": boolean, "confidence": number between 0 and 1}.\n'
        f"Report A: {report_a}\n"
        f"Report B: {report_b}\n"
    )
    raw = await _call_gemini(prompt)
    try:
        return DuplicateJudgment.model_validate(raw)
    except ValidationError as exc:
        raise LlmError("The LLM provider returned an invalid duplicate judgment.") from exc


async def explain_route(cost_breakdown: dict[str, Any], user_context: dict[str, Any]) -> str:
    if get_settings().testing:
        _raise_if_test_failure_requested(
            json.dumps(cost_breakdown, default=str), json.dumps(user_context, default=str)
        )
        return "Deterministic test explanation."
    _require_real_call_configured()
    prompt = (
        "Explain in one short paragraph, in plain language, why this driving route was chosen "
        'over its alternatives. Respond with strict JSON matching {"explanation": string}.\n'
        f"Cost breakdown: {json.dumps(cost_breakdown, default=str)}\n"
        f"Driver context: {json.dumps(user_context, default=str)}\n"
    )
    raw = await _call_gemini(prompt)
    explanation = raw.get("explanation") if isinstance(raw, dict) else None
    if not isinstance(explanation, str) or not explanation.strip():
        raise LlmError("The LLM provider returned an invalid route explanation.")
    return explanation
