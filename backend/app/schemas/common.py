"""Shared public API schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    """Base for every public response/request model."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class ErrorBody(ApiModel):
    code: str = Field(examples=["INVALID_STATION"])
    message: str = Field(examples=["The supplied station code is not recognized."])
    request_id: str | None = Field(default=None, examples=["5c1f0c4f9a6e4c1e8f0f3b2c6d7e8f90"])
    details: dict[str, Any] | None = None


class ErrorResponse(ApiModel):
    """Doc 05 §7 error envelope."""

    error: ErrorBody


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorResponse, "description": description}
    for status, description in {
        400: "Invalid request",
        404: "Not found",
        422: "Semantically invalid request",
        429: "Rate or usage limit reached",
        502: "Provider returned an invalid response",
        503: "Provider or dependency unavailable",
        504: "Provider timeout",
    }.items()
}
