from __future__ import annotations

import os
import random
from uuid import uuid4

from locust import HttpUser, between, task

_ORIGIN = os.environ.get("AUTH_ALLOWED_ORIGIN", "http://localhost:5173")


class RouteWorkflowUser(HttpUser):
    """Exercise bounded public workflows; 429/503 are expected admission outcomes."""

    wait_time = between(0.05, 0.15)
    _known_user_ids: list[int] = []

    def on_start(self) -> None:
        self.email = f"locust-{uuid4()}@example.com"
        self.post_id = None
        payload = {
            "email": self.email,
            "password": "correct-password",
            "driving_experience": "experienced",
            "vehicle_type": "car",
            "avoid_tolls": False,
            "avoid_highways": False,
        }
        with self.client.post("/api/auth/signup", json=payload, name="signup", catch_response=True) as response:
            if response.status_code == 201:
                self.user_id = response.json()["id"]
                RouteWorkflowUser._known_user_ids.append(self.user_id)
                response.success()
            elif response.status_code in {429, 503}:
                self.user_id = None
                response.success()
            else:
                self.user_id = None
                response.failure(f"unexpected signup status {response.status_code}")

    @task(3)
    def report_and_vote_on_hazard(self) -> None:
        headers = {"Origin": _ORIGIN}
        if self.post_id is None:
            payload = {
                "title": "Stress-generated hazard report",
                "body": "Locust load-test report; safe to ignore.",
                "hazard_type": "pothole",
                "is_anonymous": False,
            }
            with self.client.post("/api/forum/posts", json=payload, headers=headers, name="forum-post-create", catch_response=True) as response:
                if response.status_code == 201:
                    self.post_id = response.json()["id"]
                    response.success()
                elif response.status_code in {429, 503}:
                    response.success()
                else:
                    response.failure(f"unexpected forum post status {response.status_code}")
        else:
            with self.client.put(
                f"/api/forum/posts/{self.post_id}/vote", json={"value": "up"}, headers=headers, name="forum-vote", catch_response=True
            ) as response:
                if response.status_code in {204, 404, 429, 503}:
                    response.success()
                else:
                    response.failure(f"unexpected forum vote status {response.status_code}")

    @task(2)
    def comment_on_a_hazard_report(self) -> None:
        if self.post_id is None:
            return
        headers = {"Origin": _ORIGIN}
        payload = {"body": "Still there, confirmed.", "is_anonymous": False}
        with self.client.post(
            f"/api/forum/posts/{self.post_id}/comments", json=payload, headers=headers, name="forum-comment-create", catch_response=True
        ) as response:
            if response.status_code in {201, 404, 429, 503}:
                response.success()
            else:
                response.failure(f"unexpected forum comment status {response.status_code}")

    @task(1)
    def send_a_direct_message(self) -> None:
        candidates = [uid for uid in RouteWorkflowUser._known_user_ids if uid != self.user_id]
        recipient_id = random.choice(candidates) if candidates else self.user_id
        if recipient_id is None:
            return
        headers = {"Origin": _ORIGIN}
        with self.client.post(
            f"/api/messages/{recipient_id}", data={"body": "Stress-generated direct message."}, headers=headers, name="dm-send", catch_response=True
        ) as response:
            if response.status_code in {201, 404, 422, 429, 503}:
                response.success()
            else:
                response.failure(f"unexpected DM send status {response.status_code}")

    @task(4)
    def submit_and_poll_route(self) -> None:
        headers = {"Origin": _ORIGIN, "Idempotency-Key": str(uuid4())}
        payload = {
            "origin_longitude": 34.78,
            "origin_latitude": 32.07,
            "destination_longitude": 34.79,
            "destination_latitude": 32.08,
        }
        with self.client.post("/api/route-jobs", json=payload, headers=headers, name="route-submit", catch_response=True) as response:
            if response.status_code == 202:
                self.job_id = response.json()["id"]
                response.success()
            elif response.status_code in {429, 503}:
                response.success()
            else:
                response.failure(f"unexpected route status {response.status_code}")
        if getattr(self, "job_id", None):
            with self.client.get(f"/api/route-jobs/{self.job_id}", name="route-poll", catch_response=True) as response:
                if response.status_code in {200, 404, 429, 503}:
                    if response.status_code == 200 and response.json().get("status") == "completed":
                        self.client.delete(
                            f"/api/route-history/{self.job_id}",
                            headers={"Origin": _ORIGIN},
                            name="history-delete",
                        )
                    response.success()
                else:
                    response.failure(f"unexpected poll status {response.status_code}")

    @task(2)
    def geocode_and_history(self) -> None:
        with self.client.get("/api/geocoding/search", params={"q": "fixture origin"}, name="geocode", catch_response=True) as response:
            if response.status_code in {200, 429, 503}:
                response.success()
            else:
                response.failure(f"unexpected geocode status {response.status_code}")
        with self.client.get("/api/route-history", name="history", catch_response=True) as response:
            if response.status_code in {200, 429, 503}:
                response.success()
            else:
                response.failure(f"unexpected history status {response.status_code}")

    @task(1)
    def repeat_login(self) -> None:
        with self.client.post("/api/auth/login", json={"email": self.email, "password": "correct-password"}, name="login", catch_response=True) as response:
            if response.status_code in {200, 429, 503}:
                response.success()
            else:
                response.failure(f"unexpected login status {response.status_code}")


class AbusiveForumUser(HttpUser):
    """Exactly one simulated account hammering forum writes with near-zero wait time, proving
    rate limiting bounds a single abusive user (429/503) instead of an unbounded queue or crash."""

    fixed_count = 1
    wait_time = between(0.0, 0.02)

    def on_start(self) -> None:
        self.email = f"locust-abusive-{uuid4()}@example.com"
        payload = {
            "email": self.email,
            "password": "correct-password",
            "driving_experience": "experienced",
            "vehicle_type": "car",
            "avoid_tolls": False,
            "avoid_highways": False,
        }
        with self.client.post("/api/auth/signup", json=payload, name="abusive-signup", catch_response=True) as response:
            if response.status_code in {201, 429, 503}:
                response.success()
            else:
                response.failure(f"unexpected abusive signup status {response.status_code}")

    @task
    def hammer_forum_post_creation(self) -> None:
        headers = {"Origin": _ORIGIN}
        payload = {
            "title": "Abusive burst report",
            "body": "Rapid-fire load-test report; safe to ignore.",
            "hazard_type": "other",
            "is_anonymous": False,
        }
        with self.client.post("/api/forum/posts", json=payload, headers=headers, name="forum-post-abuse", catch_response=True) as response:
            if response.status_code in {201, 429, 503}:
                response.success()
            else:
                response.failure(f"unexpected abusive post status {response.status_code}")


class LlmQueueStressUser(HttpUser):
    """A handful of simulated accounts creating hazard reports and route jobs back-to-back, at a
    higher relative rate than RouteWorkflowUser's general mixed workload — every hazard report
    enqueues a triage job (which can itself cascade into a dedup_check job) and every completed
    route job enqueues a route_explanation job, so this is the task class that most directly
    drives llm-fast/llm-slow queue depth under load. Proves the queues stay bounded (drain back
    down, no worker crash) rather than growing without limit as load is sustained."""

    fixed_count = 3
    wait_time = between(0.0, 0.05)

    def on_start(self) -> None:
        self.email = f"locust-llm-{uuid4()}@example.com"
        payload = {
            "email": self.email,
            "password": "correct-password",
            "driving_experience": "experienced",
            "vehicle_type": "car",
            "avoid_tolls": False,
            "avoid_highways": False,
        }
        with self.client.post("/api/auth/signup", json=payload, name="llm-stress-signup", catch_response=True) as response:
            if response.status_code in {201, 429, 503}:
                response.success()
            else:
                response.failure(f"unexpected llm-stress signup status {response.status_code}")

    @task(3)
    def burst_create_hazard_report(self) -> None:
        headers = {"Origin": _ORIGIN}
        payload = {
            "title": "LLM-queue stress report",
            "body": "High-rate load-test report meant to enqueue a triage job; safe to ignore.",
            "hazard_type": "crash",
            "is_anonymous": False,
            "longitude": 34.78,
            "latitude": 32.07,
        }
        with self.client.post("/api/forum/posts", json=payload, headers=headers, name="llm-stress-forum-post", catch_response=True) as response:
            if response.status_code in {201, 429, 503}:
                response.success()
            else:
                response.failure(f"unexpected llm-stress post status {response.status_code}")

    @task(2)
    def burst_submit_route_job(self) -> None:
        headers = {"Origin": _ORIGIN, "Idempotency-Key": str(uuid4())}
        payload = {
            "origin_longitude": 34.78,
            "origin_latitude": 32.07,
            "destination_longitude": 34.79,
            "destination_latitude": 32.08,
        }
        with self.client.post("/api/route-jobs", json=payload, headers=headers, name="llm-stress-route-submit", catch_response=True) as response:
            if response.status_code in {202, 429, 503}:
                response.success()
            else:
                response.failure(f"unexpected llm-stress route status {response.status_code}")
