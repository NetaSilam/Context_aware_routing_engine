from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from fastapi import HTTPException, Request, status
from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine

JWT_ALGORITHM = "HS256"
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user_id: int, email: str) -> str:
    settings = get_settings()
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": datetime.now(timezone.utc)
        + timedelta(seconds=settings.auth_cookie_max_age_seconds),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[JWT_ALGORITHM])
        if not isinstance(payload.get("sub"), str) or not payload["sub"].isdigit():
            raise jwt.InvalidTokenError("invalid subject")
        return payload
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token.") from exc


async def get_current_user(
    request: Request,
) -> dict[str, Any]:
    token = request.cookies.get(get_settings().auth_cookie_name)
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    payload = decode_access_token(token)
    user_id = int(payload["sub"])

    sql = text(
        """
        SELECT id, email, driving_experience, vehicle_type, avoid_tolls, avoid_highways, safety_preference
        FROM app.users WHERE id = :user_id
        """
    )
    async with get_engine().begin() as conn:
        row = (await conn.execute(sql, {"user_id": user_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists.")
    return dict(row)


async def require_trusted_origin(request: Request) -> None:
    if request.headers.get("origin") != get_settings().auth_allowed_origin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Untrusted request origin.")
