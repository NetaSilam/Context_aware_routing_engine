from __future__ import annotations

import json
import os
import platform
import statistics
import time
from pathlib import Path
from typing import Any

import psycopg

from app.corridor_matcher import (
    SAMPLED_NEAREST_MATCH_SQL,
)
from app.initialize_foundation import synchronous_database_url


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    position = max(0, min(len(ordered) - 1, int(len(ordered) * percentile + 0.999) - 1))
    return ordered[position]


def _execute_bounded(
    connection: Any,
    query: str,
    parameters: tuple[Any, ...],
    statement_timeout_ms: int,
) -> list[Any]:
    with connection.transaction():
        connection.execute(f"SET LOCAL statement_timeout = {statement_timeout_ms}")
        # PostgreSQL's LLVM startup cost dominates this bounded spatial query;
        # the runtime Compose database uses the same setting.
        connection.execute("SET LOCAL jit = off")
        return connection.execute(query, parameters).fetchall()


def _measure(
    connection: Any,
    query: str,
    parameters: tuple[Any, ...],
    repeats: int,
    statement_timeout_ms: int,
) -> dict[str, float]:
    _execute_bounded(connection, query, parameters, statement_timeout_ms)
    timings: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        _execute_bounded(connection, query, parameters, statement_timeout_ms)
        timings.append((time.perf_counter() - started) * 1000)
    return {
        "warm_p50_ms": statistics.median(timings),
        "warm_p95_ms": _percentile(timings, 0.95),
    }


def _geojson_linestring_wkt(geometry: dict[str, Any], shift_degrees: float = 0) -> str:
    if geometry.get("type") != "LineString" or len(geometry.get("coordinates", [])) < 2:
        raise ValueError("benchmark corpus requires GeoJSON LineStrings")
    coordinates = ", ".join(
        f"{longitude + shift_degrees} {latitude + shift_degrees}"
        for longitude, latitude in geometry["coordinates"]
    )
    return f"LINESTRING ({coordinates})"


def _results(
    connection: Any,
    query: str,
    parameters: tuple[Any, ...],
    statement_timeout_ms: int,
) -> list[dict[str, float]]:
    return [
        {
            "candidate_index": row[0],
            "route_distance_m": row[1],
            "matched_route_length_m": row[2],
            "accident_score": row[3],
            "coverage": row[2] / row[1],
        }
        for row in _execute_bounded(connection, query, parameters, statement_timeout_ms)
    ]


def main() -> None:
    corpus_path = Path(os.environ["MATCHER_CORPUS_PATH"])
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    interval = float(os.environ.get("MATCHER_SAMPLE_INTERVAL_M", "100"))
    tolerance = float(os.environ.get("MATCHER_TOLERANCE_M", "30"))
    repeats = int(os.environ.get("MATCHER_BENCHMARK_REPEATS", "30"))
    statement_timeout_ms = int(os.environ.get("MATCHER_STATEMENT_TIMEOUT_MS", "10000"))
    if not 50 <= interval <= 100:
        raise ValueError("MATCHER_SAMPLE_INTERVAL_M must be between 50 and 100")
    if tolerance <= 0:
        raise ValueError("MATCHER_TOLERANCE_M must be greater than zero")
    if repeats <= 0:
        raise ValueError("MATCHER_BENCHMARK_REPEATS must be greater than zero")
    if statement_timeout_ms <= 0:
        raise ValueError("MATCHER_STATEMENT_TIMEOUT_MS must be greater than zero")
    selected_cases = {
        value.strip()
        for value in os.environ.get("MATCHER_CASES", "").split(",")
        if value.strip()
    }
    case_reports = []
    with psycopg.connect(synchronous_database_url(os.environ["DATABASE_URL"])) as connection:
        for case in corpus["cases"]:
            if selected_cases and case["name"] not in selected_cases:
                continue
            if len(case["candidates"]) != 3:
                raise ValueError(f'case {case["name"]!r} must contain exactly three candidates')
            candidates = [
                {
                    "candidate_index": candidate["candidate_index"],
                    "geometry_wkt": _geojson_linestring_wkt(candidate["geometry"]),
                    "distance_m": candidate["distance_m"],
                    "source_srid": 4326,
                }
                for candidate in case["candidates"]
            ]
            if [candidate["candidate_index"] for candidate in candidates] != [0, 1, 2]:
                raise ValueError(
                    f'case {case["name"]!r} must use candidate indexes 0, 1, and 2'
                )
            shifted_candidates = [
                {
                    **candidate,
                    # Roughly two metres in both axes in Israel. This is deliberately
                    # small enough to test matcher stability rather than route choice.
                    "geometry_wkt": _geojson_linestring_wkt(
                        source["geometry"], shift_degrees=0.000018
                    ),
                }
                for candidate, source in zip(candidates, case["candidates"], strict=True)
            ]
            payload = json.dumps(candidates)
            shifted_payload = json.dumps(shifted_candidates)
            sampled_parameters = (
                payload, interval, tolerance, tolerance, tolerance, tolerance
            )
            case_report: dict[str, Any] = {"name": case["name"]}
            case_report["sampled_nearest"] = {
                **_measure(
                    connection, SAMPLED_NEAREST_MATCH_SQL, sampled_parameters,
                    repeats, statement_timeout_ms,
                ),
                "results": _results(
                    connection, SAMPLED_NEAREST_MATCH_SQL, sampled_parameters,
                    statement_timeout_ms,
                ),
                "shifted_results": _results(
                    connection, SAMPLED_NEAREST_MATCH_SQL,
                    (
                        shifted_payload, interval, tolerance, tolerance,
                        tolerance, tolerance,
                    ),
                    statement_timeout_ms,
                ),
            }
            case_reports.append(case_report)
    print(json.dumps({
        "machine": {"platform": platform.platform(), "processor": platform.processor()},
        "candidate_count_per_measurement": 3, "repeats": repeats,
        "sample_interval_m": interval, "tolerance_m": tolerance,
        "cases": case_reports,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
