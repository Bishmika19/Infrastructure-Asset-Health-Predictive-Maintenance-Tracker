"""Problem+json responses and exception handlers (ADR-H002, DEC-11)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import DomainError
from app.core.logging import request_id_var

logger = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"

# Pydantic error types that mean the request is structurally wrong (400),
# as opposed to carrying an invalid value (422).
_STRUCTURAL_ERROR_TYPES = {
    "extra_forbidden",
    "json_invalid",
    "missing",
    "model_type",
    "model_attributes_type",
    "dict_type",
}

_STATUS_CODES = {
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
}


# PUBLIC_INTERFACE
def problem_response(
    status: int,
    code: str,
    title: str,
    detail: Optional[str] = None,
    errors: Optional[List[Dict[str, Any]]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    """Build an RFC 7807 problem+json response carrying ``code`` and ``requestId``."""
    body: Dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "code": code,
        "requestId": request_id_var.get(),
    }
    if detail:
        body["detail"] = detail
    if errors:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type=PROBLEM_MEDIA_TYPE, headers=headers)


async def _domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    return problem_response(
        exc.status_code, exc.code, exc.title, exc.detail, headers=exc.headers
    )


async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Map extra fields and malformed JSON to 400, value errors to 422."""
    errors = [
        {"loc": [str(part) for part in err.get("loc", ())], "type": err.get("type", "")}
        for err in exc.errors()
    ]
    structural = any(err["type"] in _STRUCTURAL_ERROR_TYPES for err in errors)
    if structural:
        return problem_response(400, "invalid_request", "Invalid request", errors=errors)
    return problem_response(422, "validation_failed", "Validation failed", errors=errors)


async def _http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _STATUS_CODES.get(exc.status_code, "http_error")
    return problem_response(exc.status_code, code, str(exc.detail), headers=exc.headers)


async def _unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
    """Never leak SQL, stack traces or internals in 500 responses."""
    logger.error("unhandled error", exc_info=exc)
    return problem_response(500, "internal_error", "Internal server error")


# PUBLIC_INTERFACE
def register_problem_handlers(app: FastAPI) -> None:
    """Install the problem+json handlers on the application."""
    app.add_exception_handler(DomainError, _domain_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_handler)  # type: ignore
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore
    app.add_exception_handler(Exception, _unhandled_handler)
