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
        "llm_hazard_type_suggested": None,
        "llm_severity": None,
        "duplicate_of_post_id": None,
        "thumbnail_media_id": None,
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


def test_serialize_post_includes_llm_classification_fields() -> None:
    unclassified = _serialize_post(_post_row(), viewer_id=1)
    assert unclassified["llm_hazard_type_suggested"] is None
    assert unclassified["llm_severity"] is None
    assert unclassified["duplicate_of_post_id"] is None

    duplicate_id = uuid4()
    classified = _serialize_post(
        _post_row(
            llm_hazard_type_suggested="flooding",
            llm_severity="high",
            duplicate_of_post_id=duplicate_id,
        ),
        viewer_id=1,
    )
    assert classified["llm_hazard_type_suggested"] == "flooding"
    assert classified["llm_severity"] == "high"
    assert classified["duplicate_of_post_id"] == duplicate_id


def test_serialize_post_derives_thumbnail_media_id_from_the_row_or_the_media_list() -> None:
    # List-style rows (no media= passed) rely on the SQL query's own thumbnail_media_id column.
    assert _serialize_post(_post_row(thumbnail_media_id=None), viewer_id=1)["thumbnail_media_id"] is None
    media_id = uuid4()
    assert _serialize_post(_post_row(thumbnail_media_id=media_id), viewer_id=1)["thumbnail_media_id"] == media_id

    # Detail-style calls (media= passed) derive it from the fetched media list's first item
    # instead, regardless of whatever the row itself happens to carry.
    row = _post_row(thumbnail_media_id=None)
    assert _serialize_post(row, viewer_id=1, media=[])["thumbnail_media_id"] is None
    first_media_id = uuid4()
    media = [{"id": first_media_id}, {"id": uuid4()}]
    assert _serialize_post(row, viewer_id=1, media=media)["thumbnail_media_id"] == first_media_id


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
