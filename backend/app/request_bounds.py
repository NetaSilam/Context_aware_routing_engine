from __future__ import annotations

from collections.abc import Collection

from fastapi import HTTPException, Request, status
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class RequestSizeLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int,
        max_query_bytes: int,
        media_max_body_bytes: int | None = None,
        media_path_suffix: str = "/media",
        media_path_prefixes: Collection[str] = (),
    ) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.max_query_bytes = max_query_bytes
        self.media_max_body_bytes = media_max_body_bytes
        self.media_path_suffix = media_path_suffix
        self.media_path_prefixes = tuple(media_path_prefixes)

    def _effective_max_body_bytes(self, scope: Scope) -> int:
        # Media-upload endpoints validate their own tighter, content-type-specific limits;
        # this middleware only needs to admit a request large enough to reach that check
        # instead of rejecting every upload at the small default JSON-body ceiling. Some
        # endpoints (e.g. direct messages) accept an optional attachment directly rather than
        # through a dedicated "/media" sub-route, so prefix matches are supported too.
        if self.media_max_body_bytes is not None:
            path = str(scope.get("path", ""))
            if path.endswith(self.media_path_suffix) or path.startswith(self.media_path_prefixes):
                return self.media_max_body_bytes
        return self.max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if len(scope.get("query_string", b"")) > self.max_query_bytes:
            await JSONResponse(
                status_code=status.HTTP_414_REQUEST_URI_TOO_LONG,
                content={"detail": "Request query is too long."},
            )(scope, receive, send)
            return
        effective_max_body_bytes = self._effective_max_body_bytes(scope)
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                too_large = int(content_length) > effective_max_body_bytes
            except ValueError:
                too_large = True
            if too_large:
                await JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={"detail": "Request body is too large."},
                )(scope, receive, send)
                return

        messages = []
        received_bytes = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            received_bytes += len(message.get("body", b""))
            if received_bytes > effective_max_body_bytes:
                await JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={"detail": "Request body is too large."},
                )(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        async def replay_receive():
            if messages:
                return messages.pop(0)
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)


def reject_unexpected_query_parameters(
    request: Request, allowed_parameters: Collection[str]
) -> None:
    unexpected = set(request.query_params) - set(allowed_parameters)
    if unexpected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported query parameter: {sorted(unexpected)[0]}",
        )
