from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException, status

from app.config import Settings


def _content_type_to_media_type_map(settings: Settings) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for content_type in settings.forum_media_allowed_image_content_types.split(","):
        mapping[content_type.strip()] = "image"
    for content_type in settings.forum_media_allowed_video_content_types.split(","):
        mapping[content_type.strip()] = "video"
    return mapping


def classify_and_validate_media(
    content_type: str | None, byte_size: int, settings: Settings
) -> str:
    """Return "image"/"video" for an allowed upload, or raise a controlled HTTP error."""
    mapping = _content_type_to_media_type_map(settings)
    normalized = (content_type or "").split(";")[0].strip().lower()
    media_type = mapping.get(normalized)
    if media_type is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported media content type: {normalized or 'unknown'}.",
        )
    if byte_size <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Uploaded file is empty."
        )
    limit = (
        settings.forum_media_max_image_bytes
        if media_type == "image"
        else settings.forum_media_max_video_bytes
    )
    if byte_size > limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"{media_type.capitalize()} uploads must be at most {limit} bytes.",
        )
    return media_type


def write_media_file(settings: Settings, data: bytes) -> str:
    settings.forum_media_storage_path.mkdir(parents=True, exist_ok=True)
    storage_key = uuid4().hex
    (settings.forum_media_storage_path / storage_key).write_bytes(data)
    return storage_key


def read_media_file(settings: Settings, storage_key: str) -> bytes:
    path = settings.forum_media_storage_path / storage_key
    try:
        return path.read_bytes()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Media file not found."
        ) from exc
