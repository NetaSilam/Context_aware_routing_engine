from __future__ import annotations

import os

# Unit tests use explicit, non-routable dependency configuration. Integration
# tests override these values with services on the disposable Compose network.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test_user:test_password@invalid.test:5432/road_risk_test",
)
os.environ.setdefault("REDIS_URL", "redis://invalid.test:6379/0")
os.environ.setdefault("FOUNDATION_DATA_VERSION", "unit-test-fixture-v1")
os.environ.setdefault("JWT_SECRET", "unit-test-only-not-for-deployment")
