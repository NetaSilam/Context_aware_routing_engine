from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.config import Settings


class OsrmErrorCode(StrEnum):
    NO_ROUTE = "no_route"
    TIMEOUT = "osrm_timeout"
    CONNECTION = "osrm_connection"
    SERVER_ERROR = "osrm_server_error"
    UNSUPPORTED_OPTION = "osrm_unsupported_option"
    PROTOCOL_ERROR = "osrm_protocol_error"
    INVALID_RESPONSE = "osrm_invalid_response"
    INVALID_GEOMETRY = "osrm_invalid_geometry"


class OsrmClientError(Exception):
    def __init__(self, code: OsrmErrorCode, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class OsrmTransientError(OsrmClientError):
    def __init__(self, code: OsrmErrorCode, message: str) -> None:
        super().__init__(code, message, retryable=True)


class OsrmProtocolError(OsrmClientError):
    def __init__(self, code: OsrmErrorCode, message: str) -> None:
        super().__init__(code, message, retryable=False)


class OsrmLineString(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["LineString"]
    coordinates: list[tuple[float, float]] = Field(min_length=2)

    @field_validator("coordinates", mode="before")
    @classmethod
    def validate_coordinate_shape(cls, value: Any) -> Any:
        if not isinstance(value, list):
            raise ValueError("LineString coordinates must be a list")
        for coordinate in value:
            if not isinstance(coordinate, (list, tuple)) or len(coordinate) != 2:
                raise ValueError("each LineString coordinate must contain longitude and latitude")
            longitude, latitude = coordinate
            if (
                isinstance(longitude, bool)
                or isinstance(latitude, bool)
                or not isinstance(longitude, (int, float))
                or not isinstance(latitude, (int, float))
                or not math.isfinite(longitude)
                or not math.isfinite(latitude)
                or not -180 <= longitude <= 180
                or not -90 <= latitude <= 90
            ):
                raise ValueError("LineString coordinates must be finite longitude/latitude values")
        return value


class OsrmManeuver(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    modifier: str | None = None
    location: tuple[float, float] | None = None


class OsrmStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    distance: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    duration: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    name: str = ""
    maneuver: OsrmManeuver


class OsrmLeg(BaseModel):
    model_config = ConfigDict(extra="ignore")

    steps: list[OsrmStep] = Field(default_factory=list)


class OsrmRouteCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    distance: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    duration: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    geometry: OsrmLineString
    legs: list[OsrmLeg] = Field(default_factory=list)

    @property
    def steps(self) -> list[OsrmStep]:
        return [step for leg in self.legs for step in leg.steps]


class OsrmResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str = Field(min_length=1)
    message: str | None = None
    routes: list[OsrmRouteCandidate] | None = Field(default=None, max_length=3)


@dataclass(frozen=True)
class OsrmRoutes:
    candidates: tuple[OsrmRouteCandidate, ...]

    @property
    def risk_choice_available(self) -> bool:
        return len(self.candidates) > 1


@dataclass(frozen=True)
class OsrmNoRoute:
    code: OsrmErrorCode = OsrmErrorCode.NO_ROUTE
    retryable: bool = False


OsrmResult = OsrmRoutes | OsrmNoRoute


def supported_exclusions(*, avoid_highways: bool, avoid_tolls: bool) -> str | None:
    exclusions = []
    if avoid_highways:
        exclusions.append("motorway")
    if avoid_tolls:
        exclusions.append("toll")
    return ",".join(exclusions) or None


class OsrmClient:
    def __init__(self, settings: Settings) -> None:
        timeout = httpx.Timeout(
            connect=settings.osrm_connect_timeout_seconds,
            read=settings.osrm_response_timeout_seconds,
            write=settings.osrm_response_timeout_seconds,
            pool=settings.osrm_connect_timeout_seconds,
        )
        limits = httpx.Limits(
            max_connections=settings.osrm_max_connections,
            max_keepalive_connections=settings.osrm_max_keepalive_connections,
        )
        self._client = httpx.Client(
            base_url=str(settings.osrm_base_url), timeout=timeout, limits=limits
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OsrmClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def request_routes(
        self,
        *,
        origin_longitude: float,
        origin_latitude: float,
        destination_longitude: float,
        destination_latitude: float,
        avoid_highways: bool,
        avoid_tolls: bool,
    ) -> OsrmResult:
        coordinate_path = (
            f"{origin_longitude},{origin_latitude};"
            f"{destination_longitude},{destination_latitude}"
        )
        params = {
            "alternatives": "3",
            "overview": "full",
            "geometries": "geojson",
            "steps": "true",
        }
        exclusions = supported_exclusions(
            avoid_highways=avoid_highways, avoid_tolls=avoid_tolls
        )
        if exclusions is not None:
            params["exclude"] = exclusions

        try:
            response = self._client.get(
                f"route/v1/driving/{coordinate_path}", params=params
            )
        except httpx.TimeoutException as error:
            raise OsrmTransientError(
                OsrmErrorCode.TIMEOUT, "OSRM did not respond before the configured timeout"
            ) from error
        except httpx.RequestError as error:
            raise OsrmTransientError(
                OsrmErrorCode.CONNECTION, "OSRM connection failed"
            ) from error

        if response.status_code >= 500:
            raise OsrmTransientError(
                OsrmErrorCode.SERVER_ERROR,
                f"OSRM returned HTTP {response.status_code}",
            )

        try:
            payload = response.json()
        except ValueError as error:
            raise OsrmProtocolError(
                OsrmErrorCode.INVALID_RESPONSE, "OSRM returned malformed JSON"
            ) from error

        try:
            parsed = OsrmResponse.model_validate(payload)
        except ValidationError as error:
            code = (
                OsrmErrorCode.INVALID_GEOMETRY
                if "geometry" in str(error) or "coordinates" in str(error)
                else OsrmErrorCode.INVALID_RESPONSE
            )
            raise OsrmProtocolError(code, "OSRM returned an invalid response") from error

        if response.status_code >= 400 or parsed.code != "Ok":
            if parsed.code == "NoRoute":
                return OsrmNoRoute()
            code = (
                OsrmErrorCode.UNSUPPORTED_OPTION
                if parsed.code == "InvalidOptions"
                else OsrmErrorCode.PROTOCOL_ERROR
            )
            raise OsrmProtocolError(code, f"OSRM rejected the request with {parsed.code}")

        if parsed.routes is None:
            raise OsrmProtocolError(
                OsrmErrorCode.INVALID_RESPONSE,
                "OSRM success response did not include routes",
            )
        if not parsed.routes:
            return OsrmNoRoute()
        return OsrmRoutes(candidates=tuple(parsed.routes))
