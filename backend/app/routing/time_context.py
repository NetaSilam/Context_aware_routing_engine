from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

ISRAEL_TIME_ZONE = ZoneInfo("Asia/Jerusalem")
TIME_CONTEXT_RULE_VERSION = "israel-day-night-v1"


@dataclass(frozen=True)
class IsraelTimeContext:
    local_timestamp: datetime
    period: Literal["day", "night"]
    rule_version: str = TIME_CONTEXT_RULE_VERSION

    @property
    def is_night(self) -> bool:
        return self.period == "night"


def get_israel_time_context(submitted_at: datetime) -> IsraelTimeContext:
    """Snapshot the submission time using Israel's real daylight-saving rules."""
    if submitted_at.tzinfo is None or submitted_at.utcoffset() is None:
        raise ValueError("submitted_at must include a UTC offset")

    local_timestamp = submitted_at.astimezone(ISRAEL_TIME_ZONE)
    period: Literal["day", "night"] = (
        "day" if 6 <= local_timestamp.hour <= 18 else "night"
    )
    return IsraelTimeContext(local_timestamp=local_timestamp, period=period)
