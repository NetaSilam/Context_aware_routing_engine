from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.forum.routes import PostCreate, VoteRequest, _serialize_comment, _serialize_post, _vote_label


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1, "up"), (-1, "down"), (None, "none")],
)
def test_vote_label_maps_stored_integer_to_public_value(value: int | None, expected: str) -> None:
    assert _vote_label(value) == expected


def test_post_create_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        PostCreate(
            title="Pothole",
            body="Deep pothole after the junction.",
            hazard_type="pothole",
            unexpected_field=True,
        )


def test_post_create_rejects_invalid_hazard_type() -> None:
    with pytest.raises(ValidationError):
        PostCreate(title="x", body="y", hazard_type="not-a-real-type")


def test_vote_request_only_accepts_up_down_none() -> None:
    with pytest.raises(ValidationError):
        VoteRequest(value="upvote")
    assert VoteRequest(value="up").value == "up"


def _post_row(**overrides: object) -> dict:
    base = {
        "id": uuid4(),
        "author_user_id": 1,
        "author_email": "reporter@example.com",
        "is_anonymous": False,
        "hazard_type": "pothole",
        "title": "Deep pothole",
        "longitude": None,
        "latitude": None,
        "upvote_count": 0,
        "downvote_count": 0,
        "comment_count": 0,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "my_vote_value": None,
    }
    base.update(overrides)
    return base


def test_serialize_post_hides_author_identity_when_anonymous() -> None:
    row = _post_row(is_anonymous=True, author_user_id=7)
    other_viewer = _serialize_post(row, viewer_id=99)
    author_viewer = _serialize_post(row, viewer_id=7)

    assert other_viewer["author_id"] is None
    assert other_viewer["author_email"] is None
    assert other_viewer["is_own"] is False

    assert author_viewer["author_id"] is None
    assert author_viewer["author_email"] is None
    assert author_viewer["is_own"] is True


def test_serialize_post_reveals_author_identity_when_not_anonymous() -> None:
    row = _post_row(is_anonymous=False, author_user_id=7, author_email="reporter@example.com")
    viewer = _serialize_post(row, viewer_id=99)

    assert viewer["author_id"] == 7
    assert viewer["author_email"] == "reporter@example.com"
    assert viewer["is_own"] is False


def test_serialize_post_omits_body_for_summary_rows_but_includes_it_when_present() -> None:
    summary_row = _post_row()
    detail_row = _post_row(body="Full report text.")

    assert "body" not in _serialize_post(summary_row, viewer_id=1)
    assert _serialize_post(detail_row, viewer_id=1)["body"] == "Full report text."


def test_serialize_comment_hides_author_identity_when_anonymous() -> None:
    row = {
        "id": uuid4(),
        "post_id": uuid4(),
        "author_user_id": 3,
        "author_email": "commenter@example.com",
        "is_anonymous": True,
        "body": "Still there.",
        "upvote_count": 0,
        "downvote_count": 0,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "my_vote_value": 1,
    }
    other_viewer = _serialize_comment(row, viewer_id=1)
    assert other_viewer["author_id"] is None
    assert other_viewer["author_email"] is None
    assert other_viewer["my_vote"] == "up"
