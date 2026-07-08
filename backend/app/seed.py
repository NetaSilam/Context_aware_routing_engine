from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

DATA_DIR = Path("/data")

# schema -> table -> (source file under DATA_DIR, has geometry column)
# Table/schema names match backend/app/repositories/{canonical_network,accident_attribution}.py
# in the foundation pipeline repo, so its query code can be ported without renaming anything.
SEED_TABLES: dict[str, dict[str, tuple[str, bool]]] = {
    "foundation_data": {
        "prepared_accidents": ("prepared_accidents.geoparquet", True),
        "prepared_osm_roads": ("prepared_osm_roads.geoparquet", True),
        "prepared_official_segments": ("prepared_official_segments.geoparquet", True),
        "prepared_segment_osm_matches": ("prepared_segment_osm_matches.parquet", False),
    },
    "canonical_network": {
        "canonical_corridors": ("canonical_corridors.geoparquet", True),
        "official_segment_links": ("official_segment_links.parquet", False),
    },
    "accident_attribution": {
        "accident_attributions": ("accident_attributions.geoparquet", True),
        "accident_attribution_summary": ("accident_attribution_summary.parquet", False),
    },
}


def _table_has_rows(engine: Engine, schema: str, table: str) -> bool:
    exists_query = text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = :schema AND table_name = :table)"
    )
    with engine.connect() as conn:
        exists = conn.execute(exists_query, {"schema": schema, "table": table}).scalar()
        if not exists:
            return False
        count = conn.execute(text(f'SELECT COUNT(*) FROM "{schema}"."{table}"')).scalar()
        return bool(count)


def _create_spatial_index(engine: Engine, schema: str, table: str) -> None:
    index_name = f"{table}_geometry_idx"
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    f'CREATE INDEX IF NOT EXISTS "{index_name}" '
                    f'ON "{schema}"."{table}" USING GIST (geometry)'
                )
            )
    except Exception:
        logger.warning(
            "Could not create spatial index on %s.%s (geometry column may be named "
            "differently) - queries against it may be slow.",
            schema,
            table,
        )


def _stringify_nested_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Some summary/audit columns hold dict/list values (e.g. `status_breakdown`).
    Neither pandas.to_sql nor psycopg can bind a raw dict to a plain column, so these
    get JSON-encoded to text here rather than inserted as native jsonb - simpler and
    safer than relying on a specific SQLAlchemy/psycopg JSON-adapter version, at the
    cost of the API doing its own json.loads() if it ever needs to query into them.
    """
    for col in frame.columns:
        if frame[col].dtype != object:
            continue
        sample = frame[col].dropna()
        if not sample.empty and isinstance(sample.iloc[0], (dict, list)):
            frame[col] = frame[col].apply(
                lambda v: json.dumps(v, default=str) if isinstance(v, (dict, list)) else v
            )
    return frame


def ensure_seeded(engine: Engine, data_dir: Path = DATA_DIR) -> None:
    """Loads the foundation pipeline's parquet/geoparquet exports into PostGIS,
    once. Safe to call on every app startup - skips any table that already has rows.
    """
    if not data_dir.exists():
        logger.warning("Seed data directory %s not found; skipping seed.", data_dir)
        return

    with engine.begin() as conn:
        for schema in SEED_TABLES:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))

    for schema, tables in SEED_TABLES.items():
        for table, (filename, is_geo) in tables.items():
            path = data_dir / filename
            if not path.exists():
                logger.warning("Seed file %s not found; skipping %s.%s.", path, schema, table)
                continue
            if _table_has_rows(engine, schema, table):
                logger.info("%s.%s already seeded; skipping.", schema, table)
                continue

            logger.info("Seeding %s.%s from %s ...", schema, table, path)
            if is_geo:
                frame = gpd.read_parquet(path)
                frame = _stringify_nested_columns(frame)
                frame.to_postgis(table, engine, schema=schema, if_exists="replace", index=False)
                _create_spatial_index(engine, schema, table)
            else:
                frame = pd.read_parquet(path)
                frame = _stringify_nested_columns(frame)
                frame.to_sql(table, engine, schema=schema, if_exists="replace", index=False)

    logger.info("Seed check complete.")
