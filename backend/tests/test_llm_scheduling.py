from __future__ import annotations

import pytest

from app.llm.scheduling import choose_queue, estimate_duration_ms


def test_estimate_duration_scales_with_input_length_for_triage() -> None:
    short = estimate_duration_ms("triage", input_chars=10)
    long = estimate_duration_ms("triage", input_chars=2000)

    assert long > short


def test_estimate_duration_ignores_candidate_count_for_triage() -> None:
    without_candidates = estimate_duration_ms("triage", input_chars=100, candidate_count=0)
    with_candidates = estimate_duration_ms("triage", input_chars=100, candidate_count=50)

    assert without_candidates == with_candidates


def test_estimate_duration_scales_with_candidate_count_for_dedup_check() -> None:
    few_candidates = estimate_duration_ms("dedup_check", input_chars=100, candidate_count=1)
    many_candidates = estimate_duration_ms("dedup_check", input_chars=100, candidate_count=20)

    assert many_candidates > few_candidates


def test_estimate_duration_rejects_negative_inputs() -> None:
    with pytest.raises(ValueError):
        estimate_duration_ms("triage", input_chars=-1)
    with pytest.raises(ValueError):
        estimate_duration_ms("dedup_check", input_chars=10, candidate_count=-1)


def test_choose_queue_boundary_is_inclusive_of_the_fast_queue() -> None:
    assert choose_queue(estimated_duration_ms=4000, fast_queue_max_estimated_ms=4000) == "llm-fast"
    assert choose_queue(estimated_duration_ms=3999, fast_queue_max_estimated_ms=4000) == "llm-fast"
    assert choose_queue(estimated_duration_ms=4001, fast_queue_max_estimated_ms=4000) == "llm-slow"


def test_a_large_candidate_count_alone_can_push_a_small_dedup_job_into_the_slow_queue() -> None:
    small_input_many_candidates = estimate_duration_ms(
        "dedup_check", input_chars=20, candidate_count=100
    )

    assert choose_queue(small_input_many_candidates, fast_queue_max_estimated_ms=4000) == "llm-slow"
