from __future__ import annotations

import math

import pytest

from app.config import Settings
from app.geocoding.geocoder_client import GeocoderError, parse_provider_results
from app.geocoding.router import normalize_query


def settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://user:password@postgres:5432/test",
        redis_url="redis://redis:6379/0",
        foundation_data_version="fixture-v1",
        jwt_secret="test-secret-with-at-least-32-characters",
        auth_allowed_origin="http://localhost:5173",
        osrm_base_url="http://osrm:5000/",
        expected_osrm_graph_version="graph-v1",
        geocoder_base_url="http://geocoder:5001/search",
        geocoder_user_agent="road-risk-tests/1.0",
    )


def test_query_normalization_collapses_whitespace_and_case() -> None:
    assert normalize_query("  TEL   Aviv\tCentral ") == "tel aviv central"


def test_provider_results_are_region_filtered_and_labels_are_bounded() -> None:
    matches = parse_provider_results(
        [
            {"display_name": "  Tel   Aviv  ", "lon": "34.78", "lat": "32.07"},
            {"display_name": "Outside", "lon": "10", "lat": "10"},
            {"display_name": "x" * 250, "lon": "34.79", "lat": "32.08"},
        ],
        settings(),
    )
    assert [(match.label, match.longitude, match.latitude) for match in matches] == [
        ("Tel Aviv", 34.78, 32.07),
        ("x" * 200, 34.79, 32.08),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"not": "a list"},
        [{"display_name": "Missing coordinates"}],
        [{"display_name": "Bad", "lon": math.inf, "lat": 32.0}],
    ],
)
def test_malformed_provider_data_is_a_controlled_failure(payload: object) -> None:
    with pytest.raises(GeocoderError, match="invalid response"):
        parse_provider_results(payload, settings())
