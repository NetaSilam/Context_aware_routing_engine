"""Add the completed route history lookup index.

Revision ID: 0005
Revises: 0004
"""
from typing import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX route_jobs_completed_history_idx
        ON app.route_jobs (user_id, status, completed_at DESC, id DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS app.route_jobs_completed_history_idx")
