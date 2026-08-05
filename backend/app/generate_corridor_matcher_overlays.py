from __future__ import annotations

import html
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable

import psycopg

from app.benchmark_corridor_matchers import _geojson_linestring_wkt
from app.initialize_foundation import synchronous_database_url


NEARBY_CORRIDORS_SQL = """
WITH input_routes AS MATERIALIZED (
    SELECT ST_Transform(ST_GeomFromText(geometry_wkt, 4326), 2039) AS geometry
    FROM jsonb_to_recordset(%s::jsonb) AS route(geometry_wkt text)
), route_chunks AS MATERIALIZED (
    SELECT ST_LineSubstring(
        route.geometry,
        chunk_number / chunk_count::double precision,
        (chunk_number + 1) / chunk_count::double precision
    ) AS geometry
    FROM input_routes route
    CROSS JOIN LATERAL (
        SELECT GREATEST(1, CEIL(ST_Length(route.geometry) / 1000)::integer) AS chunk_count
    ) chunk_total
    CROSS JOIN LATERAL generate_series(0, chunk_count - 1) AS chunk_number
)
SELECT DISTINCT risk.corridor_id,
       ST_AsGeoJSON(ST_Transform(risk.geometry, 4326))::jsonb
FROM route_chunks chunk
CROSS JOIN app.active_risk_data_version active
JOIN app.corridor_risk_statistics risk
  ON risk.risk_data_version = active.version
 AND risk.geometry && ST_Expand(chunk.geometry, %s)
 AND ST_DWithin(risk.geometry, chunk.geometry, %s)
ORDER BY risk.corridor_id
"""

COLORS = ("#0072b2", "#d55e00", "#009e73")


def _lines(geometry: dict[str, Any]) -> Iterable[list[list[float]]]:
    if geometry["type"] == "LineString":
        yield geometry["coordinates"]
    elif geometry["type"] == "MultiLineString":
        yield from geometry["coordinates"]
    else:
        raise ValueError(f"unsupported overlay geometry: {geometry['type']}")


def _svg(case: dict[str, Any], corridors: list[tuple[str, dict[str, Any]]]) -> str:
    route_lines = [candidate["geometry"]["coordinates"] for candidate in case["candidates"]]
    corridor_lines = [line for _, geometry in corridors for line in _lines(geometry)]
    coordinates = [point for line in route_lines + corridor_lines for point in line]
    latitude_midpoint = sum(point[1] for point in coordinates) / len(coordinates)
    longitude_scale = math.cos(math.radians(latitude_midpoint))
    projected = [(point[0] * longitude_scale, point[1]) for point in coordinates]
    min_x = min(point[0] for point in projected)
    max_x = max(point[0] for point in projected)
    min_y = min(point[1] for point in projected)
    max_y = max(point[1] for point in projected)
    width, height, padding = 1000, 650, 35
    scale = min(
        (width - 2 * padding) / max(max_x - min_x, 1e-12),
        (height - 2 * padding) / max(max_y - min_y, 1e-12),
    )

    def points(line: list[list[float]]) -> str:
        return " ".join(
            f"{padding + (longitude * longitude_scale - min_x) * scale:.2f},"
            f"{height - padding - (latitude - min_y) * scale:.2f}"
            for longitude, latitude in line
        )

    content = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 650" '
        'role="img" aria-labelledby="title description">',
        f'<title id="title">{html.escape(case["name"])} corridor matcher overlay</title>',
        '<desc id="description">Three fixed OSRM candidates over nearby canonical risk '
        'corridors accepted by the 30 metre matcher tolerance.</desc>',
        '<rect width="1000" height="650" fill="#ffffff"/>',
    ]
    for line in corridor_lines:
        content.append(
            f'<polyline points="{points(line)}" fill="none" stroke="#8a8a8a" '
            'stroke-width="1.2" stroke-opacity="0.58"/>'
        )
    for index, line in enumerate(route_lines):
        content.append(
            f'<polyline points="{points(line)}" fill="none" stroke="{COLORS[index]}" '
            'stroke-width="3.2" stroke-opacity="0.85"/>'
        )
    content.extend(
        [
            '<rect x="15" y="15" width="260" height="103" rx="5" '
            'fill="#ffffff" fill-opacity="0.9" stroke="#cccccc"/>',
            f'<text x="28" y="40" font-family="sans-serif" font-size="16" '
            f'font-weight="bold">{html.escape(case["name"])} — {len(corridors)} corridors</text>',
            '<line x1="28" y1="59" x2="60" y2="59" stroke="#8a8a8a" stroke-width="2"/>',
            '<text x="70" y="64" font-family="sans-serif" font-size="14">accepted corridor</text>',
        ]
    )
    for index, color in enumerate(COLORS):
        y = 80 + index * 17
        content.append(f'<line x1="28" y1="{y}" x2="60" y2="{y}" stroke="{color}" stroke-width="3"/>')
        content.append(
            f'<text x="70" y="{y + 5}" font-family="sans-serif" font-size="14">'
            f'OSRM candidate {index}</text>'
        )
    content.append("</svg>")
    return "\n".join(content) + "\n"


def main() -> None:
    corpus = json.loads(Path(os.environ["MATCHER_CORPUS_PATH"]).read_text(encoding="utf-8"))
    output_directory = Path(os.environ["MATCHER_OVERLAY_DIRECTORY"])
    output_directory.mkdir(parents=True, exist_ok=True)
    tolerance_m = float(os.environ.get("MATCHER_TOLERANCE_M", "30"))
    with psycopg.connect(synchronous_database_url(os.environ["DATABASE_URL"])) as connection:
        connection.execute("SET jit = off")
        connection.execute("SET statement_timeout = '10s'")
        for case in corpus["cases"]:
            payload = json.dumps(
                [
                    {"geometry_wkt": _geojson_linestring_wkt(candidate["geometry"])}
                    for candidate in case["candidates"]
                ]
            )
            corridors = [
                (row[0], row[1])
                for row in connection.execute(
                    NEARBY_CORRIDORS_SQL, (payload, tolerance_m, tolerance_m)
                ).fetchall()
            ]
            output_path = output_directory / f'{case["name"]}.svg'
            output_path.write_text(_svg(case, corridors), encoding="utf-8")
            print(f"{output_path}: {len(corridors)} corridors")


if __name__ == "__main__":
    main()
