"""Create the application foundation schema.

Revision ID: 0001
Revises: None
"""
from typing import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.execute(
        """
        CREATE TABLE app.users (
            id BIGSERIAL PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            driving_experience TEXT NOT NULL DEFAULT 'experienced'
                CHECK (driving_experience IN ('novice', 'experienced')),
            vehicle_type TEXT NOT NULL DEFAULT 'car'
                CHECK (vehicle_type IN ('car', 'motorcycle', 'truck')),
            avoid_tolls BOOLEAN NOT NULL DEFAULT FALSE,
            avoid_highways BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.foundation_data_versions (
            version TEXT PRIMARY KEY,
            source_checksum TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            row_counts JSONB NOT NULL,
            initialized_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.foundation_data_versions")
    op.execute("DROP TABLE IF EXISTS app.users")
    op.execute("DROP SCHEMA IF EXISTS app")
