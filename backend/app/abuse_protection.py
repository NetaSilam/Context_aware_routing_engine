from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import redis as sync_redis
from fastapi import HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import get_settings
from app.redis_client import get_redis

CAPACITY_GLOBAL_KEY = "route-capacity:global"
CAPACITY_USERS_KEY = "route-capacity:users"

RATE_LIMIT_SCRIPT = """
local results = {}
for index, key in ipairs(KEYS) do
    local count = redis.call('INCR', key)
    if count == 1 then redis.call('EXPIRE', key, ARGV[1]) end
    results[index] = count
end
local ttl = 1
for _, key in ipairs(KEYS) do ttl = math.max(ttl, redis.call('TTL', key)) end
results[#KEYS + 1] = ttl
return results
"""

RESERVE_CAPACITY_SCRIPT = """
if redis.call('SISMEMBER', KEYS[1], ARGV[1]) == 1 then return 0 end
if redis.call('SCARD', KEYS[2]) >= tonumber(ARGV[2]) then return -1 end
if redis.call('SCARD', KEYS[1]) >= tonumber(ARGV[3]) then return -2 end
redis.call('SADD', KEYS[1], ARGV[1])
redis.call('SADD', KEYS[2], ARGV[1])
redis.call('SADD', KEYS[3], ARGV[4])
return 1
"""

RELEASE_CAPACITY_SCRIPT = """
local removed = redis.call('SREM', KEYS[1], ARGV[1])
redis.call('SREM', KEYS[2], ARGV[1])
if redis.call('SCARD', KEYS[2]) == 0 then
    redis.call('DEL', KEYS[2])
    redis.call('SREM', KEYS[3], ARGV[2])
end
return removed
"""

SWAP_CAPACITY_SCRIPT = """
redis.call('SREM', KEYS[1], ARGV[1])
redis.call('SREM', KEYS[2], ARGV[1])
redis.call('SADD', KEYS[1], ARGV[2])
redis.call('SADD', KEYS[2], ARGV[2])
redis.call('SADD', KEYS[3], ARGV[3])
return 1
"""

RECONCILE_CAPACITY_SCRIPT = """
local users = redis.call('SMEMBERS', KEYS[2])
for _, user_id in ipairs(users) do redis.call('DEL', 'route-capacity:user:' .. user_id) end
redis.call('DEL', KEYS[1], KEYS[2])
for index = 1, #ARGV, 2 do
    local job_id = ARGV[index]
    local user_id = ARGV[index + 1]
    redis.call('SADD', KEYS[1], job_id)
    redis.call('SADD', 'route-capacity:user:' .. user_id, job_id)
    redis.call('SADD', KEYS[2], user_id)
end
return redis.call('SCARD', KEYS[1])
"""


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _capacity_user_key(user_id: int) -> str:
    return f"route-capacity:user:{user_id}"


def protection_unavailable(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=detail,
        headers={"Retry-After": "5"},
    )


async def enforce_action_rate_limit(
    action: str,
    request: Request,
    user_id: int,
    *,
    user_limit: int,
    ip_limit: int,
) -> None:
    settings = get_settings()
    keys = [
        f"action-rate:{action}:user:{user_id}",
        f"action-rate:{action}:ip:{_client_ip(request)}",
    ]
    try:
        counts = await get_redis().eval(
            RATE_LIMIT_SCRIPT,
            len(keys),
            *keys,
            settings.route_protection_window_seconds,
        )
    except RedisError as exc:
        raise protection_unavailable("Request protection is temporarily unavailable.") from exc
    if counts[0] > user_limit or counts[1] > ip_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please retry later.",
            headers={"Retry-After": str(max(int(counts[2]), 1))},
        )


async def reserve_route_capacity(job_id: str, user_id: int) -> None:
    settings = get_settings()
    try:
        result = await get_redis().eval(
            RESERVE_CAPACITY_SCRIPT,
            3,
            CAPACITY_GLOBAL_KEY,
            _capacity_user_key(user_id),
            CAPACITY_USERS_KEY,
            job_id,
            settings.unfinished_route_jobs_per_user,
            settings.unfinished_route_jobs_global,
            user_id,
        )
    except RedisError as exc:
        raise protection_unavailable("Route capacity protection is temporarily unavailable.") from exc
    if result < 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Route processing capacity is currently full. Please retry later.",
            headers={"Retry-After": "5"},
        )


async def release_route_capacity(job_id: str, user_id: int) -> bool:
    try:
        removed = await get_redis().eval(
            RELEASE_CAPACITY_SCRIPT,
            3,
            CAPACITY_GLOBAL_KEY,
            _capacity_user_key(user_id),
            CAPACITY_USERS_KEY,
            job_id,
            user_id,
        )
    except RedisError as exc:
        raise protection_unavailable("Route capacity protection is temporarily unavailable.") from exc
    return bool(removed)


async def swap_route_capacity(proposed_job_id: str, saved_job_id: str, user_id: int) -> None:
    try:
        await get_redis().eval(
            SWAP_CAPACITY_SCRIPT,
            3,
            CAPACITY_GLOBAL_KEY,
            _capacity_user_key(user_id),
            CAPACITY_USERS_KEY,
            proposed_job_id,
            saved_job_id,
            user_id,
        )
    except RedisError as exc:
        raise protection_unavailable("Route capacity protection is temporarily unavailable.") from exc


def release_route_capacity_sync(job_id: str, user_id: int) -> bool:
    client = sync_redis.Redis.from_url(str(get_settings().redis_url), decode_responses=True)
    try:
        removed = client.eval(
            RELEASE_CAPACITY_SCRIPT,
            3,
            CAPACITY_GLOBAL_KEY,
            _capacity_user_key(user_id),
            CAPACITY_USERS_KEY,
            job_id,
            user_id,
        )
        return bool(removed)
    finally:
        client.close()


async def reconcile_route_capacity(rows: Iterable[tuple[Any, Any]], redis: Redis | None = None) -> int:
    arguments = [str(value) for row in rows for value in row]
    client = redis or get_redis()
    return int(
        await client.eval(
            RECONCILE_CAPACITY_SCRIPT,
            2,
            CAPACITY_GLOBAL_KEY,
            CAPACITY_USERS_KEY,
            *arguments,
        )
    )
