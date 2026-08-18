from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.routing.route_scoring_service import (
    LOW_COVERAGE_WARNING,
    RISK_METRIC_DESCRIPTION,
    RISK_METRIC_NAME,
    SAFETY_WEIGHT_CAP,
    SAFETY_WEIGHT_FLOOR,
    SCORING_FORMULA_VERSION,
    CandidateRouteMeasurement,
    UserScoringContext,
    score_route_candidates,
)
from app.routing.time_context import (
    TIME_CONTEXT_RULE_VERSION,
    get_israel_time_context,
)

ISRAEL_TIME_ZONE = ZoneInfo("Asia/Jerusalem")


def candidate(
    candidate_index: int,
    *,
    duration_seconds: float = 100.0,
    density: float = 2.0,
    coverage: float = 0.9,
) -> CandidateRouteMeasurement:
    return CandidateRouteMeasurement(
        candidate_index=candidate_index,
        distance_m=1_000.0,
        duration_seconds=duration_seconds,
        matched_route_length_m=coverage * 1_000.0,
        accident_score=density * coverage,
        historical_accident_density_per_km=density,
        coverage=coverage,
    )


def context(
    driving_experience: str = "experienced",
    vehicle_type: str = "car",
    hour: int = 12,
    safety_preference: str = "balanced",
) -> UserScoringContext:
    return UserScoringContext(
        driving_experience=driving_experience,  # type: ignore[arg-type]
        vehicle_type=vehicle_type,  # type: ignore[arg-type]
        submitted_at=datetime(2026, 1, 15, hour, tzinfo=ISRAEL_TIME_ZONE),
        safety_preference=safety_preference,  # type: ignore[arg-type]
    )


def score(
    candidates: list[CandidateRouteMeasurement],
    user_context: UserScoringContext | None = None,
    reference: float = 10.0,
):
    return score_route_candidates(
        candidates,
        user_context or context(),
        reference_risk_p95=reference,
        risk_data_version="risk-data-v7",
        low_coverage_threshold=0.8,
    )


@pytest.mark.parametrize(
    ("experience", "vehicle", "hour", "expected_factors", "expected_weight"),
    [
        ("experienced", "car", 12, (0.0, 0.0, 0.0, 0.0), 0.40),
        ("novice", "car", 12, (0.2, 0.0, 0.0, 0.0), 0.60),
        ("experienced", "motorcycle", 12, (0.0, 0.2, 0.0, 0.0), 0.60),
        ("experienced", "truck", 12, (0.0, 0.0, 0.1, 0.0), 0.50),
        ("experienced", "car", 5, (0.0, 0.0, 0.0, 0.1), 0.50),
        ("novice", "motorcycle", 5, (0.2, 0.2, 0.0, 0.1), 0.90),
        ("novice", "truck", 5, (0.2, 0.0, 0.1, 0.1), 0.80),
    ],
)
def test_safety_rule_returns_factors_cap_and_complementary_weights(
    experience: str,
    vehicle: str,
    hour: int,
    expected_factors: tuple[float, float, float, float],
    expected_weight: float,
) -> None:
    result = score([candidate(0)], context(experience, vehicle, hour))
    factors = result.safety_factor_contributions

    assert factors.base == 0.40
    assert (factors.novice, factors.motorcycle, factors.truck, factors.night) == expected_factors
    assert result.safety_weight == pytest.approx(expected_weight)
    assert result.time_weight == pytest.approx(1 - expected_weight)


@pytest.mark.parametrize(
    ("preference", "expected_weight"),
    [("low", 0.40 * 0.7), ("balanced", 0.40), ("high", 0.40 * 1.3)],
)
def test_safety_preference_multiplies_the_automatic_weight(
    preference: str, expected_weight: float
) -> None:
    result = score([candidate(0)], context("experienced", "car", 12, preference))

    assert result.safety_weight == pytest.approx(expected_weight)
    assert result.time_weight == pytest.approx(1 - expected_weight)
    assert result.safety_preference == preference
    assert result.safety_preference_multiplier == {"low": 0.7, "balanced": 1.0, "high": 1.3}[preference]
    # The automatic (pre-preference) factor breakdown is unaffected by the preference —
    # it still reflects the objective driving-experience/vehicle/time-of-day baseline.
    assert result.safety_factor_contributions.base == 0.40


def test_safety_preference_cap_still_applies_after_the_multiplier() -> None:
    # novice + motorcycle + night = 0.20+0.20+0.10+0.40 base = 0.90, already at the cap.
    # A 1.3x "high" multiplier on top of that must not push Wsafe above the cap.
    result = score([candidate(0)], context("novice", "motorcycle", 5, "high"))

    assert result.safety_weight == SAFETY_WEIGHT_CAP
    assert result.time_weight == pytest.approx(1 - SAFETY_WEIGHT_CAP)


def test_safety_preference_never_pushes_the_weight_below_the_floor() -> None:
    result = score([candidate(0)], context("experienced", "car", 12, "low"))

    assert result.safety_weight >= SAFETY_WEIGHT_FLOOR


@pytest.mark.parametrize(
    ("local_hour", "local_minute", "expected_period"),
    [(5, 59, "night"), (6, 0, "day"), (18, 59, "day"), (19, 0, "night")],
)
def test_israel_day_night_boundaries(
    local_hour: int, local_minute: int, expected_period: str
) -> None:
    submitted_at = datetime(
        2026, 2, 1, local_hour, local_minute, tzinfo=ISRAEL_TIME_ZONE
    )
    result = get_israel_time_context(submitted_at)

    assert result.period == expected_period
    assert result.rule_version == TIME_CONTEXT_RULE_VERSION


def test_israel_time_uses_real_summer_and_winter_offsets() -> None:
    winter = get_israel_time_context(datetime(2026, 1, 1, 4, tzinfo=timezone.utc))
    summer = get_israel_time_context(datetime(2026, 7, 1, 3, tzinfo=timezone.utc))

    assert winter.local_timestamp.hour == 6
    assert winter.local_timestamp.utcoffset().total_seconds() == 2 * 60 * 60
    assert summer.local_timestamp.hour == 6
    assert summer.local_timestamp.utcoffset().total_seconds() == 3 * 60 * 60
    assert winter.period == summer.period == "day"


def test_naive_submission_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="UTC offset"):
        score(
            [candidate(0)],
            UserScoringContext("experienced", "car", datetime(2026, 1, 1, 12), "balanced"),
        )


def test_normalization_is_fixed_uncapped_for_time_and_capped_for_risk() -> None:
    result = score(
        [
            candidate(0, duration_seconds=100, density=5),
            candidate(1, duration_seconds=400, density=25),
        ],
        reference=10,
    )

    fast, slow = result.candidates
    assert fast.time_penalty == 0
    assert fast.normalized_risk == pytest.approx(0.5)
    assert slow.time_penalty == pytest.approx(3.0)
    assert slow.normalized_risk == 1.0
    assert slow.time_contribution == pytest.approx(result.time_weight * 3.0)
    assert slow.safety_contribution == pytest.approx(result.safety_weight)
    assert slow.final_cost == pytest.approx(
        slow.time_contribution + slow.safety_contribution
    )


@pytest.mark.parametrize("reference", [0.0, -1.0, float("inf"), float("nan")])
def test_invalid_risk_reference_is_rejected(reference: float) -> None:
    with pytest.raises(ValueError, match="reference_risk_p95"):
        score([candidate(0)], reference=reference)


def test_equal_cost_prefers_lower_duration() -> None:
    result = score(
        [
            candidate(0, duration_seconds=100, density=5),
            candidate(1, duration_seconds=150, density=0),
        ],
        context("experienced", "truck", 12),
        reference=10,
    )
    assert result.candidates[0].final_cost == pytest.approx(
        result.candidates[1].final_cost
    )
    assert result.chosen_index == 0


def test_equal_cost_and_duration_prefer_lower_raw_density_after_risk_cap() -> None:
    result = score(
        [candidate(0, density=30), candidate(1, density=20)],
        reference=10,
    )
    assert result.candidates[0].final_cost == result.candidates[1].final_cost
    assert result.chosen_index == 1


def test_complete_tie_prefers_original_osrm_index() -> None:
    result = score([candidate(2), candidate(0), candidate(1)])
    assert result.chosen_index == 0


def test_single_candidate_and_low_coverage_are_reported_honestly() -> None:
    result = score([candidate(4, coverage=0.79)])

    assert result.chosen_index == 4
    assert result.risk_choice_available is False
    assert result.candidates[0].warning == LOW_COVERAGE_WARNING
    assert result.candidates[0].coverage == 0.79


def test_result_contains_raw_normalized_explanation_and_version_fields() -> None:
    result = score([candidate(0, duration_seconds=120, density=3, coverage=0.85)])
    scored = result.candidates[0]

    assert scored.distance_m == 1_000
    assert scored.duration_seconds == 120
    assert scored.matched_route_length_m == 850
    assert scored.accident_score == pytest.approx(2.55)
    assert scored.historical_accident_density_per_km == 3
    assert scored.time_penalty == 0
    assert scored.normalized_risk == pytest.approx(0.3)
    assert scored.time_contribution == 0
    assert scored.safety_contribution == pytest.approx(0.12)
    assert scored.final_cost == pytest.approx(0.12)
    assert result.reference_risk_p95 == 10
    assert result.risk_data_version == "risk-data-v7"
    assert result.formula_version == SCORING_FORMULA_VERSION
    assert result.risk_metric_name == RISK_METRIC_NAME
    assert result.risk_metric_description == RISK_METRIC_DESCRIPTION
    assert "historical" in result.risk_metric_description.casefold()
    assert "probability" not in result.risk_metric_description.casefold()
    assert "guarante" not in result.risk_metric_description.casefold()
