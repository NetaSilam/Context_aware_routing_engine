from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from app.routing.osrm_client import (
    OsrmLineString,
    OsrmResponse,
    OsrmRouteCandidate,
    supported_exclusions,
)


@pytest.mark.parametrize(
    ("avoid_highways", "avoid_tolls", "expected"),
    [
        (False, False, None),
        (True, False, "motorway"),
        (False, True, "toll"),
        (True, True, "motorway,toll"),
    ],
)
def test_stored_preferences_map_to_supported_osrm_exclusions(
    avoid_highways: bool, avoid_tolls: bool, expected: str | None
) -> None:
    assert (
        supported_exclusions(
            avoid_highways=avoid_highways, avoid_tolls=avoid_tolls
        )
        == expected
    )


def test_response_models_accept_valid_routes_and_ignore_unneeded_osrm_fields() -> None:
    response = OsrmResponse.model_validate(
        {
            "code": "Ok",
            "routes": [
                {
                    "distance": 1200,
                    "duration": 180,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[34.78, 32.08], [34.79, 32.09]],
                    },
                    "weight": 181,
                }
            ],
            "waypoints": [],
        }
    )

    assert len(response.routes or []) == 1


@pytest.mark.parametrize("field", ["distance", "duration"])
@pytest.mark.parametrize("value", [0, -1, math.inf, math.nan])
def test_route_candidate_rejects_non_positive_or_non_finite_measurements(
    field: str, value: float
) -> None:
    payload = {
        "distance": 1200,
        "duration": 180,
        "geometry": {
            "type": "LineString",
            "coordinates": [[34.78, 32.08], [34.79, 32.09]],
        },
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        OsrmRouteCandidate.model_validate(payload)


@pytest.mark.parametrize(
    "geometry",
    [
        {"type": "Polygon", "coordinates": [[34.78, 32.08], [34.79, 32.09]]},
        {"type": "LineString", "coordinates": [[34.78, 32.08]]},
        {"type": "LineString", "coordinates": [[34.78], [34.79, 32.09]]},
        {"type": "LineString", "coordinates": [[181, 32.08], [34.79, 32.09]]},
        {"type": "LineString", "coordinates": [[34.78, math.inf], [34.79, 32.09]]},
        {"type": "LineString", "coordinates": [["34.78", 32.08], [34.79, 32.09]]},
    ],
)
def test_linestring_rejects_invalid_geometry(geometry: object) -> None:
    with pytest.raises(ValidationError):
        OsrmLineString.model_validate(geometry)


def test_response_rejects_more_than_three_candidates() -> None:
    route = {
        "distance": 1200,
        "duration": 180,
        "geometry": {
            "type": "LineString",
            "coordinates": [[34.78, 32.08], [34.79, 32.09]],
        },
    }

    with pytest.raises(ValidationError):
        OsrmResponse.model_validate({"code": "Ok", "routes": [route] * 4})
