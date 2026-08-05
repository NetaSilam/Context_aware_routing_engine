"""Create persistent asynchronous route jobs.

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.route_jobs (
            id UUID PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
            origin_longitude DOUBLE PRECISION NOT NULL,
            origin_latitude DOUBLE PRECISION NOT NULL,
            destination_longitude DOUBLE PRECISION NOT NULL,
            destination_latitude DOUBLE PRECISION NOT NULL,
            origin_label TEXT,
            destination_label TEXT,
            snapshot JSONB NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
            chosen_index INTEGER,
            route_count INTEGER,
            result JSONB CHECK (result IS NULL OR jsonb_typeof(result) = 'object'),
            error_code TEXT,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            CHECK (origin_label IS NULL OR char_length(origin_label) <= 200),
            CHECK (destination_label IS NULL OR char_length(destination_label) <= 200),
            CHECK (
                (status = 'completed' AND result IS NOT NULL AND completed_at IS NOT NULL)
                OR status <> 'completed'
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX route_jobs_user_created_idx
        ON app.route_jobs (user_id, created_at DESC, id DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.route_jobs")
