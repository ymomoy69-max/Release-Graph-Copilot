"""Consistent API error responses."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def error_body(
    request: Request,
    status: int,
    error: str,
    message: str,
) -> dict:
    rid = getattr(request.state, "request_id", None)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "error": error,
        "message": message,
        "path": request.url.path,
        "requestId": rid,
    }


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = "HTTP_ERROR"
    if exc.status_code == 401:
        code = "UNAUTHORIZED"
    elif exc.status_code == 403:
        code = "FORBIDDEN"
    elif exc.status_code == 404:
        code = "NOT_FOUND"
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(request, exc.status_code, code, str(exc.detail)),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_body(request, 422, "VALIDATION_ERROR", "Invalid request"),
    )
