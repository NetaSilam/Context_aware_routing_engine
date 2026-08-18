from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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
    request_body_max_bytes: int = Field(default=16_384, ge=1024, le=1_048_576)
    request_query_max_bytes: int = Field(default=1024, ge=64, le=16_384)
    route_protection_window_seconds: int = Field(default=60, ge=1, le=3600)
    route_creation_user_rate_limit: int = Field(default=10, ge=1, le=1000)
    route_creation_ip_rate_limit: int = Field(default=30, ge=1, le=5000)
    route_poll_user_rate_limit: int = Field(default=120, ge=1, le=10_000)
    route_poll_ip_rate_limit: int = Field(default=300, ge=1, le=20_000)
    history_mutation_user_rate_limit: int = Field(default=20, ge=1, le=1000)
    history_mutation_ip_rate_limit: int = Field(default=60, ge=1, le=5000)
    route_reroute_user_rate_limit: int = Field(default=20, ge=1, le=1000)
    route_reroute_ip_rate_limit: int = Field(default=60, ge=1, le=5000)
    route_reroute_retry_timeout_seconds: float = Field(default=2.0, gt=0.0, le=10.0)
    route_reroute_db_pool_min_size: int = Field(default=1, ge=1, le=20)
    route_reroute_db_pool_max_size: int = Field(default=10, ge=1, le=100)
    forum_nearby_max_span_degrees: float = Field(default=1.0, gt=0.0, le=10.0)
    unfinished_route_jobs_per_user: int = Field(default=3, ge=1, le=100)
    unfinished_route_jobs_global: int = Field(default=100, ge=1, le=100_000)
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
    osrm_deployment_manifest_path: Path | None = None
    osrm_compatibility_required: bool = False
    route_region_min_longitude: float = Field(default=34.0, ge=-180, le=180)
    route_region_max_longitude: float = Field(default=35.9, ge=-180, le=180)
    route_region_min_latitude: float = Field(default=29.4, ge=-90, le=90)
    route_region_max_latitude: float = Field(default=33.4, ge=-90, le=90)
    route_job_stale_created_seconds: int = Field(default=30, ge=1, le=3600)
    route_job_lease_seconds: int = Field(default=90, ge=2, le=600)
    route_job_max_retries: int = Field(default=3, ge=0, le=10)
    route_job_retry_backoff_max_seconds: int = Field(default=30, ge=1, le=300)
    celery_visibility_timeout_seconds: int = Field(default=120, ge=3, le=3600)
    celery_task_soft_time_limit_seconds: int = Field(default=45, ge=1, le=3600)
    celery_task_time_limit_seconds: int = Field(default=60, ge=2, le=3600)
    route_worker_concurrency: int = Field(default=2, ge=1, le=32)
    route_queue_publish_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    route_queue_broker_url: RedisDsn | None = None
    geocoder_base_url: HttpUrl
    geocoder_user_agent: str = Field(min_length=3, max_length=200)
    geocoder_connect_timeout_seconds: float = Field(default=2.0, gt=0.0, le=10.0)
    geocoder_response_timeout_seconds: float = Field(default=5.0, gt=0.0, le=30.0)
    geocoder_query_min_length: int = Field(default=3, ge=1, le=20)
    geocoder_query_max_length: int = Field(default=200, ge=20, le=500)
    geocoder_result_limit: int = Field(default=5, ge=1, le=10)
    geocoder_cache_ttl_seconds: int = Field(default=86_400, ge=60, le=604_800)
    geocoder_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    geocoder_user_rate_limit: int = Field(default=10, ge=1, le=100)
    geocoder_ip_rate_limit: int = Field(default=30, ge=1, le=300)
    forum_protection_window_seconds: int = Field(default=60, ge=1, le=3600)
    forum_post_user_rate_limit: int = Field(default=5, ge=1, le=1000)
    forum_post_ip_rate_limit: int = Field(default=15, ge=1, le=5000)
    forum_comment_user_rate_limit: int = Field(default=20, ge=1, le=1000)
    forum_comment_ip_rate_limit: int = Field(default=60, ge=1, le=5000)
    forum_vote_user_rate_limit: int = Field(default=60, ge=1, le=2000)
    forum_vote_ip_rate_limit: int = Field(default=180, ge=1, le=10_000)
    forum_media_storage_path: Path = Field(default=Path("/data/forum-media"))
    forum_media_max_image_bytes: int = Field(default=5_000_000, ge=1024, le=50_000_000)
    forum_media_max_video_bytes: int = Field(default=25_000_000, ge=1024, le=200_000_000)
    forum_media_allowed_image_content_types: str = Field(
        default="image/jpeg,image/png,image/webp"
    )
    forum_media_allowed_video_content_types: str = Field(default="video/mp4,video/webm")
    forum_media_max_items_per_post: int = Field(default=6, ge=1, le=50)
    forum_media_max_items_per_comment: int = Field(default=3, ge=1, le=50)
    forum_media_upload_user_rate_limit: int = Field(default=10, ge=1, le=500)
    forum_media_upload_ip_rate_limit: int = Field(default=30, ge=1, le=2000)
    dm_protection_window_seconds: int = Field(default=60, ge=1, le=3600)
    dm_send_user_rate_limit: int = Field(default=20, ge=1, le=1000)
    dm_send_ip_rate_limit: int = Field(default=60, ge=1, le=5000)
    gemini_api_key: str | None = Field(default=None)
    gemini_base_url: HttpUrl = Field(
        default=HttpUrl("https://generativelanguage.googleapis.com")
    )
    gemini_model: str = Field(default="gemini-3.5-flash-lite", min_length=1, max_length=100)
    gemini_request_timeout_seconds: float = Field(default=10.0, gt=0.0, le=30.0)
    llm_worker_concurrency: int = Field(default=2, ge=1, le=32)
    llm_fast_queue_max_estimated_ms: int = Field(default=4000, ge=100, le=60_000)
    llm_dedup_lookback_days: int = Field(default=14, ge=1, le=365)
    llm_dedup_radius_meters: float = Field(default=150.0, gt=0.0, le=5000.0)
    llm_dedup_candidate_limit: int = Field(default=20, ge=1, le=200)
    llm_queue_broker_url: RedisDsn | None = None
    llm_queue_publish_timeout_seconds: float = Field(default=2.0, gt=0, le=10)

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
        if self.celery_task_soft_time_limit_seconds >= self.celery_task_time_limit_seconds:
            raise ValueError("Celery soft task limit must be below the hard task limit")
        if self.route_job_lease_seconds >= self.celery_visibility_timeout_seconds:
            raise ValueError("route job lease must be shorter than Celery visibility timeout")
        if self.celery_task_time_limit_seconds >= self.route_job_lease_seconds:
            raise ValueError("Celery hard task limit must be shorter than the route job lease")
        if self.geocoder_query_min_length >= self.geocoder_query_max_length:
            raise ValueError("geocoder query bounds must be ordered")
        if self.geocoder_user_rate_limit > self.geocoder_ip_rate_limit:
            raise ValueError("geocoder per-user limit cannot exceed the per-IP limit")
        if self.route_creation_user_rate_limit > self.route_creation_ip_rate_limit:
            raise ValueError("route creation per-user limit cannot exceed the per-IP limit")
        if self.route_poll_user_rate_limit > self.route_poll_ip_rate_limit:
            raise ValueError("route polling per-user limit cannot exceed the per-IP limit")
        if self.history_mutation_user_rate_limit > self.history_mutation_ip_rate_limit:
            raise ValueError("history mutation per-user limit cannot exceed the per-IP limit")
        if self.route_reroute_user_rate_limit > self.route_reroute_ip_rate_limit:
            raise ValueError("route reroute per-user limit cannot exceed the per-IP limit")
        if self.route_reroute_db_pool_min_size > self.route_reroute_db_pool_max_size:
            raise ValueError("route reroute DB pool min size cannot exceed its max size")
        if self.unfinished_route_jobs_per_user > self.unfinished_route_jobs_global:
            raise ValueError("per-user unfinished job capacity cannot exceed global capacity")
        if self.forum_post_user_rate_limit > self.forum_post_ip_rate_limit:
            raise ValueError("forum post per-user limit cannot exceed the per-IP limit")
        if self.forum_comment_user_rate_limit > self.forum_comment_ip_rate_limit:
            raise ValueError("forum comment per-user limit cannot exceed the per-IP limit")
        if self.forum_vote_user_rate_limit > self.forum_vote_ip_rate_limit:
            raise ValueError("forum vote per-user limit cannot exceed the per-IP limit")
        if self.forum_media_upload_user_rate_limit > self.forum_media_upload_ip_rate_limit:
            raise ValueError("forum media upload per-user limit cannot exceed the per-IP limit")
        if self.dm_send_user_rate_limit > self.dm_send_ip_rate_limit:
            raise ValueError("DM send per-user limit cannot exceed the per-IP limit")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
