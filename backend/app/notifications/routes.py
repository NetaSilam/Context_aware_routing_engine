from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.auth import get_current_user, require_trusted_origin
from app.config import get_settings
from app.db import get_engine
from app.notifications.service import notification_channel
from app.request_bounds import reject_unexpected_query_parameters

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: UUID
    kind: str
    payload: dict[str, Any]
    created_at: datetime
    read_at: datetime | None


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    offset: int
    limit: int
    has_more: bool
    unread_count: int


def _service_unavailable(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=detail,
        headers={"Retry-After": "5"},
    )


@router.get("", response_model=NotificationPage)
async def list_notifications(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> dict[str, Any]:
    reject_unexpected_query_parameters(request, {"offset", "limit"})
    viewer_id = int(user["id"])
    try:
        async with get_engine().begin() as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        SELECT id, kind, payload, created_at, read_at
                        FROM app.notifications
                        WHERE recipient_user_id = :viewer_id
                        ORDER BY created_at DESC, id DESC
                        OFFSET :offset LIMIT :fetch_limit
                        """
                    ),
                    {"viewer_id": viewer_id, "offset": offset, "fetch_limit": limit + 1},
                )
            ).mappings().all()
            unread_count = (
                await connection.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM app.notifications
                        WHERE recipient_user_id = :viewer_id AND read_at IS NULL
                        """
                    ),
                    {"viewer_id": viewer_id},
                )
            ).scalar_one()
    except SQLAlchemyError as exc:
        raise _service_unavailable("The notifications service is temporarily unavailable.") from exc
    items = [dict(row) for row in rows[:limit]]
    return {
        "items": items,
        "offset": offset,
        "limit": limit,
        "has_more": len(rows) > limit,
        "unread_count": unread_count,
    }


@router.post(
    "/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_trusted_origin)],
)
async def mark_notification_read(
    notification_id: UUID, user: dict[str, Any] = Depends(get_current_user)
) -> Response:
    try:
        async with get_engine().begin() as connection:
            owned = (
                await connection.execute(
                    text(
                        "SELECT id FROM app.notifications WHERE id = :id AND recipient_user_id = :viewer_id"
                    ),
                    {"id": notification_id, "viewer_id": user["id"]},
                )
            ).mappings().first()
            if owned is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found."
                )
            await connection.execute(
                text(
                    "UPDATE app.notifications SET read_at = now() WHERE id = :id AND read_at IS NULL"
                ),
                {"id": notification_id},
            )
    except SQLAlchemyError as exc:
        raise _service_unavailable("The notifications service is temporarily unavailable.") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/read-all",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_trusted_origin)],
)
async def mark_all_notifications_read(
    user: dict[str, Any] = Depends(get_current_user),
) -> Response:
    try:
        async with get_engine().begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE app.notifications SET read_at = now()
                    WHERE recipient_user_id = :viewer_id AND read_at IS NULL
                    """
                ),
                {"viewer_id": user["id"]},
            )
    except SQLAlchemyError as exc:
        raise _service_unavailable("The notifications service is temporarily unavailable.") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/stream")
async def stream_notifications(
    request: Request, user: dict[str, Any] = Depends(get_current_user)
) -> StreamingResponse:
    channel = notification_channel(int(user["id"]))

    async def event_generator() -> AsyncIterator[str]:
        # A dedicated connection, not the app-wide cached get_redis() client: this
        # subscription is held open for the lifetime of the SSE connection (potentially
        # hours), and sharing the singleton client's connection pool with it starved every
        # other request on the shared pool for as long as the stream stayed open.
        redis = Redis.from_url(str(get_settings().redis_url), decode_responses=True)
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            yield "event: ready\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
                if message is not None and message.get("type") == "message":
                    yield f"data: {message['data']}\n\n"
                else:
                    yield ": keep-alive\n\n"
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            await redis.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
