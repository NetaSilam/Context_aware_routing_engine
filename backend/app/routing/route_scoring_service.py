from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Sequence

from app.routing.time_context import IsraelTimeContext, get_israel_time_context

DrivingExperience = Literal["novice", "experienced"]
VehicleType = Literal["car", "motorcycle", "truck"]

SCORING_FORMULA_VERSION = "route-scoring-v1"
RISK_METRIC_NAME = "historical_accident_density_per_km"
RISK_METRIC_DESCRIPTION = (
    "Historical accident density is a historical risk proxy based on matched corridors."
)
LOW_COVERAGE_WARNING = (
    "Historical accident density is based on incomplete corridor coverage."
)


@dataclass(frozen=True)
class CandidateRouteMeasurement:
    candidate_index: int
    distance_m: float
    duration_seconds: float
    matched_route_length_m: float
    accident_score: float
    historical_accident_density_per_km: float
    coverage: float


@dataclass(frozen=True)
class UserScoringContext:
    driving_experience: DrivingExperience
    vehicle_type: VehicleType
    submitted_at: datetime


@dataclass(frozen=True)
class SafetyFactorContributions:
    base: float
    novice: float
    motorcycle: float
    truck: float
    night: float

    @property
    def uncapped_total(self) -> float:
        return self.base + self.novice + self.motorcycle + self.truck + self.night


@dataclass(frozen=True)
class ScoredCandidate:
    candidate_index: int
    distance_m: float
    duration_seconds: float
    matched_route_length_m: float
    accident_score: float
    historical_accident_density_per_km: float
    coverage: float
    warning: str | None
    time_penalty: float
    normalized_risk: float
    time_contribution: float
    safety_contribution: float
    final_cost: float


@dataclass(frozen=True)
class RouteScoringResult:
    candidates: tuple[ScoredCandidate, ...]
    chosen_index: int
    risk_choice_available: bool
    safety_weight: float
    time_weight: float
    safety_factor_contributions: SafetyFactorContributions
    reference_risk_p95: float
    low_coverage_threshold: float
    risk_data_version: str
    formula_version: str
    risk_metric_name: str
    risk_metric_description: str
    time_context: IsraelTimeContext


def calculate_safety_factors(
    context: UserScoringContext, time_context: IsraelTimeContext
) -> SafetyFactorContributions:
    _validate_context(context)
    return SafetyFactorContributions(
        base=0.40,
        novice=0.20 if context.driving_experience == "novice" else 0.0,
        motorcycle=0.20 if context.vehicle_type == "motorcycle" else 0.0,
        truck=0.10 if context.vehicle_type == "truck" else 0.0,
        night=0.10 if time_context.is_night else 0.0,
    )


def score_route_candidates(
    candidates: Sequence[CandidateRouteMeasurement],
    context: UserScoringContext,
    *,
    reference_risk_p95: float,
    risk_data_version: str,
    low_coverage_threshold: float,
) -> RouteScoringResult:
    """Normalize and rank already-measured OSRM candidates without infrastructure access."""
    _validate_scoring_inputs(
        candidates,
        reference_risk_p95=reference_risk_p95,
        risk_data_version=risk_data_version,
        low_coverage_threshold=low_coverage_threshold,
    )
    time_context = get_israel_time_context(context.submitted_at)
    factors = calculate_safety_factors(context, time_context)
    safety_weight = min(factors.uncapped_total, 0.90)
    time_weight = 1.0 - safety_weight
    fastest_duration = min(candidate.duration_seconds for candidate in candidates)

    scored_candidates: list[ScoredCandidate] = []
    for candidate in candidates:
        time_penalty = (
            candidate.duration_seconds - fastest_duration
        ) / fastest_duration
        normalized_risk = min(
            candidate.historical_accident_density_per_km / reference_risk_p95,
            1.0,
        )
        time_contribution = time_weight * time_penalty
        safety_contribution = safety_weight * normalized_risk
        scored_candidates.append(
            ScoredCandidate(
                candidate_index=candidate.candidate_index,
                distance_m=candidate.distance_m,
                duration_seconds=candidate.duration_seconds,
                matched_route_length_m=candidate.matched_route_length_m,
                accident_score=candidate.accident_score,
                historical_accident_density_per_km=(
                    candidate.historical_accident_density_per_km
                ),
                coverage=candidate.coverage,
                warning=(
                    LOW_COVERAGE_WARNING
                    if candidate.coverage < low_coverage_threshold
                    else None
                ),
                time_penalty=time_penalty,
                normalized_risk=normalized_risk,
                time_contribution=time_contribution,
                safety_contribution=safety_contribution,
                final_cost=time_contribution + safety_contribution,
            )
        )

    chosen = min(
        scored_candidates,
        key=lambda candidate: (
            candidate.final_cost,
            candidate.duration_seconds,
            candidate.historical_accident_density_per_km,
            candidate.candidate_index,
        ),
    )
    return RouteScoringResult(
        candidates=tuple(scored_candidates),
        chosen_index=chosen.candidate_index,
        risk_choice_available=len(scored_candidates) > 1,
        safety_weight=safety_weight,
        time_weight=time_weight,
        safety_factor_contributions=factors,
        reference_risk_p95=reference_risk_p95,
        low_coverage_threshold=low_coverage_threshold,
        risk_data_version=risk_data_version,
        formula_version=SCORING_FORMULA_VERSION,
        risk_metric_name=RISK_METRIC_NAME,
        risk_metric_description=RISK_METRIC_DESCRIPTION,
        time_context=time_context,
    )


def _validate_context(context: UserScoringContext) -> None:
    if context.driving_experience not in ("novice", "experienced"):
        raise ValueError("unsupported driving_experience")
    if context.vehicle_type not in ("car", "motorcycle", "truck"):
        raise ValueError("unsupported vehicle_type")


def _validate_scoring_inputs(
    candidates: Sequence[CandidateRouteMeasurement],
    *,
    reference_risk_p95: float,
    risk_data_version: str,
    low_coverage_threshold: float,
) -> None:
    if not candidates:
        raise ValueError("at least one candidate is required")
    if not math.isfinite(reference_risk_p95) or reference_risk_p95 <= 0:
        raise ValueError("reference_risk_p95 must be finite and greater than zero")
    if not risk_data_version.strip():
        raise ValueError("risk_data_version must not be empty")
    if not math.isfinite(low_coverage_threshold) or not 0 <= low_coverage_threshold <= 1:
        raise ValueError("low_coverage_threshold must be between zero and one")

    indexes: set[int] = set()
    for candidate in candidates:
        if candidate.candidate_index < 0:
            raise ValueError("candidate_index must be zero or greater")
        if candidate.candidate_index in indexes:
            raise ValueError("candidate indexes must be unique")
        indexes.add(candidate.candidate_index)
        _require_finite_positive(candidate.distance_m, "distance_m")
        _require_finite_positive(candidate.duration_seconds, "duration_seconds")
        _require_finite_nonnegative(
            candidate.matched_route_length_m, "matched_route_length_m"
        )
        if candidate.matched_route_length_m > candidate.distance_m:
            raise ValueError("matched_route_length_m cannot exceed distance_m")
        _require_finite_nonnegative(candidate.accident_score, "accident_score")
        _require_finite_nonnegative(
            candidate.historical_accident_density_per_km,
            "historical_accident_density_per_km",
        )
        if not math.isfinite(candidate.coverage) or not 0 <= candidate.coverage <= 1:
            raise ValueError("coverage must be between zero and one")


def _require_finite_positive(value: float, field_name: str) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{field_name} must be finite and greater than zero")


def _require_finite_nonnegative(value: float, field_name: str) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{field_name} must be finite and zero or greater")
