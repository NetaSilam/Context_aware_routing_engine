"""Relax app.llm_jobs' subject-presence constraint to subject-correctness only.

Revision ID: 0008
Revises: 0007

0007's constraint required a subject_post_id/subject_route_job_id to be present for its
matching kind. That is correct for the real triage/dedup/route-explanation features (tickets
4/5/7), but blocks a legitimate scheduling-only job with no real subject yet (ticket 3's
integration test, proving fast/slow queue priority in isolation before those tickets exist).
The replacement still rejects a subject column that does not match its kind (e.g. a `triage`
job cannot carry a subject_route_job_id), it just no longer requires either to be present.
"""
from typing import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE app.llm_jobs DROP CONSTRAINT llm_jobs_check")
    op.execute("ALTER TABLE app.llm_jobs DROP CONSTRAINT llm_jobs_check1")
    op.execute(
        """
        ALTER TABLE app.llm_jobs ADD CONSTRAINT llm_jobs_subject_matches_kind_check CHECK (
            (kind = 'route_explanation' OR subject_route_job_id IS NULL)
            AND (kind IN ('triage', 'dedup_check') OR subject_post_id IS NULL)
        )
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE app.llm_jobs DROP CONSTRAINT llm_jobs_subject_matches_kind_check")
    op.execute(
        """
        ALTER TABLE app.llm_jobs ADD CONSTRAINT llm_jobs_check
        CHECK ((kind IN ('triage', 'dedup_check')) = (subject_post_id IS NOT NULL))
        """
    )
    op.execute(
        """
        ALTER TABLE app.llm_jobs ADD CONSTRAINT llm_jobs_check1
        CHECK ((kind = 'route_explanation') = (subject_route_job_id IS NOT NULL))
        """
    )
