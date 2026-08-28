"""Console entry point.

Parses argv and resolves the run mode into MONARCH_MCP_MODE *before*
importing ``app`` — FastMCP auth settings are constructor-only and tools
register at import time, so the mode cannot change after that import.
"""

import argparse
import os
import sys
from typing import Callable, List, Optional


def _load_app():
    from monarch_mcp_server import app

    return app


def _default_serve_http(app) -> None:
    """Serve the streamable-HTTP ASGI app ourselves (instead of
    ``app.mcp.run(transport=...)``) so we can wrap it with
    QueryTokenAuthMiddleware — FastMCP's own run method has no hook for
    that. The `mcp` package itself is untouched; this only wraps the ASGI
    app it hands back."""
    import uvicorn

    from monarch_mcp_server.query_token_auth import QueryTokenAuthMiddleware

    asgi_app = QueryTokenAuthMiddleware(app.mcp.streamable_http_app())
    settings = app.mcp.settings
    uvicorn.run(
        asgi_app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


def main(
    argv: Optional[List[str]] = None,
    _app_loader: Callable = _load_app,
    _serve_http: Callable = _default_serve_http,
) -> None:
    args = sys.argv[1:] if argv is None else argv

    if args and args[0] == "serve":
        parser = argparse.ArgumentParser(
            prog="monarch-mcp-server serve",
            description="Run over streamable HTTP with bearer-token auth.",
        )
        parser.add_argument("--host", help="Bind address (default 127.0.0.1)")
        parser.add_argument("--port", type=int, help="Bind port (default 8000)")
        parsed = parser.parse_args(args[1:])

        os.environ["MONARCH_MCP_MODE"] = "serve"
        if parsed.host:
            os.environ["MONARCH_MCP_HOST"] = parsed.host
        if parsed.port is not None:
            os.environ["MONARCH_MCP_PORT"] = str(parsed.port)

        app = _app_loader()
        _serve_http(app)
        return

    if args and args[0] == "login-cookies":
        parser = argparse.ArgumentParser(
            prog="monarch-mcp-server login-cookies",
            description=(
                "Save a Monarch session from a browser Cookie header read "
                "on stdin (non-interactive login_setup.py option 1)."
            ),
        )
        parser.parse_args(args[1:])

        from monarch_mcp_server.login_cookies import main as login_cookies_main

        login_cookies_main()
        return

    if args and args[0] == "login-password":
        parser = argparse.ArgumentParser(
            prog="monarch-mcp-server login-password",
            description=(
                "Save a Monarch session from newline-separated credentials "
                "on stdin: email, password, optional one-time code "
                "(non-interactive login_setup.py option 2)."
            ),
        )
        parser.parse_args(args[1:])

        from monarch_mcp_server.login_password import main as login_password_main

        login_password_main()
        return

    # Default: stdio, exactly as before.
    app = _app_loader()
    app.main()
