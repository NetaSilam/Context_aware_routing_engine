from __future__ import annotations

from app.notifications.service import notification_channel


def test_notification_channel_is_scoped_per_recipient() -> None:
    assert notification_channel(42) == "forum-notifications:42"
    assert notification_channel(1) != notification_channel(2)
