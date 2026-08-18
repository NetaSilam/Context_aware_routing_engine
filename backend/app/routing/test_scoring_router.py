from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.routing.route_scoring_service import (
    CandidateRouteMeasurement,
    UserScoringContext,
    score_route_candidates,
)

router = APIRouter(prefix="/api/testing", tags=["testing"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CandidateMeasurementRequest(StrictModel):
    candidate_index: int = Field(ge=0)
    distance_m: float = Field(gt=0, allow_inf_nan=False)
    duration_seconds: float = Field(gt=0, allow_inf_nan=False)
    matched_route_length_m: float = Field(ge=0, allow_inf_nan=False)
    accident_score: float = Field(ge=0, allow_inf_nan=False)
    historical_accident_density_per_km: float = Field(ge=0, allow_inf_nan=False)
    coverage: float = Field(ge=0, le=1, allow_inf_nan=False)


class UserScoringContextRequest(StrictModel):
    driving_experience: Literal["novice", "experienced"]
    vehicle_type: Literal["car", "motorcycle", "truck"]
    submitted_at: datetime
    safety_preference: Literal["low", "balanced", "high"] = "balanced"

    @field_validator("submitted_at")
    @classmethod
    def require_offset(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("submitted_at must include a UTC offset")
        return value


class ScoreCandidatesRequest(StrictModel):
    candidates: list[CandidateMeasurementRequest] = Field(min_length=1, max_length=3)
    context: UserScoringContextRequest
    reference_risk_p95: float = Field(gt=0, allow_inf_nan=False)
    risk_data_version: str = Field(min_length=1, max_length=100)
    low_coverage_threshold: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_candidate_relationships(self) -> "ScoreCandidatesRequest":
        indexes = [candidate.candidate_index for candidate in self.candidates]
        if len(indexes) != len(set(indexes)):
            raise ValueError("candidate indexes must be unique")
        if any(
            candidate.matched_route_length_m > candidate.distance_m
            for candidate in self.candidates
        ):
            raise ValueError("matched_route_length_m cannot exceed distance_m")
        return self


@router.post("/score-route-candidates")
def score_candidates(payload: ScoreCandidatesRequest) -> dict[str, object]:
    result = score_route_candidates(
        [
            CandidateRouteMeasurement(**candidate.model_dump())
            for candidate in payload.candidates
        ],
        UserScoringContext(**payload.context.model_dump()),
        reference_risk_p95=payload.reference_risk_p95,
        risk_data_version=payload.risk_data_version,
        low_coverage_threshold=payload.low_coverage_threshold,
    )
    return asdict(result)
