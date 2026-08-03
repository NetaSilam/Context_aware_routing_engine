from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from typing import Any

_SENSITIVE_FIELDS = {
    "address",
    "coordinates",
    "destination_latitude",
    "destination_longitude",
    "origin_latitude",
    "origin_longitude",
    "password",
    "token",
}


class PrivacySafeJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname.lower(),
            "message": record.getMessage(),
            "logger": record.name,
        }
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in {
                "args", "created", "exc_info", "exc_text", "filename", "funcName",
                "levelname", "levelno", "lineno", "message", "module", "msecs",
                "msg", "name", "pathname", "process", "processName", "relativeCreated",
                "stack_info", "thread", "threadName",
            }:
                continue
            payload[key] = "[redacted]" if key in _SENSITIVE_FIELDS else value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_structured_logging() -> None:
    root = logging.getLogger()
    handler = logging.StreamHandler()
    handler.setFormatter(PrivacySafeJsonFormatter())
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    # Request URLs can contain address-search text or coordinates. Those libraries
    # are operationally useful at warning level without retaining request payloads.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def log_route_event(
    event: str,
    *,
    job_id: str | None = None,
    stage: str,
    attempt: int | None = None,
    duration_ms: float | None = None,
    error_code: str | None = None,
    queue_capacity: int | None = None,
    level: int = logging.INFO,
) -> None:
    logging.getLogger("app.operations").log(
        level,
        event,
        extra={
            "event": event,
            "job_id": job_id,
            "stage": stage,
            "attempt": attempt,
            "duration_ms": round(duration_ms, 2) if duration_ms is not None else None,
            "error_code": error_code,
            "queue_capacity": queue_capacity,
        },
    )


class BoundedOperationsMetrics:
    """In-process counters with no user, route, or job-id label cardinality."""

    def __init__(self) -> None:
        self.started_at = time.monotonic()
        self.upstream_failures = 0

    def record_upstream_failure(self) -> None:
        self.upstream_failures += 1

    def snapshot(self, *, queue_depth: int, queue_capacity: int) -> dict[str, int | float]:
        return {
            "uptime_seconds": round(time.monotonic() - self.started_at, 3),
            "upstream_failures": self.upstream_failures,
            "queue_depth": queue_depth,
            "queue_capacity": queue_capacity,
        }


operations_metrics = BoundedOperationsMetrics()
