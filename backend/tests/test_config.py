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
    ],
)
def test_foundation_configuration_rejects_invalid_values(
    field: str, value: str
) -> None:
    values = {**VALID_SETTINGS, field: value}

    with pytest.raises(ValidationError):
        Settings(**values)


def test_foundation_configuration_has_no_dependency_url_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DATABASE_URL", "REDIS_URL", "FOUNDATION_DATA_VERSION", "JWT_SECRET", "AUTH_ALLOWED_ORIGIN"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_initializer_converts_application_url_for_direct_psycopg_connections() -> None:
    assert synchronous_database_url(VALID_SETTINGS["database_url"]) == (
        "postgresql://road_user:secret@postgres:5432/road_risk"
    )
