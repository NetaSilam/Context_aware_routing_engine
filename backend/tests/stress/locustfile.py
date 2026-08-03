from __future__ import annotations

import os
from uuid import uuid4

from locust import HttpUser, between, task


class RouteWorkflowUser(HttpUser):
    """Exercise bounded public workflows; 429/503 are expected admission outcomes."""

    wait_time = between(0.05, 0.15)

    def on_start(self) -> None:
        self.email = f"locust-{uuid4()}@example.com"
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
                response.success()
            elif response.status_code in {429, 503}:
                response.success()
            else:
                response.failure(f"unexpected signup status {response.status_code}")

    @task(4)
    def submit_and_poll_route(self) -> None:
        headers = {"Origin": os.environ.get("AUTH_ALLOWED_ORIGIN", "http://localhost:5173"), "Idempotency-Key": str(uuid4())}
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
                            headers={"Origin": os.environ.get("AUTH_ALLOWED_ORIGIN", "http://localhost:5173")},
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
