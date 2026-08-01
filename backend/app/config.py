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


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
