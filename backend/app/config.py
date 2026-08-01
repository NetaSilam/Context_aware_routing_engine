from __future__ import annotations

from functools import lru_cache

from typing import Literal

from pydantic import Field, HttpUrl, RedisDsn, field_validator, model_validator
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
    corridor_matcher_method: Literal["sampled-nearest"] = "sampled-nearest"
    corridor_matcher_version: str = Field(
        default="sampled-nearest-v1", min_length=1, max_length=100
    )
    corridor_matcher_sample_interval_m: float = Field(default=100.0, ge=50.0, le=100.0)
    corridor_matcher_tolerance_m: float = Field(default=30.0, gt=0.0, le=100.0)
    corridor_matcher_low_coverage_threshold: float = Field(
        default=0.80, ge=0.0, le=1.0
    )
    osrm_base_url: HttpUrl
    osrm_connect_timeout_seconds: float = Field(default=2.0, gt=0.0, le=10.0)
    osrm_response_timeout_seconds: float = Field(default=5.0, gt=0.0, le=30.0)
    osrm_max_connections: int = Field(default=20, ge=1, le=100)
    osrm_max_keepalive_connections: int = Field(default=10, ge=0, le=100)
    expected_osrm_graph_version: str = Field(min_length=1, max_length=100)
    route_region_min_longitude: float = Field(default=34.0, ge=-180, le=180)
    route_region_max_longitude: float = Field(default=35.9, ge=-180, le=180)
    route_region_min_latitude: float = Field(default=29.4, ge=-90, le=90)
    route_region_max_latitude: float = Field(default=33.4, ge=-90, le=90)

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

    @model_validator(mode="after")
    def validate_osrm_connection_pool(self) -> "Settings":
        if self.osrm_max_keepalive_connections > self.osrm_max_connections:
            raise ValueError(
                "OSRM_MAX_KEEPALIVE_CONNECTIONS cannot exceed OSRM_MAX_CONNECTIONS"
            )
        if self.route_region_min_longitude >= self.route_region_max_longitude:
            raise ValueError("route longitude bounds must be ordered")
        if self.route_region_min_latitude >= self.route_region_max_latitude:
            raise ValueError("route latitude bounds must be ordered")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
