"""Pure-ASGI middleware: request IDs, body-size limit, baseline security headers, access log."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import request_id_var

logger = logging.getLogger("app.access")

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_QUIET_PATH_PREFIXES = ("/api/v1/health",)


class RequestBodyTooLargeError(Exception):
    """Raised while streaming a request body that exceeds the configured limit."""


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        incoming = headers.get("x-request-id", "")
        request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_holder: dict[str, int] = {"status": 500}

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                response_headers = MutableHeaders(scope=message)
                response_headers["X-Request-ID"] = request_id
                response_headers.setdefault("X-Content-Type-Options", "nosniff")
                response_headers.setdefault("Referrer-Policy", "no-referrer")
                response_headers.setdefault("X-Frame-Options", "DENY")
                response_headers.setdefault("Cache-Control", "no-store")
            await send(message)

        try:
            declared = headers.get("content-length")
            if declared is not None and declared.isdigit() and int(declared) > self.max_body_bytes:
                await self._reject_too_large(send_with_headers, request_id)
                return

            received = 0

            async def limited_receive() -> Message:
                nonlocal received
                message = await receive()
                if message["type"] == "http.request":
                    received += len(message.get("body", b""))
                    if received > self.max_body_bytes:
                        raise RequestBodyTooLargeError
                return message

            await self.app(scope, limited_receive, send_with_headers)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            path = scope.get("path", "")
            level = logging.DEBUG if path.startswith(_QUIET_PATH_PREFIXES) else logging.INFO
            logger.log(
                level,
                "request completed",
                extra={
                    "method": scope.get("method"),
                    "path": path,
                    "status": status_holder["status"],
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)

    async def _reject_too_large(self, send: Send, request_id: str) -> None:
        body = json.dumps(
            {
                "error": {
                    "code": "REQUEST_TOO_LARGE",
                    "message": "The request body is too large.",
                    "request_id": request_id,
                }
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
