from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Protocol, Sequence


@dataclass(frozen=True)
class RouteCandidateGeometry:
    candidate_index: int
    geometry_wkt: str
    distance_m: float
    source_srid: int = 4326


@dataclass(frozen=True)
class CorridorMatch:
    candidate_index: int
    route_distance_m: float
    matched_route_length_m: float
    accident_score: float
    historical_accident_density_per_km: float
    coverage: float
    low_coverage: bool


class SqlConnection(Protocol):
    def execute(self, query: str, params: Sequence[Any]) -> Any: ...


SAMPLED_NEAREST_MATCH_SQL = """
WITH input_routes AS MATERIALIZED (
    SELECT
        candidate_index,
        distance_m,
        ST_Transform(ST_GeomFromText(geometry_wkt, source_srid), 2039) AS geometry
    FROM jsonb_to_recordset(%s::jsonb) AS candidate(
        candidate_index integer,
        geometry_wkt text,
        distance_m double precision,
        source_srid integer
    )
), route_parts AS MATERIALIZED (
    SELECT
        route.candidate_index,
        route.distance_m,
        route.geometry,
        part_number,
        FLOOR(part_number / 10.0)::integer AS chunk_number,
        sample_count,
        route.distance_m / sample_count AS represented_length_m,
        ST_LineInterpolatePoint(
            route.geometry,
            (part_number + 0.5) / sample_count
        ) AS sample_point
    FROM input_routes route
    CROSS JOIN LATERAL (
        SELECT GREATEST(1, CEIL(route.distance_m / %s)::integer) AS sample_count
    ) sample_total
    CROSS JOIN LATERAL generate_series(0, sample_count - 1) AS part_number
), route_chunks AS MATERIALIZED (
    SELECT DISTINCT ON (candidate_index, chunk_number)
        candidate_index,
        chunk_number,
        ST_LineSubstring(
            geometry,
            (chunk_number * 10.0) / sample_count,
            LEAST(1.0, ((chunk_number + 1) * 10.0) / sample_count)
        ) AS geometry
    FROM route_parts
    ORDER BY candidate_index, chunk_number
), nearby_corridors AS MATERIALIZED (
    SELECT chunk.candidate_index, chunk.chunk_number,
           risk.corridor_id, risk.corridor_length_m,
           risk.raw_accident_count, risk.geometry
    FROM route_chunks chunk
    CROSS JOIN app.active_risk_data_version active
    JOIN app.corridor_risk_statistics risk
      ON risk.risk_data_version = active.version
     AND risk.geometry && ST_Expand(chunk.geometry, %s)
     AND ST_DWithin(risk.geometry, chunk.geometry, %s)
), ranked_assignments AS (
    SELECT
        part.candidate_index,
        part.part_number,
        part.distance_m,
        part.represented_length_m,
        corridor.corridor_id,
        corridor.corridor_length_m,
        corridor.raw_accident_count,
        ROW_NUMBER() OVER (
            PARTITION BY part.candidate_index, part.part_number
            ORDER BY ST_Distance(corridor.geometry, part.sample_point), corridor.corridor_id
        ) AS match_rank
    FROM route_parts part
    LEFT JOIN nearby_corridors corridor
      ON corridor.candidate_index = part.candidate_index
     AND corridor.chunk_number = part.chunk_number
     AND corridor.geometry && ST_Expand(part.sample_point, %s)
     AND ST_DWithin(corridor.geometry, part.sample_point, %s)
), assignments AS (
    SELECT candidate_index, distance_m, represented_length_m,
           corridor_id, corridor_length_m, raw_accident_count
    FROM ranked_assignments
    WHERE match_rank = 1
), corridor_usage AS (
    SELECT
        candidate_index,
        corridor_id,
        corridor_length_m,
        raw_accident_count,
        SUM(represented_length_m) AS assigned_length_m
    FROM assignments
    WHERE corridor_id IS NOT NULL
    GROUP BY candidate_index, corridor_id, corridor_length_m, raw_accident_count
), candidate_totals AS (
    SELECT
        candidate_index,
        SUM(assigned_length_m) AS matched_route_length_m,
        SUM(
            raw_accident_count
            * LEAST(assigned_length_m, corridor_length_m)
            / corridor_length_m
        ) AS accident_score
    FROM corridor_usage
    GROUP BY candidate_index
)
SELECT
    route.candidate_index,
    route.distance_m AS route_distance_m,
    LEAST(route.distance_m, COALESCE(total.matched_route_length_m, 0))
        AS matched_route_length_m,
    COALESCE(total.accident_score, 0) AS accident_score
FROM input_routes route
LEFT JOIN candidate_totals total USING (candidate_index)
ORDER BY route.candidate_index
"""


def match_route_candidates(
    connection: SqlConnection,
    candidates: Sequence[RouteCandidateGeometry],
    *,
    sample_interval_m: float = 100.0,
    tolerance_m: float = 30.0,
    low_coverage_threshold: float = 0.80,
) -> list[CorridorMatch]:
    """Match every candidate in one indexed PostGIS statement.

    Each fixed-length route part is represented by one midpoint. Indexed route-
    chunk preselection assigns that position to at most one nearest corridor.
    Ties are resolved by the stable corridor identifier.
    """
    if not 50 <= sample_interval_m <= 100:
        raise ValueError("sample_interval_m must be between 50 and 100")
    if not math.isfinite(tolerance_m) or tolerance_m <= 0:
        raise ValueError("tolerance_m must be finite and greater than zero")
    if not 0 <= low_coverage_threshold <= 1:
        raise ValueError("low_coverage_threshold must be between zero and one")
    if not candidates:
        return []

    indexes: set[int] = set()
    payload: list[dict[str, object]] = []
    for candidate in candidates:
        if candidate.candidate_index in indexes:
            raise ValueError("candidate indexes must be unique")
        indexes.add(candidate.candidate_index)
        if not candidate.geometry_wkt.strip():
            raise ValueError("candidate geometry must not be empty")
        if not math.isfinite(candidate.distance_m) or candidate.distance_m <= 0:
            raise ValueError("candidate distance must be finite and greater than zero")
        if candidate.source_srid <= 0:
            raise ValueError("candidate source SRID must be greater than zero")
        payload.append(
            {
                "candidate_index": candidate.candidate_index,
                "geometry_wkt": candidate.geometry_wkt,
                "distance_m": candidate.distance_m,
                "source_srid": candidate.source_srid,
            }
        )

    rows = connection.execute(
        SAMPLED_NEAREST_MATCH_SQL,
        (
            json.dumps(payload), sample_interval_m,
            tolerance_m, tolerance_m, tolerance_m, tolerance_m,
        ),
    ).fetchall()
    results: list[CorridorMatch] = []
    for row in rows:
        candidate_index, route_distance_m, matched_length_m, accident_score = row
        coverage = min(1.0, max(0.0, matched_length_m / route_distance_m))
        density = accident_score / (matched_length_m / 1000.0) if matched_length_m else 0.0
        results.append(
            CorridorMatch(
                candidate_index=candidate_index,
                route_distance_m=route_distance_m,
                matched_route_length_m=matched_length_m,
                accident_score=accident_score,
                historical_accident_density_per_km=density,
                coverage=coverage,
                low_coverage=coverage < low_coverage_threshold,
            )
        )
    return results
