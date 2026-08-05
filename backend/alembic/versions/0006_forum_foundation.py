"""Create the forum, direct-message, and notification schema.

Revision ID: 0006
Revises: 0005
"""
from typing import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HAZARD_TYPES = (
    "pothole",
    "flooding",
    "broken_signal",
    "poor_lighting",
    "illegal_speed_bump",
    "crash",
    "other",
)


def upgrade() -> None:
    op.execute("ALTER TABLE app.users ADD COLUMN is_seed_account BOOLEAN NOT NULL DEFAULT FALSE")

    op.execute(
        f"""
        CREATE TABLE app.forum_posts (
            id UUID PRIMARY KEY,
            author_user_id BIGINT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            is_anonymous BOOLEAN NOT NULL DEFAULT FALSE,
            hazard_type TEXT NOT NULL CHECK (hazard_type IN {HAZARD_TYPES}),
            title TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
            body TEXT NOT NULL CHECK (char_length(body) BETWEEN 1 AND 5000),
            longitude DOUBLE PRECISION,
            latitude DOUBLE PRECISION,
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'removed')),
            upvote_count INTEGER NOT NULL DEFAULT 0 CHECK (upvote_count >= 0),
            downvote_count INTEGER NOT NULL DEFAULT 0 CHECK (downvote_count >= 0),
            comment_count INTEGER NOT NULL DEFAULT 0 CHECK (comment_count >= 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK ((longitude IS NULL) = (latitude IS NULL))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX forum_posts_feed_idx
        ON app.forum_posts (status, created_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX forum_posts_hazard_feed_idx
        ON app.forum_posts (status, hazard_type, created_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX forum_posts_author_idx
        ON app.forum_posts (author_user_id, created_at DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE app.forum_post_media (
            id UUID PRIMARY KEY,
            post_id UUID NOT NULL REFERENCES app.forum_posts(id) ON DELETE CASCADE,
            media_type TEXT NOT NULL CHECK (media_type IN ('image', 'video')),
            storage_key TEXT NOT NULL,
            content_type TEXT NOT NULL,
            byte_size INTEGER NOT NULL CHECK (byte_size > 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX forum_post_media_post_idx
        ON app.forum_post_media (post_id)
        """
    )

    op.execute(
        """
        CREATE TABLE app.forum_comments (
            id UUID PRIMARY KEY,
            post_id UUID NOT NULL REFERENCES app.forum_posts(id) ON DELETE CASCADE,
            author_user_id BIGINT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            is_anonymous BOOLEAN NOT NULL DEFAULT FALSE,
            body TEXT NOT NULL CHECK (char_length(body) BETWEEN 1 AND 2000),
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'removed')),
            upvote_count INTEGER NOT NULL DEFAULT 0 CHECK (upvote_count >= 0),
            downvote_count INTEGER NOT NULL DEFAULT 0 CHECK (downvote_count >= 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX forum_comments_post_idx
        ON app.forum_comments (post_id, status, created_at ASC, id ASC)
        """
    )
    op.execute(
        """
        CREATE INDEX forum_comments_author_idx
        ON app.forum_comments (author_user_id, created_at DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE app.forum_comment_media (
            id UUID PRIMARY KEY,
            comment_id UUID NOT NULL REFERENCES app.forum_comments(id) ON DELETE CASCADE,
            media_type TEXT NOT NULL CHECK (media_type IN ('image', 'video')),
            storage_key TEXT NOT NULL,
            content_type TEXT NOT NULL,
            byte_size INTEGER NOT NULL CHECK (byte_size > 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX forum_comment_media_comment_idx
        ON app.forum_comment_media (comment_id)
        """
    )

    op.execute(
        """
        CREATE TABLE app.forum_votes (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            target_type TEXT NOT NULL CHECK (target_type IN ('post', 'comment')),
            target_id UUID NOT NULL,
            value SMALLINT NOT NULL CHECK (value IN (-1, 1)),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (user_id, target_type, target_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX forum_votes_target_idx
        ON app.forum_votes (target_type, target_id)
        """
    )

    op.execute(
        """
        CREATE TABLE app.direct_messages (
            id UUID PRIMARY KEY,
            sender_user_id BIGINT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            recipient_user_id BIGINT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            body TEXT CHECK (body IS NULL OR char_length(body) BETWEEN 1 AND 2000),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            read_at TIMESTAMPTZ,
            CHECK (sender_user_id <> recipient_user_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX direct_messages_sender_conversation_idx
        ON app.direct_messages (sender_user_id, recipient_user_id, created_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX direct_messages_recipient_conversation_idx
        ON app.direct_messages (recipient_user_id, sender_user_id, created_at DESC, id DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE app.direct_message_media (
            id UUID PRIMARY KEY,
            message_id UUID NOT NULL REFERENCES app.direct_messages(id) ON DELETE CASCADE,
            media_type TEXT NOT NULL CHECK (media_type IN ('image', 'video')),
            storage_key TEXT NOT NULL,
            content_type TEXT NOT NULL,
            byte_size INTEGER NOT NULL CHECK (byte_size > 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX direct_message_media_message_idx
        ON app.direct_message_media (message_id)
        """
    )

    op.execute(
        """
        CREATE TABLE app.notifications (
            id UUID PRIMARY KEY,
            recipient_user_id BIGINT NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK (kind IN ('new_dm', 'new_vote', 'new_comment')),
            payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            read_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE INDEX notifications_recipient_idx
        ON app.notifications (recipient_user_id, created_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX notifications_recipient_unread_idx
        ON app.notifications (recipient_user_id, created_at DESC)
        WHERE read_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.notifications")
    op.execute("DROP TABLE IF EXISTS app.direct_message_media")
    op.execute("DROP TABLE IF EXISTS app.direct_messages")
    op.execute("DROP TABLE IF EXISTS app.forum_votes")
    op.execute("DROP TABLE IF EXISTS app.forum_comment_media")
    op.execute("DROP TABLE IF EXISTS app.forum_comments")
    op.execute("DROP TABLE IF EXISTS app.forum_post_media")
    op.execute("DROP TABLE IF EXISTS app.forum_posts")
    op.execute("ALTER TABLE app.users DROP COLUMN IF EXISTS is_seed_account")
