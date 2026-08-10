from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection

_CHANNEL_PREFIX = "forum-notifications"


def notification_channel(recipient_user_id: int) -> str:
    return f"{_CHANNEL_PREFIX}:{recipient_user_id}"


async def create_notification(
    connection: AsyncConnection,
    *,
    recipient_user_id: int,
    actor_user_id: int,
    kind: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Insert a notification row, unless the recipient is the actor themself."""
    if recipient_user_id == actor_user_id:
        return None
    row = (
        await connection.execute(
            text(
                """
                INSERT INTO app.notifications (id, recipient_user_id, kind, payload)
                VALUES (:id, :recipient_user_id, :kind, :payload)
                RETURNING id, recipient_user_id, kind, payload, created_at, read_at
                """
            ).bindparams(bindparam("payload", type_=JSONB)),
            {
                "id": uuid4(),
                "recipient_user_id": recipient_user_id,
                "kind": kind,
                "payload": payload,
            },
        )
    ).mappings().one()
    return dict(row)


async def publish_notification(redis: Redis, notification: dict[str, Any] | None) -> None:
    """Publish after the transaction that inserted the row has committed, so a subscriber
    that reacts by calling GET /api/notifications always finds the row already there."""
    if notification is None:
        return
    event = {
        "id": str(notification["id"]),
        "kind": notification["kind"],
        "payload": notification["payload"],
        "created_at": notification["created_at"].isoformat(),
    }
    await redis.publish(notification_channel(notification["recipient_user_id"]), json.dumps(event))
