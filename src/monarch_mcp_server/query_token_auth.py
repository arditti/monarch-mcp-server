"""ASGI middleware: accept the bearer token via a ``?token=`` query param.

Custom MCP connectors (Claude Desktop's and Claude mobile's "Remote MCP
server URL" field) only take a URL — there's no way to set a custom
header. mindbody-mcp solved this in its own hand-rolled HTTP layer (a
``?token=`` query param, checked only when no Authorization header is
present); this is the FastMCP/ASGI-layer equivalent, since the MCP Python
SDK's built-in ``BearerAuthBackend`` only ever reads the Authorization
header.

This wraps the ASGI app FastMCP already builds — it does not modify the
``mcp`` package, which stays a stock, general-purpose dependency.
"""

from urllib.parse import parse_qs

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send


class QueryTokenAuthMiddleware:
    """Copies ``?token=`` into the Authorization header before the wrapped
    app sees the request — only when no Authorization header is already
    present, so an explicit header always wins."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = MutableHeaders(scope=scope)
        if not headers.get("authorization"):
            query = parse_qs(scope.get("query_string", b"").decode())
            token = query.get("token", [None])[0]
            if token:
                headers["authorization"] = f"Bearer {token}"

        await self.app(scope, receive, send)
