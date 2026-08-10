from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.forum.media_storage import classify_and_validate_media, read_media_file, write_media_file

VALID_SETTINGS = {
    "database_url": "postgresql+psycopg://road_user:secret@postgres:5432/road_risk",
    "redis_url": "redis://redis:6379/0",
    "foundation_data_version": "fixture-v1",
    "jwt_secret": "test-secret-with-at-least-32-characters",
    "auth_allowed_origin": "http://localhost:5173",
    "osrm_base_url": "http://osrm:5000/",
    "geocoder_base_url": "http://geocoder:5001/search",
    "geocoder_user_agent": "road-risk-project/1.0",
}


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(**{**VALID_SETTINGS, "forum_media_storage_path": tmp_path, **overrides})


def test_classify_and_validate_media_accepts_allowed_image(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert classify_and_validate_media("image/jpeg", 1024, settings) == "image"


def test_classify_and_validate_media_accepts_allowed_video(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert classify_and_validate_media("video/mp4", 1024, settings) == "video"


def test_classify_and_validate_media_parses_content_type_parameters(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert classify_and_validate_media("image/png; charset=binary", 1024, settings) == "image"


def test_classify_and_validate_media_rejects_unsupported_content_type(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        classify_and_validate_media("application/pdf", 1024, settings)
    assert exc_info.value.status_code == 422


def test_classify_and_validate_media_rejects_missing_content_type(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        classify_and_validate_media(None, 1024, settings)
    assert exc_info.value.status_code == 422


def test_classify_and_validate_media_rejects_empty_upload(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        classify_and_validate_media("image/jpeg", 0, settings)
    assert exc_info.value.status_code == 422


def test_classify_and_validate_media_rejects_oversized_image(tmp_path: Path) -> None:
    settings = _settings(tmp_path, forum_media_max_image_bytes=1024)
    with pytest.raises(HTTPException) as exc_info:
        classify_and_validate_media("image/jpeg", 2048, settings)
    assert exc_info.value.status_code == 413


def test_classify_and_validate_media_rejects_oversized_video(tmp_path: Path) -> None:
    settings = _settings(tmp_path, forum_media_max_video_bytes=1024)
    with pytest.raises(HTTPException) as exc_info:
        classify_and_validate_media("video/mp4", 2048, settings)
    assert exc_info.value.status_code == 413


def test_classify_and_validate_media_applies_the_image_limit_not_the_video_limit(
    tmp_path: Path,
) -> None:
    settings = _settings(
        tmp_path, forum_media_max_image_bytes=1024, forum_media_max_video_bytes=10_000_000
    )
    # A video-sized payload must not slip through under an image content type.
    with pytest.raises(HTTPException) as exc_info:
        classify_and_validate_media("image/jpeg", 5000, settings)
    assert exc_info.value.status_code == 413


def test_write_and_read_media_file_round_trip(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    storage_key = write_media_file(settings, b"fake-image-bytes")
    assert read_media_file(settings, storage_key) == b"fake-image-bytes"


def test_write_media_file_generates_distinct_keys_for_repeated_uploads(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    first_key = write_media_file(settings, b"one")
    second_key = write_media_file(settings, b"two")
    assert first_key != second_key


def test_read_media_file_missing_key_raises_404(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        read_media_file(settings, "does-not-exist")
    assert exc_info.value.status_code == 404
