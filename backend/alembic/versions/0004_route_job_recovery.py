"""Add idempotency, enqueue recovery, and worker leases.

Revision ID: 0004
Revises: 0003
"""
from typing import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app.route_jobs DROP CONSTRAINT route_jobs_status_check;
        ALTER TABLE app.route_jobs
            ADD CONSTRAINT route_jobs_status_check
            CHECK (status IN (
                'created', 'enqueue_failed', 'queued', 'running', 'completed', 'failed'
            ));

        ALTER TABLE app.route_jobs
            ADD COLUMN idempotency_key UUID,
            ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0
                CHECK (attempt_count >= 0),
            ADD COLUMN lease_token UUID,
            ADD COLUMN lease_expires_at TIMESTAMPTZ,
            ADD COLUMN enqueued_at TIMESTAMPTZ;

        UPDATE app.route_jobs SET idempotency_key = id;

        ALTER TABLE app.route_jobs
            ALTER COLUMN idempotency_key SET NOT NULL;

        CREATE UNIQUE INDEX route_jobs_user_idempotency_idx
            ON app.route_jobs (user_id, idempotency_key);
        CREATE INDEX route_jobs_stale_created_idx
            ON app.route_jobs (created_at)
            WHERE status = 'created';

        ALTER TABLE app.route_jobs
            ADD CONSTRAINT route_jobs_lease_shape_check CHECK (
                (lease_token IS NULL AND lease_expires_at IS NULL)
                OR (lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
            );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS app.route_jobs_stale_created_idx;
        DROP INDEX IF EXISTS app.route_jobs_user_idempotency_idx;
        ALTER TABLE app.route_jobs DROP CONSTRAINT route_jobs_lease_shape_check;
        ALTER TABLE app.route_jobs
            DROP COLUMN enqueued_at,
            DROP COLUMN lease_expires_at,
            DROP COLUMN lease_token,
            DROP COLUMN attempt_count,
            DROP COLUMN idempotency_key;
        ALTER TABLE app.route_jobs DROP CONSTRAINT route_jobs_status_check;
        ALTER TABLE app.route_jobs
            ADD CONSTRAINT route_jobs_status_check
            CHECK (status IN ('queued', 'running', 'completed', 'failed'));
        """
    )
