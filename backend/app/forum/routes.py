from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Text, bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.abuse_protection import enforce_action_rate_limit
from app.auth import get_current_user, require_trusted_origin
from app.config import get_settings
from app.db import get_engine
from app.forum.media_storage import classify_and_validate_media, read_media_file, write_media_file
from app.llm.service import create_llm_job, enqueue_llm_job
from app.notifications.service import create_notification, publish_notification
from app.redis_client import get_redis
from app.request_bounds import reject_unexpected_query_parameters

router = APIRouter(prefix="/api/forum", tags=["forum"])

HazardType = Literal[
    "pothole",
    "flooding",
    "broken_signal",
    "poor_lighting",
    "illegal_speed_bump",
    "crash",
    "other",
]
VoteValue = Literal["up", "down", "none"]

_VOTE_TO_INT = {"up": 1, "down": -1, "none": 0}


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PostCreate(StrictRequest):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    hazard_type: HazardType
    is_anonymous: bool = False
    longitude: Annotated[float, Field(strict=True, allow_inf_nan=False, ge=-180, le=180)] | None = None
    latitude: Annotated[float, Field(strict=True, allow_inf_nan=False, ge=-90, le=90)] | None = None


class PostUpdate(StrictRequest):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=5000)
    hazard_type: HazardType | None = None


class CommentCreate(StrictRequest):
    body: str = Field(min_length=1, max_length=2000)
    is_anonymous: bool = False


class CommentUpdate(StrictRequest):
    body: str = Field(min_length=1, max_length=2000)


class VoteRequest(StrictRequest):
    value: VoteValue


class MediaItem(BaseModel):
    id: UUID
    media_type: str
    content_type: str
    byte_size: int


class PostSummary(BaseModel):
    id: UUID
    title: str
    hazard_type: str
    longitude: float | None
    latitude: float | None
    author_id: int | None
    author_email: str | None
    is_anonymous: bool
    is_own: bool
    upvote_count: int
    downvote_count: int
    comment_count: int
    my_vote: VoteValue
    llm_hazard_type_suggested: str | None
    llm_severity: str | None
    duplicate_of_post_id: UUID | None
    duplicate_of_post_title: str | None
    thumbnail_media_id: UUID | None
    created_at: datetime
    updated_at: datetime


class PostDetail(PostSummary):
    body: str
    media: list[MediaItem]


class CommentOut(BaseModel):
    id: UUID
    post_id: UUID
    body: str
    author_id: int | None
    author_email: str | None
    is_anonymous: bool
    is_own: bool
    upvote_count: int
    downvote_count: int
    my_vote: VoteValue
    media: list[MediaItem]
    created_at: datetime
    updated_at: datetime


class PostPage(BaseModel):
    items: list[PostSummary]
    offset: int
    limit: int
    has_more: bool


class CommentPage(BaseModel):
    items: list[CommentOut]
    offset: int
    limit: int
    has_more: bool


class DashboardSummary(BaseModel):
    post_count: int
    comment_count: int
    net_votes_received: int


def _service_unavailable(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=detail,
        headers={"Retry-After": "5"},
    )


def _vote_label(value: int | None) -> VoteValue:
    if value == 1:
        return "up"
    if value == -1:
        return "down"
    return "none"


def _serialize_post(row: Any, viewer_id: int, *, media: list[Any] | None = None) -> dict[str, Any]:
    is_anonymous = row["is_anonymous"]
    is_own = row["author_user_id"] == viewer_id
    fields = {
        "id": row["id"],
        "title": row["title"],
        "hazard_type": row["hazard_type"],
        "longitude": row["longitude"],
        "latitude": row["latitude"],
        "author_id": None if is_anonymous else row["author_user_id"],
        "author_email": None if is_anonymous else row["author_email"],
        "is_anonymous": is_anonymous,
        "is_own": is_own,
        "upvote_count": row["upvote_count"],
        "downvote_count": row["downvote_count"],
        "comment_count": row["comment_count"],
        "my_vote": _vote_label(row["my_vote_value"]),
        "llm_hazard_type_suggested": row["llm_hazard_type_suggested"],
        "llm_severity": row["llm_severity"],
        "duplicate_of_post_id": row["duplicate_of_post_id"],
        "duplicate_of_post_title": (
            row["duplicate_of_post_title"] if "duplicate_of_post_title" in row.keys() else None
        ),
        # When the caller already fetched full media (detail views), derive it from that
        # rather than requiring every list query to also carry a thumbnail_media_id column.
        "thumbnail_media_id": (media[0]["id"] if media else None) if media is not None else row["thumbnail_media_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if "body" in row.keys():
        fields["body"] = row["body"]
        fields["media"] = [dict(item) for item in (media or [])]
    return fields


def _serialize_comment(row: Any, viewer_id: int, *, media: list[Any] | None = None) -> dict[str, Any]:
    is_anonymous = row["is_anonymous"]
    is_own = row["author_user_id"] == viewer_id
    return {
        "id": row["id"],
        "post_id": row["post_id"],
        "body": row["body"],
        "author_id": None if is_anonymous else row["author_user_id"],
        "author_email": None if is_anonymous else row["author_email"],
        "is_anonymous": is_anonymous,
        "is_own": is_own,
        "upvote_count": row["upvote_count"],
        "downvote_count": row["downvote_count"],
        "my_vote": _vote_label(row["my_vote_value"]),
        "media": [dict(item) for item in (media or [])],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def _get_active_post_or_404(connection: AsyncConnection, post_id: UUID) -> Any:
    row = (
        await connection.execute(
            text(
                "SELECT id, author_user_id FROM app.forum_posts WHERE id = :id AND status = 'active'"
            ),
            {"id": post_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    return row


async def _fetch_post_media(connection: AsyncConnection, post_id: UUID) -> list[Any]:
    return (
        await connection.execute(
            text(
                """
                SELECT id, media_type, content_type, byte_size FROM app.forum_post_media
                WHERE post_id = :post_id ORDER BY created_at ASC
                """
            ),
            {"post_id": post_id},
        )
    ).mappings().all()


async def _fetch_comment_media_by_comment(
    connection: AsyncConnection, comment_ids: list[UUID]
) -> dict[UUID, list[Any]]:
    if not comment_ids:
        return {}
    rows = (
        await connection.execute(
            text(
                """
                SELECT id, comment_id, media_type, content_type, byte_size
                FROM app.forum_comment_media
                WHERE comment_id = ANY(:comment_ids) ORDER BY created_at ASC
                """
            ),
            {"comment_ids": comment_ids},
        )
    ).mappings().all()
    grouped: dict[UUID, list[Any]] = {comment_id: [] for comment_id in comment_ids}
    for row in rows:
        grouped[row["comment_id"]].append(row)
    return grouped


@router.post("/posts", response_model=PostDetail, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_trusted_origin)])
async def create_post(
    payload: PostCreate,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    settings = get_settings()
    await enforce_action_rate_limit(
        "forum-post-create",
        request,
        int(user["id"]),
        user_limit=settings.forum_post_user_rate_limit,
        ip_limit=settings.forum_post_ip_rate_limit,
    )
    post_id = uuid4()
    llm_job: dict[str, Any] | None = None
    try:
        async with get_engine().begin() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        INSERT INTO app.forum_posts
                            (id, author_user_id, is_anonymous, hazard_type, title, body,
                             longitude, latitude)
                        VALUES
                            (:id, :author_user_id, :is_anonymous, :hazard_type, :title, :body,
                             :longitude, :latitude)
                        RETURNING id, author_user_id, is_anonymous, hazard_type, title, body,
                                  longitude, latitude, upvote_count, downvote_count,
                                  comment_count, llm_hazard_type_suggested, llm_severity,
                                  duplicate_of_post_id, created_at, updated_at
                        """
                    ),
                    {
                        "id": post_id,
                        "author_user_id": user["id"],
                        "is_anonymous": payload.is_anonymous,
                        "hazard_type": payload.hazard_type,
                        "title": payload.title,
                        "body": payload.body,
                        "longitude": payload.longitude,
                        "latitude": payload.latitude,
                    },
                )
            ).mappings().one()
            llm_job = await create_llm_job(
                connection, kind="triage", subject_post_id=post_id, input_chars=len(payload.body)
            )
    except SQLAlchemyError as exc:
        raise _service_unavailable("The forum service is temporarily unavailable.") from exc
    if llm_job is not None:
        try:
            enqueue_llm_job(llm_job)
        except Exception:
            # Fail-open (PRD decision 6, docs/LLM_FEATURE_PRD.md): the post was already
            # committed successfully. A broker outage at this exact instant must never turn a
            # successful creation into an error response — the job row simply stays 'queued'
            # rather than ever running; classification is enrichment, not load-bearing.
            pass
    return _serialize_post(
        {**row, "author_email": user["email"], "my_vote_value": None}, int(user["id"]), media=[]
    )


@router.get("/posts", response_model=PostPage)
async def list_posts(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    hazard_type: HazardType | None = None,
) -> dict[str, Any]:
    reject_unexpected_query_parameters(request, {"offset", "limit", "hazard_type"})
    viewer_id = int(user["id"])
    try:
        async with get_engine().begin() as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        SELECT p.id, p.author_user_id, u.email AS author_email, p.is_anonymous,
                               p.hazard_type, p.title, p.longitude, p.latitude,
                               p.upvote_count, p.downvote_count, p.comment_count,
                               p.llm_hazard_type_suggested, p.llm_severity, p.duplicate_of_post_id,
                               (
                                   SELECT dp.title FROM app.forum_posts dp
                                   WHERE dp.id = p.duplicate_of_post_id
                               ) AS duplicate_of_post_title,
                               p.created_at, p.updated_at, v.value AS my_vote_value,
                               (
                                   SELECT m.id FROM app.forum_post_media m
                                   WHERE m.post_id = p.id
                                   ORDER BY m.created_at ASC LIMIT 1
                               ) AS thumbnail_media_id
                        FROM app.forum_posts p
                        JOIN app.users u ON u.id = p.author_user_id
                        LEFT JOIN app.forum_votes v
                            ON v.target_type = 'post' AND v.target_id = p.id
                               AND v.user_id = :viewer_id
                        WHERE p.status = 'active'
                          AND (:hazard_type IS NULL OR p.hazard_type = :hazard_type)
                        ORDER BY p.created_at DESC, p.id DESC
                        OFFSET :offset LIMIT :fetch_limit
                        """
                    ).bindparams(bindparam("hazard_type", type_=Text)),
                    {
                        "viewer_id": viewer_id,
                        "hazard_type": hazard_type,
                        "offset": offset,
                        "fetch_limit": limit + 1,
                    },
                )
            ).mappings().all()
    except SQLAlchemyError as exc:
        raise _service_unavailable("The forum feed is temporarily unavailable.") from exc
    items = [_serialize_post(row, viewer_id) for row in rows[:limit]]
    return {"items": items, "offset": offset, "limit": limit, "has_more": len(rows) > limit}


@router.get("/posts/nearby", response_model=PostPage)
async def list_posts_nearby(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    min_lon: Annotated[float, Query(ge=-180, le=180)] = ...,
    min_lat: Annotated[float, Query(ge=-90, le=90)] = ...,
    max_lon: Annotated[float, Query(ge=-180, le=180)] = ...,
    max_lat: Annotated[float, Query(ge=-90, le=90)] = ...,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
) -> dict[str, Any]:
    """Hazard reports within a bounding box — used to alert a driver in live
    navigation to nearby reports without recording their position server-side."""
    reject_unexpected_query_parameters(
        request, {"min_lon", "min_lat", "max_lon", "max_lat", "limit"}
    )
    if min_lon >= max_lon or min_lat >= max_lat:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="bbox bounds must be ordered (min < max)",
        )
    settings = get_settings()
    if (
        max_lon - min_lon > settings.forum_nearby_max_span_degrees
        or max_lat - min_lat > settings.forum_nearby_max_span_degrees
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="bbox span exceeds the supported maximum",
        )
    viewer_id = int(user["id"])
    try:
        async with get_engine().begin() as connection:
            rows = (
                await connection.execute(
                    text(
                        """
                        SELECT p.id, p.author_user_id, u.email AS author_email, p.is_anonymous,
                               p.hazard_type, p.title, p.longitude, p.latitude,
                               p.upvote_count, p.downvote_count, p.comment_count,
                               p.llm_hazard_type_suggested, p.llm_severity, p.duplicate_of_post_id,
                               (
                                   SELECT dp.title FROM app.forum_posts dp
                                   WHERE dp.id = p.duplicate_of_post_id
                               ) AS duplicate_of_post_title,
                               p.created_at, p.updated_at, v.value AS my_vote_value,
                               (
                                   SELECT m.id FROM app.forum_post_media m
                                   WHERE m.post_id = p.id
                                   ORDER BY m.created_at ASC LIMIT 1
                               ) AS thumbnail_media_id
                        FROM app.forum_posts p
                        JOIN app.users u ON u.id = p.author_user_id
                        LEFT JOIN app.forum_votes v
                            ON v.target_type = 'post' AND v.target_id = p.id
                               AND v.user_id = :viewer_id
                        WHERE p.status = 'active'
                          AND p.longitude BETWEEN :min_lon AND :max_lon
                          AND p.latitude BETWEEN :min_lat AND :max_lat
                        ORDER BY p.created_at DESC, p.id DESC
                        LIMIT :fetch_limit
                        """
                    ),
                    {
                        "viewer_id": viewer_id,
                        "min_lon": min_lon,
                        "max_lon": max_lon,
                        "min_lat": min_lat,
                        "max_lat": max_lat,
                        "fetch_limit": limit,
                    },
                )
            ).mappings().all()
    except SQLAlchemyError as exc:
        raise _service_unavailable("The forum feed is temporarily unavailable.") from exc
    items = [_serialize_post(row, viewer_id) for row in rows]
    return {"items": items, "offset": 0, "limit": limit, "has_more": False}


@router.get("/posts/{post_id}", response_model=PostDetail)
async def get_post(
    post_id: UUID,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    reject_unexpected_query_parameters(request, set())
    viewer_id = int(user["id"])
    try:
        async with get_engine().begin() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT p.id, p.author_user_id, u.email AS author_email, p.is_anonymous,
                               p.hazard_type, p.title, p.body, p.longitude, p.latitude,
                               p.upvote_count, p.downvote_count, p.comment_count,
                               p.llm_hazard_type_suggested, p.llm_severity, p.duplicate_of_post_id,
                               (
                                   SELECT dp.title FROM app.forum_posts dp
                                   WHERE dp.id = p.duplicate_of_post_id
                               ) AS duplicate_of_post_title,
                               p.created_at, p.updated_at, v.value AS my_vote_value
                        FROM app.forum_posts p
                        JOIN app.users u ON u.id = p.author_user_id
                        LEFT JOIN app.forum_votes v
                            ON v.target_type = 'post' AND v.target_id = p.id
                               AND v.user_id = :viewer_id
                        WHERE p.id = :id AND p.status = 'active'
                        """
                    ),
                    {"id": post_id, "viewer_id": viewer_id},
                )
            ).mappings().first()
            if row is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
            media = await _fetch_post_media(connection, post_id)
    except SQLAlchemyError as exc:
        raise _service_unavailable("The forum service is temporarily unavailable.") from exc
    return _serialize_post(row, viewer_id, media=media)


@router.patch("/posts/{post_id}", response_model=PostDetail, dependencies=[Depends(require_trusted_origin)])
async def update_post(
    post_id: UUID,
    payload: PostUpdate,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    updates = payload.model_dump(exclude_unset=True)
    viewer_id = int(user["id"])
    try:
        async with get_engine().begin() as connection:
            owned = (
                await connection.execute(
                    text(
                        "SELECT id FROM app.forum_posts WHERE id = :id AND author_user_id = :author_user_id AND status = 'active'"
                    ),
                    {"id": post_id, "author_user_id": viewer_id},
                )
            ).mappings().first()
            if owned is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
            if updates:
                set_clause = ", ".join(f"{key} = :{key}" for key in updates)
                await connection.execute(
                    text(f"UPDATE app.forum_posts SET {set_clause}, updated_at = now() WHERE id = :id"),
                    {**updates, "id": post_id},
                )
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT p.id, p.author_user_id, u.email AS author_email, p.is_anonymous,
                               p.hazard_type, p.title, p.body, p.longitude, p.latitude,
                               p.upvote_count, p.downvote_count, p.comment_count,
                               p.llm_hazard_type_suggested, p.llm_severity, p.duplicate_of_post_id,
                               (
                                   SELECT dp.title FROM app.forum_posts dp
                                   WHERE dp.id = p.duplicate_of_post_id
                               ) AS duplicate_of_post_title,
                               p.created_at, p.updated_at, v.value AS my_vote_value
                        FROM app.forum_posts p
                        JOIN app.users u ON u.id = p.author_user_id
                        LEFT JOIN app.forum_votes v
                            ON v.target_type = 'post' AND v.target_id = p.id
                               AND v.user_id = :viewer_id
                        WHERE p.id = :id
                        """
                    ),
                    {"id": post_id, "viewer_id": viewer_id},
                )
            ).mappings().one()
            media = await _fetch_post_media(connection, post_id)
    except SQLAlchemyError as exc:
        raise _service_unavailable("The forum service is temporarily unavailable.") from exc
    return _serialize_post(row, viewer_id, media=media)


@router.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_trusted_origin)])
async def delete_post(
    post_id: UUID,
    user: dict[str, Any] = Depends(get_current_user),
) -> Response:
    try:
        async with get_engine().begin() as connection:
            updated = await connection.execute(
                text(
                    """
                    UPDATE app.forum_posts SET status = 'removed', updated_at = now()
                    WHERE id = :id AND author_user_id = :author_user_id AND status = 'active'
                    """
                ),
                {"id": post_id, "author_user_id": user["id"]},
            )
    except SQLAlchemyError as exc:
        raise _service_unavailable("The forum service is temporarily unavailable.") from exc
    if updated.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/posts/{post_id}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_trusted_origin)],
)
async def create_comment(
    post_id: UUID,
    payload: CommentCreate,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    settings = get_settings()
    await enforce_action_rate_limit(
        "forum-comment-create",
        request,
        int(user["id"]),
        user_limit=settings.forum_comment_user_rate_limit,
        ip_limit=settings.forum_comment_ip_rate_limit,
    )
    comment_id = uuid4()
    notification = None
    try:
        async with get_engine().begin() as connection:
            post = await _get_active_post_or_404(connection, post_id)
            row = (
                await connection.execute(
                    text(
                        """
                        INSERT INTO app.forum_comments (id, post_id, author_user_id, is_anonymous, body)
                        VALUES (:id, :post_id, :author_user_id, :is_anonymous, :body)
                        RETURNING id, post_id, author_user_id, is_anonymous, body,
                                  upvote_count, downvote_count, created_at, updated_at
                        """
                    ),
                    {
                        "id": comment_id,
                        "post_id": post_id,
                        "author_user_id": user["id"],
                        "is_anonymous": payload.is_anonymous,
                        "body": payload.body,
                    },
                )
            ).mappings().one()
            await connection.execute(
                text(
                    "UPDATE app.forum_posts SET comment_count = comment_count + 1, updated_at = now() WHERE id = :id"
                ),
                {"id": post_id},
            )
            notification = await create_notification(
                connection,
                recipient_user_id=int(post["author_user_id"]),
                actor_user_id=int(user["id"]),
                kind="new_comment",
                payload={
                    "post_id": str(post_id),
                    "comment_id": str(comment_id),
                    "actor_label": None if payload.is_anonymous else user["email"],
                },
            )
    except SQLAlchemyError as exc:
        raise _service_unavailable("The forum service is temporarily unavailable.") from exc
    await publish_notification(get_redis(), notification)
    return _serialize_comment(
        {**row, "author_email": user["email"], "my_vote_value": None}, int(user["id"])
    )


@router.get("/posts/{post_id}/comments", response_model=CommentPage)
async def list_comments(
    post_id: UUID,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> dict[str, Any]:
    reject_unexpected_query_parameters(request, {"offset", "limit"})
    viewer_id = int(user["id"])
    try:
        async with get_engine().begin() as connection:
            await _get_active_post_or_404(connection, post_id)
            rows = (
                await connection.execute(
                    text(
                        """
                        SELECT c.id, c.post_id, c.author_user_id, u.email AS author_email,
                               c.is_anonymous, c.body, c.upvote_count, c.downvote_count,
                               c.created_at, c.updated_at, v.value AS my_vote_value
                        FROM app.forum_comments c
                        JOIN app.users u ON u.id = c.author_user_id
                        LEFT JOIN app.forum_votes v
                            ON v.target_type = 'comment' AND v.target_id = c.id
                               AND v.user_id = :viewer_id
                        WHERE c.post_id = :post_id AND c.status = 'active'
                        ORDER BY c.created_at ASC, c.id ASC
                        OFFSET :offset LIMIT :fetch_limit
                        """
                    ),
                    {
                        "post_id": post_id,
                        "viewer_id": viewer_id,
                        "offset": offset,
                        "fetch_limit": limit + 1,
                    },
                )
            ).mappings().all()
            page_rows = rows[:limit]
            media_by_comment = await _fetch_comment_media_by_comment(
                connection, [row["id"] for row in page_rows]
            )
    except SQLAlchemyError as exc:
        raise _service_unavailable("The forum service is temporarily unavailable.") from exc
    items = [
        _serialize_comment(row, viewer_id, media=media_by_comment.get(row["id"], []))
        for row in page_rows
    ]
    return {"items": items, "offset": offset, "limit": limit, "has_more": len(rows) > limit}


@router.patch("/comments/{comment_id}", response_model=CommentOut, dependencies=[Depends(require_trusted_origin)])
async def update_comment(
    comment_id: UUID,
    payload: CommentUpdate,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    viewer_id = int(user["id"])
    try:
        async with get_engine().begin() as connection:
            owned = (
                await connection.execute(
                    text(
                        "SELECT id FROM app.forum_comments WHERE id = :id AND author_user_id = :author_user_id AND status = 'active'"
                    ),
                    {"id": comment_id, "author_user_id": viewer_id},
                )
            ).mappings().first()
            if owned is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found.")
            await connection.execute(
                text("UPDATE app.forum_comments SET body = :body, updated_at = now() WHERE id = :id"),
                {"body": payload.body, "id": comment_id},
            )
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT c.id, c.post_id, c.author_user_id, u.email AS author_email,
                               c.is_anonymous, c.body, c.upvote_count, c.downvote_count,
                               c.created_at, c.updated_at, v.value AS my_vote_value
                        FROM app.forum_comments c
                        JOIN app.users u ON u.id = c.author_user_id
                        LEFT JOIN app.forum_votes v
                            ON v.target_type = 'comment' AND v.target_id = c.id
                               AND v.user_id = :viewer_id
                        WHERE c.id = :id
                        """
                    ),
                    {"id": comment_id, "viewer_id": viewer_id},
                )
            ).mappings().one()
            media = await _fetch_comment_media_by_comment(connection, [comment_id])
    except SQLAlchemyError as exc:
        raise _service_unavailable("The forum service is temporarily unavailable.") from exc
    return _serialize_comment(row, viewer_id, media=media.get(comment_id, []))


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_trusted_origin)])
async def delete_comment(
    comment_id: UUID,
    user: dict[str, Any] = Depends(get_current_user),
) -> Response:
    try:
        async with get_engine().begin() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        UPDATE app.forum_comments SET status = 'removed', updated_at = now()
                        WHERE id = :id AND author_user_id = :author_user_id AND status = 'active'
                        RETURNING post_id
                        """
                    ),
                    {"id": comment_id, "author_user_id": user["id"]},
                )
            ).mappings().first()
            if row is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found.")
            await connection.execute(
                text(
                    "UPDATE app.forum_posts SET comment_count = GREATEST(comment_count - 1, 0), updated_at = now() WHERE id = :id"
                ),
                {"id": row["post_id"]},
            )
    except SQLAlchemyError as exc:
        raise _service_unavailable("The forum service is temporarily unavailable.") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _apply_vote(
    connection: AsyncConnection,
    *,
    target_type: Literal["post", "comment"],
    target_id: UUID,
    user_id: int,
    requested: VoteValue,
) -> bool:
    """Apply the vote and return whether it newly set an up/down vote (not clearing one), so
    callers can decide whether this is worth a notification."""
    table = "forum_posts" if target_type == "post" else "forum_comments"
    # A row-level lock only works once a forum_votes row exists. An advisory lock also
    # serializes the first vote from the same user on the same target, so two concurrent
    # requests can never both read "no existing vote" and double-apply a counter delta.
    await connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": f"forum-vote:{target_type}:{target_id}:{user_id}"},
    )
    existing = (
        await connection.execute(
            text(
                """
                SELECT value FROM app.forum_votes
                WHERE user_id = :user_id AND target_type = :target_type AND target_id = :target_id
                FOR UPDATE
                """
            ),
            {"user_id": user_id, "target_type": target_type, "target_id": target_id},
        )
    ).scalar_one_or_none()
    new_value = _VOTE_TO_INT[requested]
    if new_value == 0:
        if existing is not None:
            await connection.execute(
                text(
                    """
                    DELETE FROM app.forum_votes
                    WHERE user_id = :user_id AND target_type = :target_type AND target_id = :target_id
                    """
                ),
                {"user_id": user_id, "target_type": target_type, "target_id": target_id},
            )
    else:
        await connection.execute(
            text(
                """
                INSERT INTO app.forum_votes (user_id, target_type, target_id, value)
                VALUES (:user_id, :target_type, :target_id, :value)
                ON CONFLICT (user_id, target_type, target_id)
                DO UPDATE SET value = EXCLUDED.value
                """
            ),
            {"user_id": user_id, "target_type": target_type, "target_id": target_id, "value": new_value},
        )
    upvote_delta = (1 if new_value == 1 else 0) - (1 if existing == 1 else 0)
    downvote_delta = (1 if new_value == -1 else 0) - (1 if existing == -1 else 0)
    if upvote_delta or downvote_delta:
        await connection.execute(
            text(
                f"""
                UPDATE app.{table}
                SET upvote_count = upvote_count + :upvote_delta,
                    downvote_count = downvote_count + :downvote_delta
                WHERE id = :id
                """
            ),
            {"upvote_delta": upvote_delta, "downvote_delta": downvote_delta, "id": target_id},
        )
    return new_value != 0 and new_value != existing


@router.put("/posts/{post_id}/vote", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_trusted_origin)])
async def vote_on_post(
    post_id: UUID,
    payload: VoteRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> Response:
    settings = get_settings()
    await enforce_action_rate_limit(
        "forum-vote",
        request,
        int(user["id"]),
        user_limit=settings.forum_vote_user_rate_limit,
        ip_limit=settings.forum_vote_ip_rate_limit,
    )
    notification = None
    try:
        async with get_engine().begin() as connection:
            post = await _get_active_post_or_404(connection, post_id)
            voted = await _apply_vote(
                connection,
                target_type="post",
                target_id=post_id,
                user_id=int(user["id"]),
                requested=payload.value,
            )
            if voted:
                notification = await create_notification(
                    connection,
                    recipient_user_id=int(post["author_user_id"]),
                    actor_user_id=int(user["id"]),
                    kind="new_vote",
                    payload={"target_type": "post", "post_id": str(post_id), "value": payload.value},
                )
    except SQLAlchemyError as exc:
        raise _service_unavailable("The forum service is temporarily unavailable.") from exc
    await publish_notification(get_redis(), notification)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/comments/{comment_id}/vote", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_trusted_origin)])
async def vote_on_comment(
    comment_id: UUID,
    payload: VoteRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> Response:
    settings = get_settings()
    await enforce_action_rate_limit(
        "forum-vote",
        request,
        int(user["id"]),
        user_limit=settings.forum_vote_user_rate_limit,
        ip_limit=settings.forum_vote_ip_rate_limit,
    )
    notification = None
    try:
        async with get_engine().begin() as connection:
            comment_row = (
                await connection.execute(
                    text(
                        "SELECT id, author_user_id, post_id FROM app.forum_comments WHERE id = :id AND status = 'active'"
                    ),
                    {"id": comment_id},
                )
            ).mappings().first()
            if comment_row is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found.")
            voted = await _apply_vote(
                connection,
                target_type="comment",
                target_id=comment_id,
                user_id=int(user["id"]),
                requested=payload.value,
            )
            if voted:
                notification = await create_notification(
                    connection,
                    recipient_user_id=int(comment_row["author_user_id"]),
                    actor_user_id=int(user["id"]),
                    kind="new_vote",
                    payload={
                        "target_type": "comment",
                        "comment_id": str(comment_id),
                        "post_id": str(comment_row["post_id"]),
                        "value": payload.value,
                    },
                )
    except SQLAlchemyError as exc:
        raise _service_unavailable("The forum service is temporarily unavailable.") from exc
    await publish_notification(get_redis(), notification)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me/dashboard", response_model=DashboardSummary)
async def get_my_dashboard(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    try:
        async with get_engine().begin() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            (SELECT COUNT(*) FROM app.forum_posts
                             WHERE author_user_id = :user_id AND status = 'active') AS post_count,
                            (SELECT COUNT(*) FROM app.forum_comments
                             WHERE author_user_id = :user_id AND status = 'active') AS comment_count,
                            (SELECT COALESCE(SUM(upvote_count - downvote_count), 0)
                             FROM app.forum_posts
                             WHERE author_user_id = :user_id AND status = 'active')
                            +
                            (SELECT COALESCE(SUM(upvote_count - downvote_count), 0)
                             FROM app.forum_comments
                             WHERE author_user_id = :user_id AND status = 'active')
                            AS net_votes_received
                        """
                    ),
                    {"user_id": user["id"]},
                )
            ).mappings().one()
    except SQLAlchemyError as exc:
        raise _service_unavailable("The forum service is temporarily unavailable.") from exc
    return dict(row)


def _normalized_content_type(upload: UploadFile) -> str:
    return (upload.content_type or "").split(";")[0].strip().lower()


@router.post(
    "/posts/{post_id}/media",
    response_model=MediaItem,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_trusted_origin)],
)
async def upload_post_media(
    post_id: UUID,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    settings = get_settings()
    await enforce_action_rate_limit(
        "forum-media-upload",
        request,
        int(user["id"]),
        user_limit=settings.forum_media_upload_user_rate_limit,
        ip_limit=settings.forum_media_upload_ip_rate_limit,
    )
    data = await file.read()
    content_type = _normalized_content_type(file)
    media_type = classify_and_validate_media(content_type, len(data), settings)
    media_id = uuid4()
    try:
        async with get_engine().begin() as connection:
            owned = (
                await connection.execute(
                    text(
                        "SELECT id FROM app.forum_posts WHERE id = :id AND author_user_id = :author_user_id AND status = 'active'"
                    ),
                    {"id": post_id, "author_user_id": user["id"]},
                )
            ).mappings().first()
            if owned is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
            existing_count = (
                await connection.execute(
                    text("SELECT COUNT(*) FROM app.forum_post_media WHERE post_id = :post_id"),
                    {"post_id": post_id},
                )
            ).scalar_one()
            if existing_count >= settings.forum_media_max_items_per_post:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="This post already has the maximum number of media attachments.",
                )
            storage_key = await asyncio.to_thread(write_media_file, settings, data)
            row = (
                await connection.execute(
                    text(
                        """
                        INSERT INTO app.forum_post_media
                            (id, post_id, media_type, storage_key, content_type, byte_size)
                        VALUES (:id, :post_id, :media_type, :storage_key, :content_type, :byte_size)
                        RETURNING id, media_type, content_type, byte_size
                        """
                    ),
                    {
                        "id": media_id,
                        "post_id": post_id,
                        "media_type": media_type,
                        "storage_key": storage_key,
                        "content_type": content_type,
                        "byte_size": len(data),
                    },
                )
            ).mappings().one()
    except SQLAlchemyError as exc:
        raise _service_unavailable("The forum media service is temporarily unavailable.") from exc
    return dict(row)


@router.post(
    "/comments/{comment_id}/media",
    response_model=MediaItem,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_trusted_origin)],
)
async def upload_comment_media(
    comment_id: UUID,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    settings = get_settings()
    await enforce_action_rate_limit(
        "forum-media-upload",
        request,
        int(user["id"]),
        user_limit=settings.forum_media_upload_user_rate_limit,
        ip_limit=settings.forum_media_upload_ip_rate_limit,
    )
    data = await file.read()
    content_type = _normalized_content_type(file)
    media_type = classify_and_validate_media(content_type, len(data), settings)
    media_id = uuid4()
    try:
        async with get_engine().begin() as connection:
            owned = (
                await connection.execute(
                    text(
                        "SELECT id FROM app.forum_comments WHERE id = :id AND author_user_id = :author_user_id AND status = 'active'"
                    ),
                    {"id": comment_id, "author_user_id": user["id"]},
                )
            ).mappings().first()
            if owned is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found.")
            existing_count = (
                await connection.execute(
                    text("SELECT COUNT(*) FROM app.forum_comment_media WHERE comment_id = :comment_id"),
                    {"comment_id": comment_id},
                )
            ).scalar_one()
            if existing_count >= settings.forum_media_max_items_per_comment:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="This comment already has the maximum number of media attachments.",
                )
            storage_key = await asyncio.to_thread(write_media_file, settings, data)
            row = (
                await connection.execute(
                    text(
                        """
                        INSERT INTO app.forum_comment_media
                            (id, comment_id, media_type, storage_key, content_type, byte_size)
                        VALUES (:id, :comment_id, :media_type, :storage_key, :content_type, :byte_size)
                        RETURNING id, media_type, content_type, byte_size
                        """
                    ),
                    {
                        "id": media_id,
                        "comment_id": comment_id,
                        "media_type": media_type,
                        "storage_key": storage_key,
                        "content_type": content_type,
                        "byte_size": len(data),
                    },
                )
            ).mappings().one()
    except SQLAlchemyError as exc:
        raise _service_unavailable("The forum media service is temporarily unavailable.") from exc
    return dict(row)


@router.get("/media/{media_id}")
async def get_media(media_id: UUID, user: dict[str, Any] = Depends(get_current_user)) -> Response:
    settings = get_settings()
    viewer_id = int(user["id"])
    try:
        async with get_engine().begin() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT pm.storage_key, pm.content_type
                        FROM app.forum_post_media pm
                        JOIN app.forum_posts p ON p.id = pm.post_id
                        WHERE pm.id = :id AND p.status = 'active'
                        UNION ALL
                        SELECT cm.storage_key, cm.content_type
                        FROM app.forum_comment_media cm
                        JOIN app.forum_comments c ON c.id = cm.comment_id
                        JOIN app.forum_posts p ON p.id = c.post_id
                        WHERE cm.id = :id AND c.status = 'active' AND p.status = 'active'
                        UNION ALL
                        SELECT dmm.storage_key, dmm.content_type
                        FROM app.direct_message_media dmm
                        JOIN app.direct_messages dm ON dm.id = dmm.message_id
                        WHERE dmm.id = :id
                              AND (dm.sender_user_id = :viewer_id OR dm.recipient_user_id = :viewer_id)
                        """
                    ),
                    {"id": media_id, "viewer_id": viewer_id},
                )
            ).mappings().first()
    except SQLAlchemyError as exc:
        raise _service_unavailable("The forum media service is temporarily unavailable.") from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found.")
    data = await asyncio.to_thread(read_media_file, settings, row["storage_key"])
    return Response(content=data, media_type=row["content_type"])
