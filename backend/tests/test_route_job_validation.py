from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from app.routing.route_jobs import RouteJobCreate


def valid_request(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "origin_longitude": 34.78,
        "origin_latitude": 32.07,
        "destination_longitude": 34.79,
        "destination_latitude": 32.08,
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    "overrides",
    [
        {"origin_longitude": math.nan},
        {"destination_latitude": math.inf},
        {"origin_longitude": "not-a-coordinate"},
        {"origin_longitude": "34.78"},
        {"unexpected": True},
        {"origin_label": "x" * 201},
        {
            "destination_longitude": 34.78,
            "destination_latitude": 32.07,
        },
    ],
)
def test_route_job_request_rejects_malformed_input(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RouteJobCreate.model_validate(valid_request(**overrides))


def test_route_job_request_accepts_bounded_optional_labels() -> None:
    request = RouteJobCreate.model_validate(
        valid_request(origin_label="North station", destination_label="South station")
    )
    assert request.origin_label == "North station"
    assert request.destination_label == "South station"
