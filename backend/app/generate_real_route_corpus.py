from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OSRM_IMAGE = (
    "ghcr.io/project-osrm/osrm-backend:v6.0.0@"
    "sha256:729461bcc9ae9e6aafa92c0f93db9b060a32e85d5e72092c01ae4a4a9f1eb564"
)
GRAPH_DATA_VERSION = "israel-palestine-2026-07-31-osrm-6.0.0-profile-v1"
PBF_SOURCE = "https://download.geofabrik.de/asia/israel-and-palestine-260731.osm.pbf"
PBF_SHA256 = "e9b3db1a669140565f75c05a1483f054b7f0df695ce483681791f84cfb80802a"
PROFILE_PATH = "osrm/road-risk-car.lua"

CASES = (
    ("short", (34.79, 32.08), (34.77, 32.10)),
    ("long", (35.2137, 31.7683), (34.7818, 32.0853)),
    ("urban", (35.18, 31.77), (35.24, 31.79)),
    ("highway", (34.87, 32.32), (34.78, 32.08)),
    ("junction", (34.78, 32.10), (34.84, 32.18)),
    ("parallel-road", (34.793, 32.101), (34.799, 32.145)),
)


def generate_corpus(osrm_url: str) -> dict[str, object]:
    cases = []
    for name, origin, destination in CASES:
        coordinate_path = f"{origin[0]},{origin[1]};{destination[0]},{destination[1]}"
        query = urllib.parse.urlencode(
            {"alternatives": 3, "overview": "full", "geometries": "geojson"}
        )
        request_url = f"{osrm_url.rstrip('/')}/route/v1/driving/{coordinate_path}?{query}"
        with urllib.request.urlopen(request_url, timeout=30) as response:
            result = json.load(response)
        routes = result.get("routes", [])
        if result.get("code") != "Ok" or len(routes) != 3:
            raise RuntimeError(
                f"case {name!r} expected exactly three routes, "
                f"received code={result.get('code')!r}, count={len(routes)}"
            )
        cases.append(
            {
                "name": name,
                "origin": {"longitude": origin[0], "latitude": origin[1]},
                "destination": {
                    "longitude": destination[0], "latitude": destination[1]
                },
                "request_parameters": {
                    "alternatives": 3,
                    "overview": "full",
                    "geometries": "geojson",
                },
                "candidates": [
                    {
                        "candidate_index": index,
                        "distance_m": route["distance"],
                        "duration_seconds": route["duration"],
                        "geometry": route["geometry"],
                    }
                    for index, route in enumerate(routes)
                ],
            }
        )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provenance": {
            "osrm_image": OSRM_IMAGE,
            "graph_data_version": GRAPH_DATA_VERSION,
            "pbf_source": PBF_SOURCE,
            "pbf_sha256": PBF_SHA256,
            "profile_path": PROFILE_PATH,
        },
        "cases": cases,
    }


def main() -> None:
    output_path = Path(os.environ["MATCHER_CORPUS_OUTPUT"])
    output_path.write_text(
        json.dumps(generate_corpus(os.environ["OSRM_URL"]), indent=2) + "\n",
        encoding="utf-8",
    )
    print(output_path)


if __name__ == "__main__":
    main()
