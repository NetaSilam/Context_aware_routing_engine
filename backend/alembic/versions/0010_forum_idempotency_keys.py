"""Add an optional idempotency key to forum posts and comments.

Revision ID: 0010
Revises: 0009

Route job creation already required an Idempotency-Key header and deduplicated on
(user_id, idempotency_key); forum post/comment creation had no equivalent, so a fast
double-click (or a client's own retry-on-timeout) could silently create duplicate reports or
comments -- the per-user rate limiter throttles *volume* but never de-duplicates a specific
retried request. Unlike route jobs the header is optional here (older/other API clients keep
working unchanged); when present, a partial unique index makes the same (author, key) pair
collide at the database level so a genuine concurrent double-submit can't create two rows.
"""
from typing import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE app.forum_posts ADD COLUMN idempotency_key UUID")
    op.execute(
        """
        CREATE UNIQUE INDEX forum_posts_author_idempotency_key_idx
        ON app.forum_posts (author_user_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL
        """
    )
    op.execute("ALTER TABLE app.forum_comments ADD COLUMN idempotency_key UUID")
    op.execute(
        """
        CREATE UNIQUE INDEX forum_comments_author_idempotency_key_idx
        ON app.forum_comments (author_user_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS app.forum_comments_author_idempotency_key_idx")
    op.execute("ALTER TABLE app.forum_comments DROP COLUMN idempotency_key")
    op.execute("DROP INDEX IF EXISTS app.forum_posts_author_idempotency_key_idx")
    op.execute("ALTER TABLE app.forum_posts DROP COLUMN idempotency_key")
