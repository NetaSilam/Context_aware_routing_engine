from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from redis.exceptions import RedisError

from app import abuse_protection
from app.abuse_protection import enforce_action_rate_limit


class _FakeClient:
    host = "127.0.0.1"


class _FakeRequest:
    client = _FakeClient()


class _FlakyRedisEval:
    """Stand-in for the async Redis client's `.eval()` — fails `fail_times` times
    before returning `result`, so both the retry-succeeds and gives-up-after-two
    paths are exercised, not just a rigged happy path."""

    def __init__(self, fail_times: int, result: list[int]) -> None:
        self.fail_times = fail_times
        self.result = result
        self.calls = 0

    async def eval(self, *_args: object, **_kwargs: object) -> list[int]:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RedisError("simulated redis blip")
        return self.result


def _run_check(fake_redis: _FlakyRedisEval, *, user_limit: int = 10, ip_limit: int = 10) -> None:
    asyncio.run(
        enforce_action_rate_limit(
            "test-action", _FakeRequest(), user_id=1, user_limit=user_limit, ip_limit=ip_limit
        )
    )


def test_rate_limit_check_retries_once_after_a_transient_redis_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = _FlakyRedisEval(fail_times=1, result=[1, 1, 60])
    monkeypatch.setattr(abuse_protection, "get_redis", lambda: fake_redis)

    _run_check(fake_redis)  # must not raise

    assert fake_redis.calls == 2


def test_rate_limit_check_fails_closed_after_two_transient_redis_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = _FlakyRedisEval(fail_times=99, result=[1, 1, 60])
    monkeypatch.setattr(abuse_protection, "get_redis", lambda: fake_redis)

    with pytest.raises(HTTPException) as excinfo:
        _run_check(fake_redis)

    assert excinfo.value.status_code == 503
    assert fake_redis.calls == 2


def test_rate_limit_check_still_rejects_requests_over_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = _FlakyRedisEval(fail_times=0, result=[11, 1, 60])
    monkeypatch.setattr(abuse_protection, "get_redis", lambda: fake_redis)

    with pytest.raises(HTTPException) as excinfo:
        _run_check(fake_redis, user_limit=10, ip_limit=10)

    assert excinfo.value.status_code == 429
    assert fake_redis.calls == 1
