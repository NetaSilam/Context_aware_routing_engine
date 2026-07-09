from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine


def ensure_app_schema(engine: Engine) -> None:
    """Creates the `app` schema/tables this project owns (as opposed to the
    ported foundation-pipeline schemas seed.py loads). Safe to call every startup.
    """
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS app"))
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS app.users (
                    id SERIAL PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    driving_experience TEXT NOT NULL DEFAULT 'experienced'
                        CHECK (driving_experience IN ('novice', 'experienced')),
                    vehicle_type TEXT NOT NULL DEFAULT 'car'
                        CHECK (vehicle_type IN ('car', 'motorcycle', 'truck')),
                    avoid_tolls BOOLEAN NOT NULL DEFAULT FALSE,
                    avoid_highways BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )
