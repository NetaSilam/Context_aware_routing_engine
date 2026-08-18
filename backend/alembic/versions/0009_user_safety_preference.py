"""Add a user-level safety preference that multiplies the automatically-derived safety weight.

Revision ID: 0009
Revises: 0008

The safety weight (Wsafe) was previously derived only from an objective, automatic rule
(driving experience, vehicle type, time of day). This adds a subjective layer on top: the
user picks how much they personally weigh safety versus time, as one of three fixed levels
(never a free-form slider, to keep the ranking explainable/reproducible). It multiplies the
automatic weight rather than replacing it, so a novice motorcyclist's already-elevated
baseline is preserved even at the "low" preference.
"""
from typing import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE app.users
        ADD COLUMN safety_preference TEXT NOT NULL DEFAULT 'balanced'
            CHECK (safety_preference IN ('low', 'balanced', 'high'))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE app.users DROP COLUMN safety_preference")
