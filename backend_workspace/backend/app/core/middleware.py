"""Request ID, body-size limit and content-type guard as one ASGI middleware."""

from __future__ import annotations

import re
import uuid
from typing import Awaitable, Callable, Dict, MutableMapping

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_var
from app.core.problem import problem_response

_BODY_METHODS = {"POST", "PUT", "PATCH"}
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# Routes that legitimately accept multipart (photo upload on inspections).
_MULTIPART_PATH = re.compile(r"/inspections/?$")


class _BodyTooLarge(Exception):
    """Raised inside the receive wrapper when the streamed body exceeds the limit."""


class RequestGuardMiddleware:
    """Assign a request ID, enforce body limits (413) and content types (415)."""

    def __init__(self, app: ASGIApp, max_json_bytes: int, max_multipart_bytes: int) -> None:
        self.app = app
        self.max_json_bytes = max_json_bytes
        self.max_multipart_bytes = max_multipart_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers: Dict[str, str] = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]
        }
        incoming = headers.get("x-request-id", "")
        request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = response_headers
            await send(message)

        try:
            rejection = self._reject(scope, headers)
            if rejection is not None:
                await rejection(scope, receive, send_with_id)
                return
            limit = self._limit_for(scope, headers)
            await self._run_limited(scope, receive, send_with_id, limit)
        finally:
            request_id_var.reset(token)

    def _is_multipart(self, scope: Scope, headers: MutableMapping[str, str]) -> bool:
        content_type = headers.get("content-type", "").lower()
        return content_type.startswith("multipart/form-data") and bool(
            _MULTIPART_PATH.search(scope["path"])
        )

    def _limit_for(self, scope: Scope, headers: MutableMapping[str, str]) -> int:
        return self.max_multipart_bytes if self._is_multipart(scope, headers) else self.max_json_bytes

    def _reject(self, scope: Scope, headers: MutableMapping[str, str]):
        """Return a response app when the request must be rejected up front."""
        if scope["method"] not in _BODY_METHODS:
            return None
        length_raw = headers.get("content-length")
        has_body = headers.get("transfer-encoding") is not None or (
            length_raw is not None and length_raw.isdigit() and int(length_raw) > 0
        )
        if not has_body:
            return None
        content_type = headers.get("content-type", "").lower()
        if not (content_type.startswith("application/json") or self._is_multipart(scope, headers)):
            return problem_response(
                415, "unsupported_media_type", "Unsupported media type",
                "Use Content-Type: application/json.",
            )
        if length_raw and length_raw.isdigit() and int(length_raw) > self._limit_for(scope, headers):
            return problem_response(413, "payload_too_large", "Payload too large")
        return None

    async def _run_limited(self, scope: Scope, receive: Receive, send: Send, limit: int) -> None:
        """Run the app while counting streamed bytes against the limit."""
        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not started:
                await problem_response(413, "payload_too_large", "Payload too large")(
                    scope, receive, send
                )


MiddlewareFactory = Callable[[ASGIApp], Awaitable[None]]
