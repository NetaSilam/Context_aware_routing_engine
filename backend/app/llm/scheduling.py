from __future__ import annotations

from typing import Literal

Kind = Literal["triage", "dedup_check", "route_explanation"]
QueueName = Literal["llm-fast", "llm-slow"]

# Deliberately simple and explainable, not ML-based estimation — matching this project's general
# scoring philosophy (see docs/ROUTING_FEATURE_PRD.md). A dedup_check additionally scales with how
# many candidate reports it must compare against, since that is genuinely the more expensive job
# shape, not just a fixed constant per kind.
_BASE_DURATION_MS = 400
_PER_CHAR_MS = 2
_PER_CANDIDATE_MS = 150


def estimate_duration_ms(kind: Kind, input_chars: int, candidate_count: int = 0) -> int:
    if input_chars < 0:
        raise ValueError("input_chars must not be negative")
    if candidate_count < 0:
        raise ValueError("candidate_count must not be negative")
    duration = _BASE_DURATION_MS + input_chars * _PER_CHAR_MS
    if kind == "dedup_check":
        duration += candidate_count * _PER_CANDIDATE_MS
    return duration


def choose_queue(estimated_duration_ms: int, fast_queue_max_estimated_ms: int) -> QueueName:
    return "llm-fast" if estimated_duration_ms <= fast_queue_max_estimated_ms else "llm-slow"
