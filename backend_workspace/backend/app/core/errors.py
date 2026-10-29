"""Framework-free domain errors mapped to HTTP status and ``code`` by the API layer.

Services and everything below raise these; they never import FastAPI so the
worker can reuse the same services.
"""

from __future__ import annotations

from typing import Dict, Optional


class DomainError(Exception):
    """Base class for business errors carrying a contract status and code."""

    status_code: int = 400
    code: str = "invalid_request"
    title: str = "Invalid request"

    def __init__(
        self, detail: Optional[str] = None, headers: Optional[Dict[str, str]] = None
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        # Extra response headers (for example ``Retry-After``), applied by the API layer.
        self.headers = headers


class InvalidRequest(DomainError):
    """Structurally invalid request (400)."""


class ValidationFailed(DomainError):
    """Well-formed request with invalid values (422)."""

    status_code = 422
    code = "validation_failed"
    title = "Validation failed"


class InvalidCursor(DomainError):
    """Pagination cursor is malformed or tampered with (422)."""

    status_code = 422
    code = "invalid_cursor"
    title = "Invalid cursor"


class Unauthenticated(DomainError):
    """Missing or invalid credentials (401)."""

    status_code = 401
    code = "unauthorized"
    title = "Authentication required"

    def __init__(
        self, detail: Optional[str] = None, headers: Optional[Dict[str, str]] = None
    ) -> None:
        super().__init__(detail, headers or {"WWW-Authenticate": "Bearer"})


class Forbidden(DomainError):
    """Authenticated principal lacks permission (403)."""

    status_code = 403
    code = "forbidden"
    title = "Forbidden"


class NotFound(DomainError):
    """Resource does not exist or is not visible (404)."""

    status_code = 404
    code = "not_found"
    title = "Not found"


class Conflict(DomainError):
    """Request conflicts with current state (409)."""

    status_code = 409
    code = "conflict"
    title = "Conflict"


class AssetNotFlagged(Conflict):
    """Work order requested for an asset without an open alert (409)."""

    code = "asset_not_flagged"
    title = "Asset is not flagged"


class AssetInactive(Conflict):
    """Work order requested for a deactivated asset (409)."""

    code = "asset_inactive"
    title = "Asset is inactive"


class AlertMismatch(Conflict):
    """A supplied alert is not the asset's current unresolved episode (409)."""

    code = "alert_mismatch"
    title = "Alert does not match the asset's current episode"


class InvalidTransition(Conflict):
    """Forbidden work-order status transition (409)."""

    code = "invalid_transition"
    title = "Invalid status transition"


class CaseComplete(Conflict):
    """A terminal work order was supplied with a further mutation (409)."""

    code = "case_complete"
    title = "Case is complete"


class IdempotencyConflict(Conflict):
    """Idempotency key reused with a different request body (409)."""

    code = "idempotency_conflict"
    title = "Idempotency key reused with a different request"


class VersionMismatch(DomainError):
    """If-Match version does not match the stored row version (412)."""

    status_code = 412
    code = "precondition_failed"
    title = "Version mismatch"


class PreconditionRequired(DomainError):
    """A required If-Match header is missing (428)."""

    status_code = 428
    code = "precondition_required"
    title = "If-Match header required"


class PayloadTooLarge(DomainError):
    """Request body exceeds the configured limit (413)."""

    status_code = 413
    code = "payload_too_large"
    title = "Payload too large"


class UnsupportedMediaType(DomainError):
    """Unsupported Content-Type (415)."""

    status_code = 415
    code = "unsupported_media_type"
    title = "Unsupported media type"


class TooManyRequests(DomainError):
    """Throttled request (429)."""

    status_code = 429
    code = "rate_limited"
    title = "Too many requests"

    def __init__(self, detail: Optional[str] = None, retry_after_s: int = 60) -> None:
        super().__init__(detail, {"Retry-After": str(max(1, int(retry_after_s)))})


class ServiceUnavailable(DomainError):
    """A dependency such as the database is unavailable (503)."""

    status_code = 503
    code = "unavailable"
    title = "Service unavailable"
