from __future__ import annotations

from functools import lru_cache

from pydantic import Field, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    redis_url: RedisDsn
    foundation_data_version: str = Field(min_length=1, max_length=100)
    testing: bool = False
    readiness_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    jwt_secret: str = Field(min_length=32)
    auth_cookie_name: str = Field(default="road_risk_session", min_length=1, max_length=64)
    auth_cookie_secure: bool = False
    auth_cookie_max_age_seconds: int = Field(default=86_400, ge=86_400, le=86_400)
    auth_allowed_origin: str = Field(min_length=1)
    auth_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    signup_rate_limit: int = Field(default=5, ge=1, le=100)
    login_rate_limit: int = Field(default=10, ge=1, le=100)

    @field_validator("database_url")
    @classmethod
    def validate_async_database_url(cls, value: str) -> str:
        url = make_url(value)
        if url.drivername not in {"postgresql+psycopg", "postgresql+asyncpg"}:
            raise ValueError(
                "DATABASE_URL must use an async PostgreSQL driver "
                "(postgresql+psycopg or postgresql+asyncpg)"
            )
        if not url.host or not url.database or not url.username or url.password is None:
            raise ValueError("DATABASE_URL must include host, database, username, and password")
        return value

    @field_validator("jwt_secret")
    @classmethod
    def reject_placeholder_jwt_secret(cls, value: str) -> str:
        normalized = value.strip().casefold()
        placeholder_fragments = ("replace", "change-me", "changeme", "placeholder")
        if any(fragment in normalized for fragment in placeholder_fragments):
            raise ValueError("JWT_SECRET must not be a placeholder")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
