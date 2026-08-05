"""Create versioned derived corridor-risk data.

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.risk_data_versions (
            version TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL,
            foundation_data_version TEXT NOT NULL
                REFERENCES app.foundation_data_versions(version),
            source_metadata JSONB NOT NULL CHECK (jsonb_typeof(source_metadata) = 'object'),
            included_year_start INTEGER NOT NULL,
            included_year_end INTEGER NOT NULL CHECK (included_year_end >= included_year_start),
            input_corridor_count BIGINT NOT NULL CHECK (input_corridor_count > 0),
            input_accident_count BIGINT NOT NULL CHECK (input_accident_count > 0),
            attributed_accident_count BIGINT NOT NULL
                CHECK (attributed_accident_count >= 0
                       AND attributed_accident_count <= input_accident_count),
            attribution_counts_by_confidence JSONB NOT NULL
                CHECK (jsonb_typeof(attribution_counts_by_confidence) = 'object'),
            output_corridor_count BIGINT NOT NULL CHECK (output_corridor_count > 0),
            reference_risk_p95 DOUBLE PRECISION NOT NULL
                CHECK (reference_risk_p95 > 0 AND reference_risk_p95 < 'Infinity'),
            validation_status TEXT NOT NULL CHECK (validation_status IN ('valid', 'invalid')),
            refresh_duration_ms DOUBLE PRECISION NOT NULL
                CHECK (refresh_duration_ms >= 0 AND refresh_duration_ms < 'Infinity'),
            storage_bytes BIGINT NOT NULL CHECK (storage_bytes >= 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            activated_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.corridor_risk_statistics (
            risk_data_version TEXT NOT NULL
                REFERENCES app.risk_data_versions(version) ON DELETE CASCADE,
            corridor_id TEXT NOT NULL,
            corridor_family TEXT NOT NULL,
            road_id TEXT,
            primary_ref TEXT,
            primary_name TEXT,
            geometry geometry(Geometry, 2039) NOT NULL,
            corridor_length_m DOUBLE PRECISION NOT NULL
                CHECK (corridor_length_m > 0 AND corridor_length_m < 'Infinity'),
            raw_accident_count BIGINT NOT NULL CHECK (raw_accident_count >= 0),
            PRIMARY KEY (risk_data_version, corridor_id),
            CHECK (ST_GeometryType(geometry) IN ('ST_LineString', 'ST_MultiLineString'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX corridor_risk_statistics_geometry_gist
        ON app.corridor_risk_statistics USING GIST (geometry)
        """
    )
    op.execute(
        """
        CREATE TABLE app.active_risk_data_version (
            singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
            version TEXT NOT NULL UNIQUE REFERENCES app.risk_data_versions(version)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.active_risk_data_version")
    op.execute("DROP TABLE IF EXISTS app.corridor_risk_statistics")
    op.execute("DROP TABLE IF EXISTS app.risk_data_versions")
