from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.db import get_engine

router = APIRouter()

DEFAULT_LIMIT = 200
MAX_LIMIT = 2000


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


def _corridor_build_description(row: dict[str, Any]) -> str:
    # Synthesized rather than ported: the original repo's build_description came from
    # canonical_roads, which isn't in this data export (see PROJECT_REQUIREMENTS.md §0.1).
    label = row["primary_name"] or row["primary_ref"] or row["corridor_id"]
    return (
        f"{label} is a {row['corridor_family'].replace('_', ' ')} built from "
        f"{row['atom_count']} atom(s) on the basis of '{row['build_basis']}' "
        f"(split reason: {row['split_from_reason']})."
    )


@router.get("/api/canonical-network/corridors")
def list_corridors(
    bbox: str = Query(..., description="min_lon,min_lat,max_lon,max_lat (WGS84)"),
    limit: int = Query(DEFAULT_LIMIT, gt=0, le=MAX_LIMIT),
) -> dict[str, Any]:
    """Real corridor data ported from the foundation project. Adapted from the
    original query: joining against `canonical_corridor_display` (simplified display
    geometry) and `canonical_roads` isn't possible because that data isn't in this
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
        LIMIT :query_limit
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
                    "query_limit": limit + 1,
                },
            )
            .mappings()
            .all()
        )

    truncated = len(rows) > limit
    rows = rows[:limit]
    return {
        "bbox": {
            "min_lon": min_lon,
            "min_lat": min_lat,
            "max_lon": max_lon,
            "max_lat": max_lat,
        },
        "max_results": limit,
        "returned_count": len(rows),
        "truncated": truncated,
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
        links = [dict(link) for link in conn.execute(links_sql, {"corridor_id": corridor_id}).mappings().all()]

    result = dict(row)
    result["geometry"] = json.loads(result.pop("geometry_geojson"))
    result["build_description"] = _corridor_build_description(result)
    # Not available in this data export (no canonical_roads table) - see PROJECT_REQUIREMENTS.md §0.1.
    result["road"] = None
    result["official_link_summary"] = (
        None
        if not links
        else {
            "official_segment_count": len(links),
            "link_method_breakdown": _count_by(links, "link_method"),
            "link_strength_breakdown": _count_by(links, "link_strength"),
            "links": links,
        }
    )
    return result


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(key) or "unknown"
        counts[value] = counts.get(value, 0) + 1
    return counts


@router.get("/api/accident-attribution/accidents")
def list_accidents(
    bbox: str = Query(..., description="min_lon,min_lat,max_lon,max_lat (WGS84)"),
    limit: int = Query(DEFAULT_LIMIT, gt=0, le=MAX_LIMIT),
    status: str | None = Query(None, description="Filter by attribution_status"),
    confidence: str | None = Query(None, description="Filter by confidence_tier"),
    year: int | None = Query(None, description="Filter by accident_year"),
) -> dict[str, Any]:
    min_lon, min_lat, max_lon, max_lat = _parse_bbox(bbox)
    conditions = [
        "ST_Intersects(geometry, ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326))"
    ]
    params: dict[str, Any] = {
        "min_lon": min_lon,
        "min_lat": min_lat,
        "max_lon": max_lon,
        "max_lat": max_lat,
        "query_limit": limit + 1,
    }
    if status is not None:
        conditions.append("attribution_status = :status")
        params["status"] = status
    if confidence is not None:
        conditions.append("confidence_tier = :confidence")
        params["confidence"] = confidence
    if year is not None:
        conditions.append("accident_year = :year")
        params["year"] = year

    sql = text(
        f"""
        SELECT
            accident_id, accident_year, severity, road_number, corridor_id, road_id,
            corridor_primary_name AS corridor_label,
            attribution_status, confidence_tier, confidence_reason_code,
            ST_AsGeoJSON(geometry) AS geometry_geojson
        FROM accident_attribution.accident_attributions
        WHERE {" AND ".join(conditions)}
        ORDER BY accident_id
        LIMIT :query_limit
        """
    )
    with get_engine().begin() as conn:
        rows = conn.execute(sql, params).mappings().all()

    truncated = len(rows) > limit
    rows = rows[:limit]
    return {
        "bbox": {
            "min_lon": min_lon,
            "min_lat": min_lat,
            "max_lon": max_lon,
            "max_lat": max_lat,
        },
        "max_results": limit,
        "returned_count": len(rows),
        "truncated": truncated,
        "accidents": [
            {
                "accident_id": row["accident_id"],
                "accident_year": row["accident_year"],
                "severity": row["severity"],
                "road_number": row["road_number"],
                "corridor_id": row["corridor_id"],
                "road_id": row["road_id"],
                "corridor_label": row["corridor_label"],
                "attribution_status": row["attribution_status"],
                "confidence_tier": row["confidence_tier"],
                "confidence_reason_code": row["confidence_reason_code"],
                "geometry": json.loads(row["geometry_geojson"]),
            }
            for row in rows
        ],
    }


@router.get("/api/accident-attribution/accidents/{accident_id}")
def get_accident(accident_id: str) -> dict[str, Any]:
    sql = text(
        """
        SELECT
            accident_id, accident_year, severity, road_number, locality_code,
            geographic_domain, corridor_id, corridor_family, road_id,
            corridor_primary_ref, corridor_primary_name, attribution_status,
            confidence_tier, assignment_method, unresolved_reason,
            confidence_reason_code, review_needed, distance_to_corridor_m,
            second_best_distance_m, official_reference_effect, diagnostics_json,
            attribution_version,
            ST_AsGeoJSON(geometry) AS geometry_geojson
        FROM accident_attribution.accident_attributions
        WHERE accident_id = :accident_id
        """
    )
    with get_engine().begin() as conn:
        row = conn.execute(sql, {"accident_id": accident_id}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown accident_id '{accident_id}'.")

    diagnostics = None
    if row["diagnostics_json"]:
        try:
            diagnostics = json.loads(row["diagnostics_json"])
        except (TypeError, ValueError):
            diagnostics = None

    explanation_snippets: list[str] = [
        f"Confidence tier: {row['confidence_tier']} ({row['confidence_reason_code'] or 'no reason code'})."
    ]
    if row["distance_to_corridor_m"] is not None:
        explanation_snippets.append(
            f"Matched corridor is {row['distance_to_corridor_m']:.1f}m from the accident point."
        )
    if row["official_reference_effect"] not in (None, "not_available"):
        explanation_snippets.append(
            f"Official road-number reference effect: {row['official_reference_effect']}."
        )

    return {
        "accident": {
            "accident_id": row["accident_id"],
            "accident_year": row["accident_year"],
            "severity": row["severity"],
            "road_number": row["road_number"],
            "locality_code": row["locality_code"],
            "geographic_domain": row["geographic_domain"],
            "geometry": json.loads(row["geometry_geojson"]) if row["geometry_geojson"] else None,
        },
        "attribution": {
            "corridor_id": row["corridor_id"],
            "corridor_family": row["corridor_family"],
            "road_id": row["road_id"],
            "corridor_primary_ref": row["corridor_primary_ref"],
            "corridor_primary_name": row["corridor_primary_name"],
            "attribution_status": row["attribution_status"],
            "confidence_tier": row["confidence_tier"],
            "assignment_method": row["assignment_method"],
            "unresolved_reason": row["unresolved_reason"],
            "confidence_reason_code": row["confidence_reason_code"],
            "review_needed": row["review_needed"],
            "distance_to_corridor_m": row["distance_to_corridor_m"],
            "second_best_distance_m": row["second_best_distance_m"],
            "official_reference_effect": row["official_reference_effect"],
            "attribution_version": row["attribution_version"],
        },
        "diagnostics": diagnostics,
        "explanation_snippets": explanation_snippets,
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
