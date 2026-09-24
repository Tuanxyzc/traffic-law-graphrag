"""Global exception handlers converting errors to standardized JSON responses."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from src.api.schemas.common import ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handles Pydantic validation errors and returns 422 with structured details."""
    details: list[ErrorDetail] = []
    for err in exc.errors():
        loc = list(err.get("loc", []))
        msg = err.get("msg", "Validation error")
        code = err.get("type", "VALIDATION_ERROR")
        details.append(ErrorDetail(code=code, message=msg, location=loc))

    req_id = getattr(request.state, "request_id", None)
    error_payload = ErrorResponse(
        success=False,
        error="Dữ liệu yêu cầu không hợp lệ (Request Validation Error)",
        code="UNPROCESSABLE_ENTITY",
        details=details,
        request_id=req_id,
    )
    return JSONResponse(
        status_code=422,
        content=error_payload.model_dump(),
    )


async def neo4j_exception_handler(request: Request, exc: Neo4jError) -> JSONResponse:
    """Handles Neo4j driver and connectivity exceptions."""
    req_id = getattr(request.state, "request_id", None)
    logger.error("Neo4j database error: %s (req_id: %s)", exc, req_id)
    error_payload = ErrorResponse(
        success=False,
        error="Cơ sở dữ liệu đồ thị tri thức tạm thời không khả dụng",
        code="DATABASE_UNAVAILABLE",
        details=[ErrorDetail(code="NEO4J_ERROR", message=str(exc))],
        request_id=req_id,
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=error_payload.model_dump(),
    )


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all unhandled exception handler."""
    req_id = getattr(request.state, "request_id", None)
    logger.critical("Unhandled internal server error: %s (req_id: %s)", exc, req_id)
    error_payload = ErrorResponse(
        success=False,
        error="Đã xảy ra lỗi nội bộ trên máy chủ (Internal Server Error)",
        code="INTERNAL_SERVER_ERROR",
        details=[ErrorDetail(code="SERVER_ERROR", message=str(exc))],
        request_id=req_id,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_payload.model_dump(),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Registers custom exception handlers on FastAPI application."""
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ServiceUnavailable, neo4j_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Neo4jError, neo4j_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, global_exception_handler)
