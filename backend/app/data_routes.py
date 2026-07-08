from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.db import get_engine

router = APIRouter()


def _parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    parts = bbox.split(",")
    if len(parts) != 4:
        raise HTTPException(
            status_code=400, detail="bbox must be 'min_lon,min_lat,max_lon,max_lat'"
        )
    try:
        min_lon, min_lat, max_lon, max_lat = (float(v) for v in parts)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="bbox must be 'min_lon,min_lat,max_lon,max_lat'"
        ) from exc
    return min_lon, min_lat, max_lon, max_lat


@router.get("/api/canonical-network/corridors")
def list_corridors(
    bbox: str = Query(..., description="min_lon,min_lat,max_lon,max_lat (WGS84)"),
    limit: int = Query(200, gt=0, le=2000),
) -> dict[str, Any]:
    """Real corridor data ported from the foundation project. Adapted from the
    original query: joins against `canonical_corridor_display` (simplified display
    geometry) and `canonical_roads` aren't possible because that data isn't in this
    export (see PROJECT_REQUIREMENTS.md §0.1) - this returns the full analysis
    geometry directly from `canonical_corridors` instead.
    """
    min_lon, min_lat, max_lon, max_lat = _parse_bbox(bbox)
    sql = text(
        """
        SELECT
            corridor_id,
            corridor_family,
            road_id,
            primary_ref,
            primary_name,
            length_m,
            build_basis,
            ST_AsGeoJSON(ST_Transform(geometry, 4326)) AS geometry_geojson
        FROM canonical_network.canonical_corridors
        WHERE ST_Intersects(
            geometry,
            ST_Transform(ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326), 2039)
        )
        ORDER BY corridor_id
        LIMIT :limit
        """
    )
    with get_engine().begin() as conn:
        rows = (
            conn.execute(
                sql,
                {
                    "min_lon": min_lon,
                    "min_lat": min_lat,
                    "max_lon": max_lon,
                    "max_lat": max_lat,
                    "limit": limit,
                },
            )
            .mappings()
            .all()
        )
    return {
        "count": len(rows),
        "corridors": [
            {
                "corridor_id": row["corridor_id"],
                "corridor_family": row["corridor_family"],
                "road_id": row["road_id"],
                "primary_ref": row["primary_ref"],
                "primary_name": row["primary_name"],
                "length_m": row["length_m"],
                "build_basis": row["build_basis"],
                "geometry": json.loads(row["geometry_geojson"]),
            }
            for row in rows
        ],
    }


@router.get("/api/canonical-network/corridors/{corridor_id}")
def get_corridor(corridor_id: str) -> dict[str, Any]:
    sql = text(
        """
        SELECT
            corridor_id, corridor_family, road_id, primary_ref, primary_name,
            length_m, atom_count, build_basis, split_from_reason,
            ST_AsGeoJSON(ST_Transform(geometry, 4326)) AS geometry_geojson
        FROM canonical_network.canonical_corridors
        WHERE corridor_id = :corridor_id
        """
    )
    links_sql = text(
        """
        SELECT official_segment_id, segment_key, road_number, link_method, link_strength,
               source_match_confidence, distance_m, is_multi_target
        FROM canonical_network.official_segment_links
        WHERE target_object_type = 'corridor' AND target_object_id = :corridor_id
        ORDER BY official_segment_id
        """
    )
    with get_engine().begin() as conn:
        row = conn.execute(sql, {"corridor_id": corridor_id}).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown corridor_id '{corridor_id}'.")
        links = conn.execute(links_sql, {"corridor_id": corridor_id}).mappings().all()

    result = dict(row)
    result["geometry"] = json.loads(result.pop("geometry_geojson"))
    result["official_segment_links"] = [dict(link) for link in links]
    return result


@router.get("/api/accident-attribution/accidents")
def list_accidents(
    bbox: str = Query(..., description="min_lon,min_lat,max_lon,max_lat (WGS84)"),
    limit: int = Query(200, gt=0, le=2000),
) -> dict[str, Any]:
    min_lon, min_lat, max_lon, max_lat = _parse_bbox(bbox)
    sql = text(
        """
        SELECT
            accident_id, accident_year, severity, road_number, corridor_id,
            corridor_primary_name, attribution_status, confidence_tier,
            distance_to_corridor_m,
            ST_AsGeoJSON(geometry) AS geometry_geojson
        FROM accident_attribution.accident_attributions
        WHERE ST_Intersects(
            geometry,
            ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)
        )
        ORDER BY accident_id
        LIMIT :limit
        """
    )
    with get_engine().begin() as conn:
        rows = (
            conn.execute(
                sql,
                {
                    "min_lon": min_lon,
                    "min_lat": min_lat,
                    "max_lon": max_lon,
                    "max_lat": max_lat,
                    "limit": limit,
                },
            )
            .mappings()
            .all()
        )
    return {
        "count": len(rows),
        "accidents": [
            {
                "accident_id": row["accident_id"],
                "accident_year": row["accident_year"],
                "severity": row["severity"],
                "road_number": row["road_number"],
                "corridor_id": row["corridor_id"],
                "corridor_primary_name": row["corridor_primary_name"],
                "attribution_status": row["attribution_status"],
                "confidence_tier": row["confidence_tier"],
                "distance_to_corridor_m": row["distance_to_corridor_m"],
                "geometry": json.loads(row["geometry_geojson"]),
            }
            for row in rows
        ],
    }


@router.get("/api/accident-attribution/summary")
def accident_attribution_summary() -> dict[str, Any]:
    sql = text("SELECT * FROM accident_attribution.accident_attribution_summary LIMIT 1")
    with get_engine().begin() as conn:
        row = conn.execute(sql).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Accident attribution summary table is empty.")

    result = dict(row)
    for key in (
        "status_breakdown",
        "confidence_breakdown",
        "unresolved_reason_breakdown",
        "official_reference_effect_breakdown",
    ):
        if isinstance(result.get(key), str):
            result[key] = json.loads(result[key])
    return result
