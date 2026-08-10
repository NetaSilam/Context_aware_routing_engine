from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.abuse_protection import enforce_action_rate_limit
from app.auth import get_current_user, require_trusted_origin
from app.config import get_settings
from app.db import get_engine
from app.forum.media_storage import classify_and_validate_media, write_media_file
from app.forum.routes import MediaItem
from app.notifications.service import create_notification, publish_notification
from app.redis_client import get_redis
from app.request_bounds import reject_unexpected_query_parameters

router = APIRouter(prefix="/api/messages", tags=["messages"])


class MessageOut(BaseModel):
    id: UUID
    sender_user_id: int
    sender_email: str
    recipient_user_id: int
    recipient_email: str
    body: str | None
    media: MediaItem | None
    created_at: datetime
    read_at: datetime | None


class MessagePage(BaseModel):
    items: list[MessageOut]
    offset: int
    limit: int
    has_more: bool


class ConversationSummary(BaseModel):
    other_user_id: int
    other_user_email: str
    last_message_body: str | None
    last_message_at: datetime
    unread_count: int


class ConversationPage(BaseModel):
    items: list[ConversationSummary]
    offset: int
    limit: int
    has_more: bool


def _service_unavailable(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=detail,
        headers={"Retry-After": "5"},
    )


def _normalized_content_type(upload: UploadFile) -> str:
    return (upload.content_type or "").split(";")[0].strip().lower()


def _serialize_message(
    row: Any, *, sender_email: str, recipient_email: str, media: Any | None
) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sender_user_id": row["sender_user_id"],
        "sender_email": sender_email,
        "recipient_user_id": row["recipient_user_id"],
        "recipient_email": recipient_email,
        "body": row["body"],
        "media": dict(media) if media is not None else None,
        "created_at": row["created_at"],
        "read_at": row["read_at"],
    }


def _serialize_conversation_message_row(row: Any) -> dict[str, Any]:
    media = None
    if row["media_id"] is not None:
        media = {
            "id": row["media_id"],
            "media_type": row["media_type"],
            "content_type": row["content_type"],
            "byte_size": row["byte_size"],
        }
    return {
        "id": row["id"],
        "sender_user_id": row["sender_user_id"],
        "sender_email": row["sender_email"],
        "recipient_user_id": row["recipient_user_id"],
        "recipient_email": row["recipient_email"],
        "body": row["body"],
        "media": media,
        "created_at": row["created_at"],
        "read_at": row["read_at"],
    }


@router.post(
    "/{recipient_user_id}",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_trusted_origin)],
)
async def send_message(
    recipient_user_id: int,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    body: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
) -> dict[str, Any]:
    settings = get_settings()
    if recipient_user_id == int(user["id"]):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot send a message to yourself.",
        )
    normalized_body = (body or "").strip() or None
    if normalized_body is not None and len(normalized_body) > 2000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message body must be at most 2000 characters.",
        )
    data = await file.read() if file is not None else b""
    if normalized_body is None and not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message must include text or an attachment.",
        )
    content_type: str | None = None
    media_type: str | None = None
    if data:
        content_type = _normalized_content_type(file)
        media_type = classify_and_validate_media(content_type, len(data), settings)

    await enforce_action_rate_limit(
        "dm-send",
        request,
        int(user["id"]),
        user_limit=settings.dm_send_user_rate_limit,
        ip_limit=settings.dm_send_ip_rate_limit,
    )

    message_id = uuid4()
    notification = None
    try:
        async with get_engine().begin() as connection:
            recipient = (
                await connection.execute(
                    text("SELECT email FROM app.users WHERE id = :id"),
                    {"id": recipient_user_id},
                )
            ).mappings().first()
            if recipient is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Recipient not found."
                )
            row = (
                await connection.execute(
                    text(
                        """
                        INSERT INTO app.direct_messages (id, sender_user_id, recipient_user_id, body)
                        VALUES (:id, :sender_user_id, :recipient_user_id, :body)
                        RETURNING id, sender_user_id, recipient_user_id, body, created_at, read_at
                        """
                    ),
                    {
                        "id": message_id,
                        "sender_user_id": user["id"],
                        "recipient_user_id": recipient_user_id,
                        "body": normalized_body,
                    },
                )
            ).mappings().one()
            media_row = None
            if data:
                storage_key = await asyncio.to_thread(write_media_file, settings, data)
                media_row = (
                    await connection.execute(
                        text(
                            """
                            INSERT INTO app.direct_message_media
                                (id, message_id, media_type, storage_key, content_type, byte_size)
                            VALUES (:id, :message_id, :media_type, :storage_key, :content_type, :byte_size)
                            RETURNING id, media_type, content_type, byte_size
                            """
                        ),
                        {
                            "id": uuid4(),
                            "message_id": message_id,
                            "media_type": media_type,
                            "storage_key": storage_key,
                            "content_type": content_type,
                            "byte_size": len(data),
                        },
                    )
                ).mappings().one()
            notification = await create_notification(
                connection,
                recipient_user_id=recipient_user_id,
                actor_user_id=int(user["id"]),
                kind="new_dm",
                payload={
                    "message_id": str(message_id),
                    "sender_user_id": int(user["id"]),
                    "sender_email": user["email"],
                },
            )
    except SQLAlchemyError as exc:
        raise _service_unavailable("The messaging service is temporarily unavailable.") from exc
    await publish_notification(get_redis(), notification)
    return _serialize_message(
        row, sender_email=user["email"], recipient_email=recipient["email"], media=media_row
    )


@router.get("/{other_user_id}", response_model=MessagePage)
async def get_conversation(
    other_user_id: int,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> dict[str, Any]:
    reject_unexpected_query_parameters(request, {"offset", "limit"})
    viewer_id = int(user["id"])
    try:
        async with get_engine().begin() as connection:
            other = (
                await connection.execute(
                    text("SELECT id FROM app.users WHERE id = :id"), {"id": other_user_id}
                )
            ).mappings().first()
            if other is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found."
                )
            await connection.execute(
                text(
                    """
                    UPDATE app.direct_messages SET read_at = now()
                    WHERE sender_user_id = :other_id AND recipient_user_id = :viewer_id
                          AND read_at IS NULL
                    """
                ),
                {"other_id": other_user_id, "viewer_id": viewer_id},
            )
            rows = (
                await connection.execute(
                    text(
                        """
                        SELECT dm.id, dm.sender_user_id, dm.recipient_user_id, dm.body,
                               dm.created_at, dm.read_at,
                               su.email AS sender_email, ru.email AS recipient_email,
                               dmm.id AS media_id, dmm.media_type, dmm.content_type, dmm.byte_size
                        FROM app.direct_messages dm
                        JOIN app.users su ON su.id = dm.sender_user_id
                        JOIN app.users ru ON ru.id = dm.recipient_user_id
                        LEFT JOIN app.direct_message_media dmm ON dmm.message_id = dm.id
                        WHERE (dm.sender_user_id = :viewer_id AND dm.recipient_user_id = :other_id)
                           OR (dm.sender_user_id = :other_id AND dm.recipient_user_id = :viewer_id)
                        ORDER BY dm.created_at DESC, dm.id DESC
                        OFFSET :offset LIMIT :fetch_limit
                        """
                    ),
                    {
                        "viewer_id": viewer_id,
                        "other_id": other_user_id,
                        "offset": offset,
                        "fetch_limit": limit + 1,
                    },
                )
            ).mappings().all()
    except SQLAlchemyError as exc:
        raise _service_unavailable("The messaging service is temporarily unavailable.") from exc
    page_rows = rows[:limit]
    items = [_serialize_conversation_message_row(row) for row in reversed(page_rows)]
    return {"items": items, "offset": offset, "limit": limit, "has_more": len(rows) > limit}


@router.get("", response_model=ConversationPage)
async def list_conversations(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict[str, Any]:
    reject_unexpected_query_parameters(request, {"offset", "limit"})
    viewer_id = int(user["id"])
    try:
        async with get_engine().begin() as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        WITH partners AS (
                            SELECT
                                CASE WHEN sender_user_id = :viewer_id THEN recipient_user_id
                                     ELSE sender_user_id END AS other_user_id,
                                body, created_at
                            FROM app.direct_messages
                            WHERE sender_user_id = :viewer_id OR recipient_user_id = :viewer_id
                        ),
                        ranked AS (
                            SELECT *,
                                   ROW_NUMBER() OVER (
                                       PARTITION BY other_user_id ORDER BY created_at DESC
                                   ) AS rn
                            FROM partners
                        )
                        SELECT r.other_user_id, u.email AS other_user_email,
                               r.body AS last_message_body, r.created_at AS last_message_at,
                               (
                                   SELECT COUNT(*) FROM app.direct_messages dm
                                   WHERE dm.sender_user_id = r.other_user_id
                                         AND dm.recipient_user_id = :viewer_id
                                         AND dm.read_at IS NULL
                               ) AS unread_count
                        FROM ranked r
                        JOIN app.users u ON u.id = r.other_user_id
                        WHERE r.rn = 1
                        ORDER BY r.created_at DESC
                        OFFSET :offset LIMIT :fetch_limit
                        """
                    ),
                    {"viewer_id": viewer_id, "offset": offset, "fetch_limit": limit + 1},
                )
            ).mappings().all()
    except SQLAlchemyError as exc:
        raise _service_unavailable("The messaging service is temporarily unavailable.") from exc
    items = [
        {
            "other_user_id": row["other_user_id"],
            "other_user_email": row["other_user_email"],
            "last_message_body": row["last_message_body"],
            "last_message_at": row["last_message_at"],
            "unread_count": row["unread_count"],
        }
        for row in rows[:limit]
    ]
    return {"items": items, "offset": offset, "limit": limit, "has_more": len(rows) > limit}
