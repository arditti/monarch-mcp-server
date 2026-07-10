"""FastMCP application instance and entry point.

The run mode (stdio vs serve) must be known before the FastMCP instance is
created: auth settings are constructor-only, and tool modules register
against the instance at import time. ``cli.main`` resolves the mode into
``MONARCH_MCP_MODE`` before importing this module.
"""

import logging

from mcp.server.fastmcp import FastMCP

from monarch_mcp_server.config import ServeConfig, get_mode

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# The gql aiohttp transport logs full GraphQL requests/responses at INFO, which
# can include Monarch account payloads. Raise its floor to WARNING so those
# payloads are not written to logs. Transport-level errors still surface; drop
# this to INFO/DEBUG temporarily if you need to trace GraphQL traffic.
logging.getLogger("gql.transport.aiohttp").setLevel(logging.WARNING)

MODE = get_mode()

# Populated by _build_mcp() in serve mode; read by the /setup route below.
_serve_cfg: ServeConfig | None = None


def _build_mcp() -> FastMCP:
    if MODE != "serve":
        return FastMCP("Monarch Money MCP Server")

    from mcp.server.auth.settings import AuthSettings
    from mcp.server.transport_security import TransportSecuritySettings

    from monarch_mcp_server.http_auth import StaticTokenVerifier

    global _serve_cfg
    cfg = ServeConfig.from_env()
    _serve_cfg = cfg
    return FastMCP(
        "Monarch Money MCP Server",
        host=cfg.host,
        port=cfg.port,
        # Plain JSON tool responses survive buffering proxies that break SSE.
        json_response=True,
        token_verifier=StaticTokenVerifier(cfg.auth_token),
        auth=AuthSettings(
            issuer_url=cfg.issuer_url,
            resource_server_url=cfg.issuer_url,
        ),
        # DNS-rebinding protection only makes sense when the operator says
        # which Host values are legitimate; with no allowlist it would reject
        # every request.
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=bool(cfg.allowed_hosts),
            allowed_hosts=cfg.allowed_hosts,
        ),
    )


mcp = _build_mcp()

if MODE == "serve":
    from starlette.requests import Request
    from starlette.responses import HTMLResponse, PlainTextResponse

    from monarch_mcp_server.setup_page import render_setup_page

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_: Request) -> PlainTextResponse:
        # Liveness only — no version or config details.
        return PlainTextResponse("ok")

    @mcp.custom_route("/setup", methods=["GET"])
    async def setup(_: Request) -> HTMLResponse:
        # No auth of our own here — this path must sit behind Cloudflare
        # Access at the edge (see docs/SECRETS.md in home-infra). Custom
        # routes bypass the MCP transport's bearer-token check entirely,
        # same as /healthz.
        assert _serve_cfg is not None
        return HTMLResponse(render_setup_page(_serve_cfg))


# Import tools package to trigger @mcp.tool() registration
import monarch_mcp_server.tools  # noqa: E402, F401

# Export for `mcp run`
app = mcp


def main() -> None:
    """Main entry point for the server."""
    logger.info("Starting Monarch Money MCP Server...")
    try:
        mcp.run()
    except Exception as e:
        logger.error(f"Failed to run server: {str(e)}")
        raise
