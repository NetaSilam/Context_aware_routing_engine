from __future__ import annotations

from fastapi import HTTPException, Request, status
from redis.exceptions import RedisError

from app.config import get_settings
from app.redis_client import get_redis


async def enforce_auth_rate_limit(action: str, request: Request) -> None:
    settings = get_settings()
    limit = settings.signup_rate_limit if action == "signup" else settings.login_rate_limit
    client_ip = request.client.host if request.client else "unknown"
    key = f"auth-rate:{action}:ip:{client_ip}"

    try:
        redis = get_redis()
        count, ttl = await redis.eval(
            """
            local count = redis.call('INCR', KEYS[1])
            if count == 1 then
                redis.call('EXPIRE', KEYS[1], ARGV[1])
            end
            return {count, redis.call('TTL', KEYS[1])}
            """,
            1,
            key,
            settings.auth_rate_limit_window_seconds,
        )
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication protection is temporarily unavailable. Please retry later.",
            headers={"Retry-After": "5"},
        ) from exc

    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication attempts. Please retry later.",
            headers={"Retry-After": str(max(ttl, 1))},
        )
