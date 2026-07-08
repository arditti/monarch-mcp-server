"""Run-mode resolution and serve-mode configuration.

Mode must be resolved before ``app.py`` is imported: FastMCP accepts auth
settings only at construction, and tools register at import time.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

MODE_ENV = "MONARCH_MCP_MODE"
MIN_TOKEN_LENGTH = 32


def get_mode() -> str:
    """Return the run mode: "stdio" (default) or "serve"."""
    mode = os.environ.get(MODE_ENV, "stdio").strip().lower()
    if mode not in ("stdio", "serve"):
        raise ValueError(
            f"{MODE_ENV} must be 'stdio' or 'serve', got {mode!r}"
        )
    return mode


@dataclass(frozen=True)
class ServeConfig:
    """Configuration for serve (streamable HTTP) mode, read from env vars."""

    host: str
    port: int
    auth_token: str
    issuer_url: str
    allowed_hosts: List[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "ServeConfig":
        host = os.environ.get("MONARCH_MCP_HOST", "127.0.0.1")
        port = int(os.environ.get("MONARCH_MCP_PORT", "8000"))

        token = ""
        token_file = os.environ.get("MONARCH_MCP_AUTH_TOKEN_FILE")
        if token_file:
            token = Path(token_file).read_text().strip()
        if not token:
            token = os.environ.get("MONARCH_MCP_AUTH_TOKEN", "").strip()
        if not token:
            raise ValueError(
                "Serve mode requires MONARCH_MCP_AUTH_TOKEN or "
                "MONARCH_MCP_AUTH_TOKEN_FILE. Generate one with: "
                "openssl rand -base64 33"
            )
        if len(token) < MIN_TOKEN_LENGTH:
            raise ValueError(
                f"Auth token must be at least {MIN_TOKEN_LENGTH} characters "
                f"(got {len(token)}). Generate one with: openssl rand -base64 33"
            )

        issuer_url = os.environ.get(
            "MONARCH_MCP_PUBLIC_URL", f"http://{host}:{port}"
        ).rstrip("/")

        raw_hosts = os.environ.get("MONARCH_MCP_ALLOWED_HOSTS", "")
        allowed_hosts = [h.strip() for h in raw_hosts.split(",") if h.strip()]

        return cls(
            host=host,
            port=port,
            auth_token=token,
            issuer_url=issuer_url,
            allowed_hosts=allowed_hosts,
        )
