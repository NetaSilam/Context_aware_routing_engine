"""Create the LLM job queue schema and forum post classification columns.

Revision ID: 0007
Revises: 0006
"""
from typing import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app.forum_posts
            ADD COLUMN llm_hazard_type_suggested TEXT,
            ADD COLUMN llm_severity TEXT CHECK (llm_severity IN ('low', 'medium', 'high')),
            ADD COLUMN duplicate_of_post_id UUID REFERENCES app.forum_posts(id)
        """
    )

    op.execute(
        """
        CREATE TABLE app.llm_jobs (
            id UUID PRIMARY KEY,
            kind TEXT NOT NULL CHECK (kind IN ('triage', 'dedup_check', 'route_explanation')),
            subject_post_id UUID REFERENCES app.forum_posts(id) ON DELETE CASCADE,
            subject_route_job_id UUID REFERENCES app.route_jobs(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'running', 'completed', 'failed')),
            queue_name TEXT NOT NULL CHECK (queue_name IN ('llm-fast', 'llm-slow')),
            estimated_duration_ms INTEGER NOT NULL CHECK (estimated_duration_ms >= 0),
            result JSONB CHECK (result IS NULL OR jsonb_typeof(result) = 'object'),
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ,
            CHECK ((kind IN ('triage', 'dedup_check')) = (subject_post_id IS NOT NULL)),
            CHECK ((kind = 'route_explanation') = (subject_route_job_id IS NOT NULL))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX llm_jobs_subject_post_idx
        ON app.llm_jobs (subject_post_id)
        WHERE subject_post_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX llm_jobs_subject_route_job_idx
        ON app.llm_jobs (subject_route_job_id)
        WHERE subject_route_job_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX llm_jobs_status_idx
        ON app.llm_jobs (status, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.llm_jobs")
    op.execute(
        """
        ALTER TABLE app.forum_posts
            DROP COLUMN IF EXISTS llm_hazard_type_suggested,
            DROP COLUMN IF EXISTS llm_severity,
            DROP COLUMN IF EXISTS duplicate_of_post_id
        """
    )
