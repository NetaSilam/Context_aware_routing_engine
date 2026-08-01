from __future__ import annotations

import os

import psycopg
import pytest

from app.corridor_matcher import RouteCandidateGeometry, match_route_candidates

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_CORRIDOR_MATCHER_INTEGRATION") != "true",
        reason="requires the disposable Compose PostGIS stack",
    ),
]

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SYNC_DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")

MATCHER_FIXTURE_SQL = """
DELETE FROM app.corridor_risk_statistics
WHERE risk_data_version = (SELECT version FROM app.active_risk_data_version);

INSERT INTO app.corridor_risk_statistics (
    risk_data_version, corridor_id, corridor_family, geometry,
    corridor_length_m, raw_accident_count
)
SELECT active.version, fixture.corridor_id, 'fixture',
       ST_GeomFromText(fixture.geometry_wkt, 2039),
       fixture.corridor_length_m, fixture.raw_accident_count
FROM app.active_risk_data_version active
CROSS JOIN (VALUES
    ('main', 'LINESTRING(100000 600000, 101000 600000)', 1000.0, 10),
    ('parallel', 'LINESTRING(100000 600020, 101000 600020)', 1000.0, 100),
    ('cross', 'LINESTRING(100500 599500, 100500 600500)', 1000.0, 5),
    ('long', 'LINESTRING(100000 600300, 110000 600300)', 10000.0, 100)
) AS fixture(corridor_id, geometry_wkt, corridor_length_m, raw_accident_count);
"""


def route(index: int, wkt: str, distance_m: float) -> RouteCandidateGeometry:
    return RouteCandidateGeometry(index, wkt, distance_m, source_srid=2039)


def test_sampled_matcher_scores_all_candidates_once_with_bounded_coverage() -> None:
    candidates = [
        route(0, "LINESTRING(100000 600000, 101000 600000)", 1000),
        route(1, "LINESTRING(100250 600000, 100750 600000)", 500),
        route(2, "LINESTRING(99750 600000, 101250 600000)", 1500),
        route(3, "LINESTRING(100000 600010, 101000 600010)", 1000),
        route(4, "LINESTRING(100500 599500, 100500 600500)", 1000),
        route(5, "LINESTRING(100000 600700, 101000 600700)", 1000),
        route(6, "LINESTRING(100000 600300, 101000 600300)", 1000),
    ]
    with psycopg.connect(SYNC_DATABASE_URL) as connection:
        with connection.transaction(force_rollback=True):
            connection.execute(MATCHER_FIXTURE_SQL)
            matches = match_route_candidates(
                connection,
                candidates,
                sample_interval_m=50,
                tolerance_m=30,
                low_coverage_threshold=0.80,
            )

    assert [match.candidate_index for match in matches] == list(range(7))
    full, partial, gaps, parallel, intersection, no_match, long_use = matches

    assert full.matched_route_length_m == pytest.approx(1000)
    assert full.accident_score == pytest.approx(10)
    assert full.historical_accident_density_per_km == pytest.approx(10)
    assert full.coverage == pytest.approx(1)
    assert not full.low_coverage

    assert partial.matched_route_length_m == pytest.approx(500)
    assert partial.accident_score == pytest.approx(5)
    assert partial.coverage == pytest.approx(1)

    # Midpoints within the 30 m accepted tolerance represent 1,100 of 1,500 m.
    assert gaps.matched_route_length_m == pytest.approx(1100)
    assert gaps.coverage == pytest.approx(11 / 15)
    assert gaps.low_coverage

    # The route is equidistant from two divided-road corridors. Stable corridor-id
    # tie-breaking assigns every position to `main`; risk is never double counted.
    assert parallel.matched_route_length_m == pytest.approx(1000)
    assert parallel.accident_score == pytest.approx(10)
    assert parallel.accident_score != pytest.approx(110)

    assert intersection.matched_route_length_m == pytest.approx(1000)
    assert intersection.accident_score == pytest.approx(5)
    assert no_match.matched_route_length_m == 0
    assert no_match.accident_score == 0
    assert no_match.coverage == 0
    assert no_match.low_coverage

    # Average-density prorating uses only 1/10 of the long corridor's accidents.
    assert long_use.accident_score == pytest.approx(10)
    assert long_use.historical_accident_density_per_km == pytest.approx(10)

    assert all(0 <= match.coverage <= 1 for match in matches)
    assert all(match.matched_route_length_m <= match.route_distance_m for match in matches)


def test_sampled_matcher_is_stable_after_small_route_shift() -> None:
    with psycopg.connect(SYNC_DATABASE_URL) as connection:
        with connection.transaction(force_rollback=True):
            connection.execute(MATCHER_FIXTURE_SQL)
            original, shifted = match_route_candidates(
                connection,
                [
                    route(0, "LINESTRING(100000 600000, 101000 600000)", 1000),
                    route(1, "LINESTRING(100000 600002, 101000 600002)", 1000),
                ],
                sample_interval_m=75,
                tolerance_m=30,
            )

    assert shifted.matched_route_length_m == pytest.approx(original.matched_route_length_m)
    assert shifted.accident_score == pytest.approx(original.accident_score)
    assert shifted.coverage == pytest.approx(original.coverage)


@pytest.mark.parametrize(
    "candidates,kwargs,error",
    [
        ([route(0, "LINESTRING(0 0, 1 1)", 0)], {}, "distance"),
        ([route(0, "LINESTRING(0 0, 1 1)", 10), route(0, "LINESTRING(0 0, 1 1)", 10)], {}, "unique"),
        ([route(0, "LINESTRING(0 0, 1 1)", 10)], {"sample_interval_m": 49}, "between 50 and 100"),
    ],
)
def test_matcher_rejects_invalid_inputs(candidates, kwargs, error) -> None:
    with psycopg.connect(SYNC_DATABASE_URL) as connection:
        with pytest.raises(ValueError, match=error):
            match_route_candidates(connection, candidates, **kwargs)
