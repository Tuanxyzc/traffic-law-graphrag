"""Common schemas used across API endpoints."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class BaseResponse(BaseModel, Generic[T]):
    """Standardized API response wrapper."""

    success: bool = True
    message: str = "Operation completed successfully"
    data: T | None = None


class ErrorDetail(BaseModel):
    """Structured error detail representation."""

    code: str
    message: str
    location: list[str | int] | None = None


class ErrorResponse(BaseModel):
    """Standardized API error response format."""

    success: bool = False
    error: str
    code: str = "INTERNAL_ERROR"
    details: list[ErrorDetail] = Field(default_factory=list)
    request_id: str | None = None


class PaginationParams(BaseModel):
    """Standard pagination query parameters."""

    skip: int = Field(default=0, ge=0, description="Offset of records to skip")
    limit: int = Field(default=20, ge=1, le=100, description="Maximum records to return")
