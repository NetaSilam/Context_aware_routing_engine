from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


@dataclass(frozen=True)
class FoundationSource:
    schema: str
    table: str
    filename: str
    has_geometry: bool


FOUNDATION_SOURCES = (
    FoundationSource(
        "canonical_network", "canonical_corridors", "canonical_corridors.geoparquet", True
    ),
    FoundationSource(
        "canonical_network", "official_segment_links", "official_segment_links.parquet", False
    ),
    FoundationSource(
        "accident_attribution", "accident_attributions", "accident_attributions.geoparquet", True
    ),
    FoundationSource(
        "accident_attribution",
        "accident_attribution_summary",
        "accident_attribution_summary.parquet",
        False,
    ),
)


def source_paths(data_dir: Path) -> tuple[Path, ...]:
    paths = tuple(data_dir / source.filename for source in FOUNDATION_SOURCES)
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "real foundation data is missing required files: " + ", ".join(missing)
        )
    return paths


def source_manifest_checksum(data_dir: Path) -> str:
    """Return the documented checksum for the foundation artifact manifest."""
    file_checksums: dict[str, str] = {}
    for source, path in zip(FOUNDATION_SOURCES, source_paths(data_dir), strict=True):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        file_checksums[source.filename] = digest.hexdigest()
    manifest = json.dumps(file_checksums, sort_keys=True).encode("utf-8")
    return hashlib.sha256(manifest).hexdigest()


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sqlalchemy_database_url(value: str) -> str:
    url = make_url(value)
    if url.drivername in {"postgresql", "postgresql+asyncpg"}:
        return url.set(drivername="postgresql+psycopg").render_as_string(
            hide_password=False
        )
    return value


def _table_state(connection: Any) -> dict[tuple[str, str], int | None]:
    state: dict[tuple[str, str], int | None] = {}
    for source in FOUNDATION_SOURCES:
        exists = connection.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = :schema AND table_name = :table)"
            ),
            {"schema": source.schema, "table": source.table},
        ).scalar()
        if not exists:
            state[(source.schema, source.table)] = None
            continue
        state[(source.schema, source.table)] = int(
            connection.execute(
                text(
                    f"SELECT count(*) FROM {_quote_identifier(source.schema)}."
                    f"{_quote_identifier(source.table)}"
                )
            ).scalar_one()
        )
    return state


def _stringify_nested_columns(frame: Any) -> Any:
    """Make dict/list Parquet fields safe for ordinary SQL text columns."""
    for column in frame.columns:
        series = frame[column]
        if series.dtype != object:
            continue
        sample = series.dropna()
        if sample.empty or not isinstance(sample.iloc[0], (dict, list)):
            continue
        frame[column] = series.apply(
            lambda value: json.dumps(value, default=str)
            if isinstance(value, (dict, list))
            else value
        )
    return frame


def _read_source(source: FoundationSource, path: Path) -> Any:
    if source.has_geometry:
        import geopandas as gpd

        frame = gpd.read_parquet(path)
    else:
        import pandas as pd

        frame = pd.read_parquet(path)
    return _stringify_nested_columns(frame)


def _create_geometry_index(connection: Any, source: FoundationSource) -> None:
    index_name = f"{source.table}_geometry_gist"
    connection.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS {_quote_identifier(index_name)} "
            f"ON {_quote_identifier(source.schema)}.{_quote_identifier(source.table)} "
            "USING GIST (geometry)"
        )
    )


def load_real_foundation(database_url: str, data_dir: Path) -> None:
    """Load the prepared real-data artifacts into PostGIS exactly once.

    Existing complete, non-empty tables are left untouched. A partial or empty
    table set is rejected so a failed or stale database cannot be mistaken for a
    valid foundation dataset.
    """
    source_paths(data_dir)
    engine = create_engine(_sqlalchemy_database_url(database_url), pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            state = _table_state(connection)
            existing_counts = tuple(state.values())
            if all(count is not None and count > 0 for count in existing_counts):
                return
            if any(count is not None for count in existing_counts):
                partial = [
                    f"{schema}.{table}={count}"
                    for (schema, table), count in state.items()
                    if count is not None
                ]
                raise RuntimeError(
                    "real foundation tables are partial or empty: " + ", ".join(partial)
                )

            for source in FOUNDATION_SOURCES:
                connection.execute(
                    text(f"CREATE SCHEMA IF NOT EXISTS {_quote_identifier(source.schema)}")
                )

            for source, path in zip(FOUNDATION_SOURCES, source_paths(data_dir), strict=True):
                frame = _read_source(source, path)
                if source.has_geometry:
                    frame.to_postgis(
                        source.table,
                        connection,
                        schema=source.schema,
                        if_exists="fail",
                        index=False,
                    )
                    _create_geometry_index(connection, source)
                else:
                    frame.to_sql(
                        source.table,
                        connection,
                        schema=source.schema,
                        if_exists="fail",
                        index=False,
                    )

            loaded_state = _table_state(connection)
            empty = [
                f"{schema}.{table}"
                for (schema, table), count in loaded_state.items()
                if count is None or count <= 0
            ]
            if empty:
                raise RuntimeError(
                    "real foundation load produced missing or empty tables: "
                    + ", ".join(empty)
                )
    finally:
        engine.dispose()
