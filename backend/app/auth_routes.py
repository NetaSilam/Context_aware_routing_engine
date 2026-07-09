from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.auth import create_access_token, get_current_user, hash_password, verify_password
from app.db import get_engine

router = APIRouter(prefix="/api/auth", tags=["auth"])

DrivingExperience = Literal["novice", "experienced"]
VehicleType = Literal["car", "motorcycle", "truck"]


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    driving_experience: DrivingExperience = "experienced"
    vehicle_type: VehicleType = "car"
    avoid_tolls: bool = False
    avoid_highways: bool = False


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class PreferencesUpdate(BaseModel):
    driving_experience: DrivingExperience | None = None
    vehicle_type: VehicleType | None = None
    avoid_tolls: bool | None = None
    avoid_highways: bool | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/signup", response_model=TokenResponse, status_code=201)
def signup(payload: SignupRequest) -> TokenResponse:
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    sql = text(
        """
        INSERT INTO app.users
            (email, password_hash, driving_experience, vehicle_type, avoid_tolls, avoid_highways)
        VALUES (:email, :password_hash, :driving_experience, :vehicle_type, :avoid_tolls, :avoid_highways)
        RETURNING id
        """
    )
    try:
        with get_engine().begin() as conn:
            row = conn.execute(
                sql,
                {
                    "email": payload.email,
                    "password_hash": hash_password(payload.password),
                    "driving_experience": payload.driving_experience,
                    "vehicle_type": payload.vehicle_type,
                    "avoid_tolls": payload.avoid_tolls,
                    "avoid_highways": payload.avoid_highways,
                },
            ).mappings().first()
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from exc

    return TokenResponse(access_token=create_access_token(row["id"], payload.email))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    sql = text("SELECT id, email, password_hash FROM app.users WHERE email = :email")
    with get_engine().begin() as conn:
        row = conn.execute(sql, {"email": payload.email}).mappings().first()

    if row is None or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")

    return TokenResponse(access_token=create_access_token(row["id"], row["email"]))


@router.get("/me")
def get_me(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return user


@router.patch("/me")
def update_me(
    payload: PreferencesUpdate, user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return user

    set_clause = ", ".join(f"{key} = :{key}" for key in updates)
    sql = text(f"UPDATE app.users SET {set_clause} WHERE id = :user_id")
    with get_engine().begin() as conn:
        conn.execute(sql, {**updates, "user_id": user["id"]})

    return {**user, **updates}
