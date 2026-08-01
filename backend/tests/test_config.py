import pytest
from pydantic import ValidationError

from app.config import Settings
from app.initialize_foundation import synchronous_database_url


VALID_SETTINGS = {
    "database_url": "postgresql+psycopg://road_user:secret@postgres:5432/road_risk",
    "redis_url": "redis://redis:6379/0",
    "foundation_data_version": "fixture-v1",
    "jwt_secret": "test-secret-with-at-least-32-characters",
    "auth_allowed_origin": "http://localhost:5173",
    "osrm_base_url": "http://osrm:5000/",
}


def test_foundation_configuration_accepts_async_dependency_urls() -> None:
    settings = Settings(**VALID_SETTINGS)

    assert settings.database_url.startswith("postgresql+psycopg://")
    assert str(settings.redis_url) == "redis://redis:6379/0"
    assert settings.foundation_data_version == "fixture-v1"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_url", "sqlite:///road-risk.db"),
        ("database_url", "postgresql+psycopg://postgres/road_risk"),
        ("redis_url", "http://redis:6379/0"),
        ("foundation_data_version", ""),
        ("jwt_secret", "replace_with_a_long_random_secret"),
        ("osrm_base_url", "not-a-url"),
        ("osrm_connect_timeout_seconds", 0),
        ("osrm_response_timeout_seconds", 31),
        ("osrm_max_connections", 0),
        ("route_job_max_retries", 11),
        ("route_worker_concurrency", 0),
    ],
)
def test_foundation_configuration_rejects_invalid_values(
    field: str, value: str
) -> None:
    values = {**VALID_SETTINGS, field: value}

    with pytest.raises(ValidationError):
        Settings(**values)


def test_foundation_configuration_has_no_dependency_url_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DATABASE_URL",
        "REDIS_URL",
        "FOUNDATION_DATA_VERSION",
        "JWT_SECRET",
        "AUTH_ALLOWED_ORIGIN",
        "OSRM_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_initializer_converts_application_url_for_direct_psycopg_connections() -> None:
    assert synchronous_database_url(VALID_SETTINGS["database_url"]) == (
        "postgresql://road_user:secret@postgres:5432/road_risk"
    )


def test_osrm_configuration_rejects_keepalive_pool_larger_than_total_pool() -> None:
    with pytest.raises(ValidationError):
        Settings(
            **VALID_SETTINGS,
            osrm_max_connections=5,
            osrm_max_keepalive_connections=6,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"celery_task_soft_time_limit_seconds": 60, "celery_task_time_limit_seconds": 60},
        {"route_job_lease_seconds": 120, "celery_visibility_timeout_seconds": 120},
        {"celery_task_time_limit_seconds": 90, "route_job_lease_seconds": 90},
    ],
)
def test_route_recovery_configuration_rejects_unsafe_time_bounds(
    overrides: dict[str, int],
) -> None:
    with pytest.raises(ValidationError):
        Settings(**VALID_SETTINGS, **overrides)
