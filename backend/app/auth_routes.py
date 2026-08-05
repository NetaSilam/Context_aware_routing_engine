from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    require_trusted_origin,
    verify_password,
)
from app.auth_rate_limit import enforce_auth_rate_limit
from app.config import get_settings
from app.db import get_engine

router = APIRouter(prefix="/api/auth", tags=["auth"])

DrivingExperience = Literal["novice", "experienced"]
VehicleType = Literal["car", "motorcycle", "truck"]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def normalize_email(value: str) -> str:
    return value.strip().casefold()


class SignupRequest(StrictRequest):
    email: EmailStr
    password: str
    driving_experience: DrivingExperience = "experienced"
    vehicle_type: VehicleType = "car"
    avoid_tolls: bool = False
    avoid_highways: bool = False

    @field_validator("email", mode="before")
    @classmethod
    def normalize_submitted_email(cls, value: Any) -> Any:
        return normalize_email(value) if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def validate_password_bounds(cls, value: str) -> str:
        if len(value) < 8 or len(value) > 72 or len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be between 8 and 72 bytes.")
        return value


class LoginRequest(StrictRequest):
    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def normalize_submitted_email(cls, value: Any) -> Any:
        return normalize_email(value) if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def validate_password_maximum(cls, value: str) -> str:
        if len(value) > 72 or len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 bytes.")
        return value


class PreferencesUpdate(StrictRequest):
    driving_experience: DrivingExperience | None = None
    vehicle_type: VehicleType | None = None
    avoid_tolls: bool | None = None
    avoid_highways: bool | None = None


class UserProfile(BaseModel):
    id: int
    email: EmailStr
    driving_experience: DrivingExperience
    vehicle_type: VehicleType
    avoid_tolls: bool
    avoid_highways: bool


def set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.auth_cookie_max_age_seconds,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="strict",
        path="/",
    )
    prevent_session_caching(response)


def prevent_session_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.post("/signup", response_model=UserProfile, status_code=status.HTTP_201_CREATED)
async def signup(payload: SignupRequest, request: Request, response: Response) -> dict[str, Any]:
    email = str(payload.email)
    await enforce_auth_rate_limit("signup", request)
    password_hash = hash_password(payload.password)
    sql = text(
        """
        INSERT INTO app.users
            (email, password_hash, driving_experience, vehicle_type, avoid_tolls, avoid_highways)
        VALUES (:email, :password_hash, :driving_experience, :vehicle_type, :avoid_tolls, :avoid_highways)
        RETURNING id, email, driving_experience, vehicle_type, avoid_tolls, avoid_highways
        """
    )
    try:
        async with get_engine().begin() as conn:
            row = (await conn.execute(sql, {**payload.model_dump(exclude={"password"}), "email": email, "password_hash": password_hash})).mappings().one()
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from exc

    set_session_cookie(response, create_access_token(row["id"], row["email"]))
    return dict(row)


@router.post("/login", response_model=UserProfile)
async def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    email = str(payload.email)
    await enforce_auth_rate_limit("login", request)
    sql = text(
        """SELECT id, email, password_hash, driving_experience, vehicle_type,
                  avoid_tolls, avoid_highways FROM app.users WHERE email = :email"""
    )
    async with get_engine().begin() as conn:
        row = (await conn.execute(sql, {"email": email})).mappings().first()

    if row is None or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    set_session_cookie(response, create_access_token(row["id"], row["email"]))
    return {key: value for key, value in row.items() if key != "password_hash"}


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    dependencies=[Depends(require_trusted_origin)],
)
async def logout(_: dict[str, Any] = Depends(get_current_user)) -> Response:
    settings = get_settings()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="strict",
    )
    prevent_session_caching(response)
    return response


@router.get("/me", response_model=UserProfile)
async def get_me(response: Response, user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    prevent_session_caching(response)
    return user


@router.patch("/me", response_model=UserProfile, dependencies=[Depends(require_trusted_origin)])
async def update_me(
    payload: PreferencesUpdate,
    response: Response,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    prevent_session_caching(response)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return user
    set_clause = ", ".join(f"{key} = :{key}" for key in updates)
    sql = text(f"UPDATE app.users SET {set_clause} WHERE id = :user_id")
    async with get_engine().begin() as conn:
        await conn.execute(sql, {**updates, "user_id": user["id"]})
    return {**user, **updates}
