from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.messaging.routes import _serialize_conversation_message_row, _serialize_message


def _message_row(**overrides: object) -> dict:
    base = {
        "id": uuid4(),
        "sender_user_id": 1,
        "recipient_user_id": 2,
        "body": "hello",
        "created_at": datetime.now(timezone.utc),
        "read_at": None,
    }
    base.update(overrides)
    return base


def test_serialize_message_includes_sender_and_recipient_email() -> None:
    row = _message_row()
    result = _serialize_message(
        row, sender_email="a@example.com", recipient_email="b@example.com", media=None
    )
    assert result["sender_email"] == "a@example.com"
    assert result["recipient_email"] == "b@example.com"
    assert result["media"] is None


def test_serialize_message_includes_media_dict_when_present() -> None:
    row = _message_row()
    media = {"id": uuid4(), "media_type": "image", "content_type": "image/jpeg", "byte_size": 10}
    result = _serialize_message(
        row, sender_email="a@example.com", recipient_email="b@example.com", media=media
    )
    assert result["media"]["media_type"] == "image"


def test_serialize_conversation_message_row_omits_media_when_no_attachment() -> None:
    row = {
        **_message_row(),
        "sender_email": "a@example.com",
        "recipient_email": "b@example.com",
        "media_id": None,
        "media_type": None,
        "content_type": None,
        "byte_size": None,
    }
    result = _serialize_conversation_message_row(row)
    assert result["media"] is None


def test_serialize_conversation_message_row_includes_media_when_present() -> None:
    row = {
        **_message_row(),
        "sender_email": "a@example.com",
        "recipient_email": "b@example.com",
        "media_id": uuid4(),
        "media_type": "video",
        "content_type": "video/mp4",
        "byte_size": 2048,
    }
    result = _serialize_conversation_message_row(row)
    assert result["media"] == {
        "id": row["media_id"],
        "media_type": "video",
        "content_type": "video/mp4",
        "byte_size": 2048,
    }
