from __future__ import annotations

from fastapi import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings
from app.core.auth import validate_csrf_value


class RequestTooLarge(Exception):
    pass


class RequestSizeLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length) > settings.max_request_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                pass

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > settings.max_request_bytes:
                    raise RequestTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestTooLarge:
            await self._reject(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit_mib = settings.max_request_bytes / (1024 * 1024)
        response = JSONResponse(
            status_code=413,
            content={
                "detail": (
                    f"Request exceeds the {limit_mib:g} MiB limit. Reduce the submitted "
                    "content or split it across multiple memories, then retry."
                )
            },
        )
        await response(scope, receive, send)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in {"/docs", "/redoc"}:
            content_security_policy = (
                b"default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                b"style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                b"img-src 'self' data: https://fastapi.tiangolo.com; object-src 'none'; "
                b"base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            )
        else:
            content_security_policy = (
                b"default-src 'self'; script-src 'self'; style-src 'self'; "
                b"img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                b"base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            )

        async def secure_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                        (
                            b"content-security-policy",
                            content_security_policy,
                        ),
                    ]
                )
                if not path.startswith("/dashboard-assets/"):
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, secure_send)


class DashboardCSRFMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        method = scope.get("method", "GET").upper()
        path = scope.get("path", "")
        if scope["type"] == "http" and path.startswith("/dashboard/api/") and method not in {
            "GET",
            "HEAD",
            "OPTIONS",
        }:
            request = Request(scope, receive=receive)
            if not validate_csrf_value(
                request.cookies.get(settings.csrf_cookie_name),
                request.headers.get("X-CSRF-Token"),
            ):
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "Dashboard security token is missing or invalid. Refresh and retry."},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"
