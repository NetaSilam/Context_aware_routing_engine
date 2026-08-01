from __future__ import annotations

import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import psycopg
import pytest
import redis

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_ABUSE_INTEGRATION") != "true",
        reason="requires disposable PostgreSQL, Redis, Celery broker, and fake geocoder",
    ),
]

API_URL = os.environ.get("ABUSE_TEST_API_URL", "http://abuse-api:8000")
UNAVAILABLE_API_URL = os.environ.get(
    "ABUSE_UNAVAILABLE_API_URL", "http://queue-unavailable-api:8000"
)
FAKE_GEOCODER_URL = os.environ.get("FAKE_GEOCODER_URL", "http://fake-geocoder:5001")
DATABASE_URL = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
ORIGIN = os.environ.get("AUTH_ALLOWED_ORIGIN", "http://localhost:5173")
REDIS_URL = os.environ["REDIS_URL"]


@pytest.fixture(autouse=True)
def clear_test_state() -> None:
    redis.Redis.from_url(REDIS_URL).flushdb()
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute("DELETE FROM app.users WHERE email LIKE 'abuse-%@example.com'")
    httpx.post(f"{FAKE_GEOCODER_URL}/reset", timeout=5).raise_for_status()


def signup(prefix: str) -> tuple[dict[str, object], str]:
    response = httpx.post(
        f"{API_URL}/api/auth/signup",
        json={
            "email": f"abuse-{prefix}-{uuid4()}@example.com",
            "password": "correct-password",
            "driving_experience": "experienced",
            "vehicle_type": "car",
            "avoid_tolls": False,
            "avoid_highways": False,
        },
        timeout=5,
    )
    assert response.status_code == 201, response.text
    return response.json(), response.cookies["road_risk_session"]


def route_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "origin_longitude": 34.78,
        "origin_latitude": 32.07,
        "destination_longitude": 34.79,
        "destination_latitude": 32.08,
    }
    payload.update(overrides)
    return payload


def submit(cookie: str, key: str | None = None) -> httpx.Response:
    return httpx.post(
        f"{API_URL}/api/route-jobs",
        cookies={"road_risk_session": cookie},
        headers={"Origin": ORIGIN, "Idempotency-Key": key or str(uuid4())},
        json=route_payload(),
        timeout=10,
    )


def test_concurrent_admission_is_atomic_per_user_and_globally() -> None:
    first_user, first_cookie = signup("capacity-one")
    _, second_cookie = signup("capacity-two")
    with ThreadPoolExecutor(max_workers=10) as pool:
        first_responses = list(pool.map(lambda _: submit(first_cookie), range(10)))
    assert [response.status_code for response in first_responses].count(202) == 2
    assert [response.status_code for response in first_responses].count(429) == 8
    assert all(response.headers.get("retry-after") for response in first_responses if response.status_code == 429)

    second_responses = [submit(second_cookie), submit(second_cookie)]
    assert [response.status_code for response in second_responses] == [202, 429]

    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    assert client.scard("route-capacity:global") == 3
    assert client.scard(f"route-capacity:user:{first_user['id']}") == 2
    assert client.llen("celery") == 3


def test_concurrent_idempotent_retries_create_one_job_and_one_reservation() -> None:
    user, cookie = signup("idempotency")
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=10) as pool:
        responses = list(pool.map(lambda _: submit(cookie, key), range(10)))
    accepted = [response for response in responses if response.status_code == 202]
    assert accepted
    assert len({response.json()["id"] for response in accepted}) == 1
    with psycopg.connect(DATABASE_URL) as connection:
        count = connection.execute(
            "SELECT count(*) FROM app.route_jobs WHERE user_id = %s AND idempotency_key = %s",
            (user["id"], key),
        ).fetchone()[0]
    assert count == 1
    assert redis.Redis.from_url(REDIS_URL).scard("route-capacity:global") == 1
    assert redis.Redis.from_url(REDIS_URL).llen("celery") == 1


def test_polling_and_history_mutations_are_bounded_before_database_work() -> None:
    user, cookie = signup("action-limits")
    accepted = submit(cookie)
    assert accepted.status_code == 202
    job_id = accepted.json()["id"]
    polls = [
        httpx.get(
            f"{API_URL}/api/route-jobs/{job_id}",
            cookies={"road_risk_session": cookie},
            timeout=5,
        )
        for _ in range(3)
    ]
    assert [response.status_code for response in polls] == [200, 200, 429]

    missing_id = uuid4()
    mutations = [
        httpx.delete(
            f"{API_URL}/api/route-history/{missing_id}",
            cookies={"road_risk_session": cookie},
            headers={"Origin": ORIGIN},
            timeout=5,
        )
        for _ in range(3)
    ]
    assert [response.status_code for response in mutations] == [404, 404, 429]
    assert mutations[-1].headers["retry-after"]
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute(
            "SELECT count(*) FROM app.route_jobs WHERE user_id = %s", (user["id"],)
        ).fetchone()[0] == 1


def test_invalid_and_oversized_work_never_reaches_queue_or_geocoder() -> None:
    _, cookie = signup("invalid")
    client = redis.Redis.from_url(REDIS_URL)
    before_queue = client.llen("celery")
    invalid_routes = [
        route_payload(origin_longitude="34.78"),
        route_payload(origin_longitude=0),
        {**route_payload(), "unsupported": True},
    ]
    responses = [
        httpx.post(
            f"{API_URL}/api/route-jobs",
            cookies={"road_risk_session": cookie},
            headers={"Origin": ORIGIN, "Idempotency-Key": str(uuid4())},
            json=payload,
            timeout=5,
        )
        for payload in invalid_routes
    ]
    huge = httpx.post(
        f"{API_URL}/api/route-jobs",
        cookies={"road_risk_session": cookie},
        headers={"Origin": ORIGIN, "Idempotency-Key": str(uuid4())},
        content=b"x" * 1025,
        timeout=5,
    )
    chunked_huge = httpx.post(
        f"{API_URL}/api/route-jobs",
        cookies={"road_risk_session": cookie},
        headers={"Origin": ORIGIN, "Idempotency-Key": str(uuid4())},
        content=(chunk for chunk in (b"x" * 600, b"x" * 600)),
        timeout=5,
    )
    bad_geocode = httpx.get(
        f"{API_URL}/api/geocoding/search",
        params={"q": "x", "unsupported": "1"},
        cookies={"road_risk_session": cookie},
        timeout=5,
    )
    huge_query = httpx.get(
        f"{API_URL}/api/geocoding/search?q={'x' * 200}",
        cookies={"road_risk_session": cookie},
        timeout=5,
    )
    assert [response.status_code for response in responses] == [422, 422, 422]
    assert huge.status_code == 413
    assert chunked_huge.status_code == 413
    assert bad_geocode.status_code == 422
    assert huge_query.status_code == 414
    assert client.llen("celery") == before_queue
    assert httpx.get(f"{FAKE_GEOCODER_URL}/metrics", timeout=5).json()["requests_by_query"] == {}


def test_redis_outage_fails_closed_for_writes_but_keeps_bounded_history_read() -> None:
    _, cookie = signup("redis-outage")
    create = httpx.post(
        f"{UNAVAILABLE_API_URL}/api/route-jobs",
        cookies={"road_risk_session": cookie},
        headers={"Origin": ORIGIN, "Idempotency-Key": str(uuid4())},
        json=route_payload(),
        timeout=5,
    )
    poll = httpx.get(
        f"{UNAVAILABLE_API_URL}/api/route-jobs/{uuid4()}",
        cookies={"road_risk_session": cookie},
        timeout=5,
    )
    mutation = httpx.delete(
        f"{UNAVAILABLE_API_URL}/api/route-history/{uuid4()}",
        cookies={"road_risk_session": cookie},
        headers={"Origin": ORIGIN},
        timeout=5,
    )
    history = httpx.get(
        f"{UNAVAILABLE_API_URL}/api/route-history",
        cookies={"road_risk_session": cookie},
        timeout=5,
    )
    assert [create.status_code, poll.status_code, mutation.status_code] == [503, 503, 503]
    assert all(response.headers["retry-after"] == "5" for response in (create, poll, mutation))
    assert history.status_code == 200


def test_startup_reconciliation_rebuilds_and_corrects_capacity_sets() -> None:
    user, _ = signup("reconcile")
    job_id = uuid4()
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            """
            INSERT INTO app.route_jobs (
                id, user_id, idempotency_key, status, origin_longitude, origin_latitude,
                destination_longitude, destination_latitude, snapshot
            ) VALUES (%s, %s, %s, 'queued', 34.78, 32.07, 34.79, 32.08, '{}')
            """,
            (job_id, user["id"], uuid4()),
        )
    client = redis.Redis.from_url(REDIS_URL)
    client.flushdb()
    client.sadd("route-capacity:global", "leaked-job")
    client.sadd("route-capacity:user:999999", "leaked-job")
    client.sadd("route-capacity:users", "999999")

    process = subprocess.Popen(
        ["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8012"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if httpx.get("http://127.0.0.1:8012/health/live", timeout=0.2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        assert client.smembers("route-capacity:global") == {str(job_id).encode()}
        assert client.smembers(f"route-capacity:user:{user['id']}") == {str(job_id).encode()}
        assert not client.exists("route-capacity:user:999999")
    finally:
        process.terminate()
        process.wait(timeout=5)
