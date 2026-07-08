# Remote HTTP Access (Phase 1a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `serve` mode that exposes the existing MCP server over streamable HTTP with static bearer-token auth, deployable via Docker behind Cloudflare Tunnel or any reverse proxy, while leaving stdio mode byte-for-byte compatible.

**Architecture:** Mode is resolved from CLI/env *before* `app.py` is imported (FastMCP auth is constructor-only). A new `cli.py` dispatcher sets `MONARCH_MCP_MODE` then imports `app`, which builds `FastMCP` with a `StaticTokenVerifier` in serve mode. Login MCP tools are not registered in serve mode; Monarch sessions come from `login_setup.py` run on the host (cookie-paste primary). Session storage is unchanged (keyring/file).

**Tech Stack:** Python 3.12, `mcp>=1.28,<2` (FastMCP, streamable HTTP, TokenVerifier), uvicorn (ships with `mcp[cli]`), Docker multi-arch, pytest.

**Spec:** `docs/superpowers/specs/2026-07-08-remote-http-phase1a-design.md`

## Global Constraints

- `mcp>=1.28,<2` (1.13.x has a session/credential binding hole in stateful HTTP).
- `requires-python = ">=3.12,<3.14"` — unchanged.
- Stdio mode must keep working with zero behavior change (existing tests keep passing unmodified except where a test asserts import-time keyring probing).
- Auth token: min 32 chars, compared with `hmac.compare_digest`, sourced from `MONARCH_MCP_AUTH_TOKEN_FILE` (precedence) or `MONARCH_MCP_AUTH_TOKEN`. Serve mode refuses to start without it.
- Serve mode: `json_response=True`, stateful sessions (default), no proxy-header trust, global (not per-IP) auth-failure throttle.
- `/healthz` returns exactly `ok`, unauthenticated, no version info.
- Serve mode never registers: `setup_authentication`, `monarch_login`, `monarch_login_with_token`, `monarch_logout`, `debug_session_loading`. It DOES register `check_auth_status`.
- No new runtime Python dependencies.
- Spec deviation (documented): the SDK requires `AuthSettings.issuer_url` even in TokenVerifier-only mode, so serve mode accepts optional `MONARCH_MCP_PUBLIC_URL` (default `http://127.0.0.1:<port>`). It only affects the RFC 9728 metadata advertised in 401 responses; static-token clients ignore it.
- Commit messages: plain, no AI attribution of any kind.
- Repo uses `uv` (uv.lock present). Run tests with `uv run pytest`; sync with `uv sync --extra dev`.

## File Structure

- Create: `src/monarch_mcp_server/config.py` — mode resolution + `ServeConfig`
- Create: `src/monarch_mcp_server/http_auth.py` — `StaticTokenVerifier`
- Create: `src/monarch_mcp_server/cli.py` — entry-point dispatcher (parses argv before importing `app`)
- Modify: `src/monarch_mcp_server/app.py` — mode-aware FastMCP construction, `/healthz`
- Modify: `src/monarch_mcp_server/secure_session.py` — lazy keyring probe
- Modify: `src/monarch_mcp_server/tools/auth.py` — conditional login-tool registration
- Modify: `pyproject.toml` — mcp floor, entry point → `cli:main`
- Create: `tests/test_config.py`, `tests/test_http_auth.py`, `tests/test_serve_http.py`
- Create: `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `scripts/e2e_http.py`
- Modify: `README.md`, `requirements.txt`

---

### Task 1: Upgrade MCP SDK to >=1.28,<2

**Files:**
- Modify: `pyproject.toml:23` (`"mcp[cli]>=1.10.0"` → `"mcp[cli]>=1.28,<2"`)
- Modify: `requirements.txt` (mcp line, if pinned)

**Interfaces:**
- Produces: an environment where `from mcp.server.auth.provider import TokenVerifier, AccessToken`, `from mcp.server.auth.settings import AuthSettings`, and `from mcp.server.transport_security import TransportSecuritySettings` all import.

- [ ] **Step 1: Bump the constraint**

In `pyproject.toml` dependencies, change `"mcp[cli]>=1.10.0"` to `"mcp[cli]>=1.28,<2"`. Check `requirements.txt` for an `mcp` line and align it if present.

- [ ] **Step 2: Re-lock and sync**

Run: `uv sync --extra dev`
Expected: resolves mcp to 1.28.x, no conflicts.

- [ ] **Step 3: Verify new APIs import**

Run: `uv run python -c "from mcp.server.auth.provider import TokenVerifier, AccessToken; from mcp.server.auth.settings import AuthSettings; from mcp.server.transport_security import TransportSecuritySettings; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Run the full existing suite**

Run: `uv run pytest`
Expected: all existing tests pass. If any fail from SDK API drift (e.g. elicitation interfaces in `auth.py`), fix the call sites minimally and note it in the commit message.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock requirements.txt
git commit -m "Upgrade mcp SDK to >=1.28,<2 for streamable HTTP session-credential binding"
```

---

### Task 2: Lazy keyring probe in SecureMonarchSession

**Files:**
- Modify: `src/monarch_mcp_server/secure_session.py:64-69` (`__init__`) and every `self._use_keyring` read (lines 131, 177, 221)
- Test: `tests/test_secure_session.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `SecureMonarchSession()` construction performs no keyring access; probing happens on first `save_session_blob`/`load_session`/`delete_token` call via the private property `_keyring_ok: bool`. Public API unchanged.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_secure_session.py`:

```python
class TestLazyKeyringProbe:
    def test_constructor_does_not_probe_keyring(self):
        from monarch_mcp_server import secure_session as ss

        with patch.object(ss, "_keyring_available") as probe:
            ss.SecureMonarchSession()
            probe.assert_not_called()

    def test_first_use_probes_keyring_once(self, tmp_path):
        from monarch_mcp_server import secure_session as ss

        with patch.object(ss, "_keyring_available", return_value=False) as probe, \
             patch.object(ss, "_TOKEN_DIR", tmp_path), \
             patch.object(ss, "_TOKEN_FILE", tmp_path / "token"):
            session = ss.SecureMonarchSession()
            session.load_session()
            session.load_session()
            assert probe.call_count == 1
```

(`patch` is already imported in this test file; if not, add `from unittest.mock import patch`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_secure_session.py::TestLazyKeyringProbe -v`
Expected: FAIL — constructor currently calls `_keyring_available()`.

- [ ] **Step 3: Implement the lazy probe**

Replace `__init__` in `secure_session.py`:

```python
    def __init__(self) -> None:
        # Keyring availability is probed lazily on first use. Probing in the
        # constructor triggers keyring access (a macOS Keychain prompt in some
        # setups) for any import of this package, even when the session store
        # is never used (e.g. serve mode).
        self._use_keyring: Optional[bool] = None

    @property
    def _keyring_ok(self) -> bool:
        if self._use_keyring is None:
            self._use_keyring = _keyring_available()
            if self._use_keyring:
                logger.info("🔐 Using system keyring for token storage")
            else:
                logger.info("🔐 Keyring unavailable — using file-based token storage")
        return self._use_keyring
```

Then replace the three reads: `if self._use_keyring:` → `if self._keyring_ok:` in `save_session_blob`, `load_session`, and `delete_token`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_secure_session.py -v`
Expected: PASS (all, including pre-existing tests).

- [ ] **Step 5: Commit**

```bash
git add src/monarch_mcp_server/secure_session.py tests/test_secure_session.py
git commit -m "Probe keyring lazily instead of at import time"
```

---

### Task 3: Mode resolution and serve configuration (`config.py`)

**Files:**
- Create: `src/monarch_mcp_server/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: environment variables only.
- Produces:
  - `get_mode() -> str` — returns `"stdio"` or `"serve"` from `MONARCH_MCP_MODE` (default `"stdio"`; unknown values raise `ValueError`).
  - `ServeConfig` frozen dataclass: `host: str`, `port: int`, `auth_token: str`, `issuer_url: str`, `allowed_hosts: list[str]`; classmethod `from_env() -> ServeConfig` raising `ValueError` on missing/short token.
  - `MIN_TOKEN_LENGTH = 32` constant (Task 4 reuses it).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config.py`:

```python
"""Tests for mode resolution and serve configuration."""

import pytest

from monarch_mcp_server.config import MIN_TOKEN_LENGTH, ServeConfig, get_mode

VALID_TOKEN = "x" * MIN_TOKEN_LENGTH


class TestGetMode:
    def test_default_is_stdio(self, monkeypatch):
        monkeypatch.delenv("MONARCH_MCP_MODE", raising=False)
        assert get_mode() == "stdio"

    def test_serve_from_env(self, monkeypatch):
        monkeypatch.setenv("MONARCH_MCP_MODE", "serve")
        assert get_mode() == "serve"

    def test_unknown_mode_raises(self, monkeypatch):
        monkeypatch.setenv("MONARCH_MCP_MODE", "bananas")
        with pytest.raises(ValueError, match="MONARCH_MCP_MODE"):
            get_mode()


class TestServeConfig:
    def _clear(self, monkeypatch):
        for var in (
            "MONARCH_MCP_AUTH_TOKEN",
            "MONARCH_MCP_AUTH_TOKEN_FILE",
            "MONARCH_MCP_HOST",
            "MONARCH_MCP_PORT",
            "MONARCH_MCP_PUBLIC_URL",
            "MONARCH_MCP_ALLOWED_HOSTS",
        ):
            monkeypatch.delenv(var, raising=False)

    def test_defaults(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("MONARCH_MCP_AUTH_TOKEN", VALID_TOKEN)
        cfg = ServeConfig.from_env()
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 8000
        assert cfg.auth_token == VALID_TOKEN
        assert cfg.issuer_url == "http://127.0.0.1:8000"
        assert cfg.allowed_hosts == []

    def test_missing_token_raises(self, monkeypatch):
        self._clear(monkeypatch)
        with pytest.raises(ValueError, match="MONARCH_MCP_AUTH_TOKEN"):
            ServeConfig.from_env()

    def test_short_token_raises(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("MONARCH_MCP_AUTH_TOKEN", "short")
        with pytest.raises(ValueError, match="32"):
            ServeConfig.from_env()

    def test_token_file_takes_precedence(self, monkeypatch, tmp_path):
        self._clear(monkeypatch)
        token_file = tmp_path / "token"
        token_file.write_text("f" * MIN_TOKEN_LENGTH + "\n")
        monkeypatch.setenv("MONARCH_MCP_AUTH_TOKEN", "e" * MIN_TOKEN_LENGTH)
        monkeypatch.setenv("MONARCH_MCP_AUTH_TOKEN_FILE", str(token_file))
        cfg = ServeConfig.from_env()
        assert cfg.auth_token == "f" * MIN_TOKEN_LENGTH  # stripped, file wins

    def test_custom_host_port_public_url_and_allowed_hosts(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("MONARCH_MCP_AUTH_TOKEN", VALID_TOKEN)
        monkeypatch.setenv("MONARCH_MCP_HOST", "0.0.0.0")
        monkeypatch.setenv("MONARCH_MCP_PORT", "9100")
        monkeypatch.setenv("MONARCH_MCP_PUBLIC_URL", "https://monarch.example.com")
        monkeypatch.setenv(
            "MONARCH_MCP_ALLOWED_HOSTS", "monarch.example.com, localhost:9100"
        )
        cfg = ServeConfig.from_env()
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 9100
        assert cfg.issuer_url == "https://monarch.example.com"
        assert cfg.allowed_hosts == ["monarch.example.com", "localhost:9100"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `monarch_mcp_server.config` does not exist.

- [ ] **Step 3: Implement `config.py`**

Create `src/monarch_mcp_server/config.py`:

```python
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
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (all 9).

- [ ] **Step 5: Commit**

```bash
git add src/monarch_mcp_server/config.py tests/test_config.py
git commit -m "Add run-mode resolution and serve-mode configuration"
```

---

### Task 4: Static token verifier (`http_auth.py`)

**Files:**
- Create: `src/monarch_mcp_server/http_auth.py`
- Test: `tests/test_http_auth.py`

**Interfaces:**
- Consumes: `mcp.server.auth.provider.AccessToken` (SDK model: `token`, `client_id`, `scopes` required).
- Produces: `StaticTokenVerifier(expected_token: str, max_failures_per_minute: int = 10)` implementing the SDK `TokenVerifier` protocol — `async verify_token(token: str) -> AccessToken | None`. Constant-time comparison; after `max_failures_per_minute` failures within 60s, each further failure sleeps 2s before returning None (global throttle, deliberately not per-IP).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_http_auth.py`:

```python
"""Tests for the static bearer token verifier."""

from unittest.mock import AsyncMock, patch

import pytest

from monarch_mcp_server.http_auth import StaticTokenVerifier

TOKEN = "t" * 40


class TestStaticTokenVerifier:
    async def test_valid_token_returns_access_token(self):
        verifier = StaticTokenVerifier(TOKEN)
        result = await verifier.verify_token(TOKEN)
        assert result is not None
        assert result.client_id == "static-token-client"

    async def test_invalid_token_returns_none(self):
        verifier = StaticTokenVerifier(TOKEN)
        assert await verifier.verify_token("w" * 40) is None

    async def test_empty_and_prefix_tokens_rejected(self):
        verifier = StaticTokenVerifier(TOKEN)
        assert await verifier.verify_token("") is None
        assert await verifier.verify_token(TOKEN[:-1]) is None
        assert await verifier.verify_token(TOKEN + "x") is None

    async def test_uses_constant_time_comparison(self):
        verifier = StaticTokenVerifier(TOKEN)
        with patch("monarch_mcp_server.http_auth.hmac.compare_digest",
                   wraps=__import__("hmac").compare_digest) as cmp:
            await verifier.verify_token(TOKEN)
            cmp.assert_called_once()

    async def test_throttles_after_repeated_failures(self):
        verifier = StaticTokenVerifier(TOKEN, max_failures_per_minute=3)
        with patch("monarch_mcp_server.http_auth.asyncio.sleep",
                   new=AsyncMock()) as sleep:
            for _ in range(3):
                await verifier.verify_token("bad" * 20)
            sleep.assert_not_called()
            await verifier.verify_token("bad" * 20)
            sleep.assert_awaited_once_with(2)

    async def test_successes_do_not_throttle(self):
        verifier = StaticTokenVerifier(TOKEN, max_failures_per_minute=1)
        with patch("monarch_mcp_server.http_auth.asyncio.sleep",
                   new=AsyncMock()) as sleep:
            for _ in range(5):
                await verifier.verify_token(TOKEN)
            sleep.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_http_auth.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the verifier**

Create `src/monarch_mcp_server/http_auth.py`:

```python
"""Static bearer-token verification for serve mode."""

import asyncio
import hmac
import logging
import time
from collections import deque
from typing import Deque, Optional

from mcp.server.auth.provider import AccessToken

logger = logging.getLogger(__name__)

_THROTTLE_WINDOW_SECONDS = 60.0
_THROTTLE_DELAY_SECONDS = 2


class StaticTokenVerifier:
    """Verifies the single operator-issued bearer token.

    Failed attempts are throttled globally (not per-IP): behind a tunnel all
    traffic shares one peer address, and trusting X-Forwarded-For would let a
    direct-connecting client dodge the limit by spoofing the header.
    """

    def __init__(self, expected_token: str, max_failures_per_minute: int = 10):
        self._expected = expected_token.encode()
        self._max_failures = max_failures_per_minute
        self._failures: Deque[float] = deque()

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        if hmac.compare_digest(token.encode(), self._expected):
            return AccessToken(
                token=token, client_id="static-token-client", scopes=[]
            )

        now = time.monotonic()
        self._failures.append(now)
        while self._failures and now - self._failures[0] > _THROTTLE_WINDOW_SECONDS:
            self._failures.popleft()
        if len(self._failures) > self._max_failures:
            logger.warning(
                "Auth failure throttle engaged (%d failures in the last minute)",
                len(self._failures),
            )
            await asyncio.sleep(_THROTTLE_DELAY_SECONDS)
        return None
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_http_auth.py -v`
Expected: PASS (all 6).

- [ ] **Step 5: Commit**

```bash
git add src/monarch_mcp_server/http_auth.py tests/test_http_auth.py
git commit -m "Add static bearer token verifier with global failure throttle"
```

---

### Task 5: Mode-aware app construction and conditional tool registration

**Files:**
- Modify: `src/monarch_mcp_server/app.py` (full rewrite shown below)
- Modify: `src/monarch_mcp_server/tools/auth.py` (registration block)
- Test: `tests/test_serve_mode.py` (new; uses subprocesses because tool registration is an import-time effect)

**Interfaces:**
- Consumes: `get_mode()`, `ServeConfig.from_env()` (Task 3), `StaticTokenVerifier` (Task 4).
- Produces: `monarch_mcp_server.app.mcp` — a `FastMCP` built for the resolved mode; `monarch_mcp_server.app.MODE` — the resolved mode string; `main()` unchanged for stdio. In serve mode `/healthz` is registered via `custom_route`. Tool functions in `tools/auth.py` remain importable in both modes (the `server.py` shim keeps working); only their *registration* is conditional.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_serve_mode.py`:

```python
"""Mode-dependent app construction and tool registration.

Registration happens at import time, so each case runs in a fresh
interpreter with the mode set via environment variables.
"""

import json
import os
import subprocess
import sys

LIST_TOOLS_SNIPPET = (
    "import asyncio, json;"
    "from monarch_mcp_server.app import mcp;"
    "tools = asyncio.run(mcp.list_tools());"
    "print(json.dumps(sorted(t.name for t in tools)))"
)

LOGIN_TOOLS = {
    "setup_authentication",
    "monarch_login",
    "monarch_login_with_token",
    "monarch_logout",
    "debug_session_loading",
}


def _tool_names(extra_env):
    env = os.environ | extra_env
    out = subprocess.run(
        [sys.executable, "-c", LIST_TOOLS_SNIPPET],
        capture_output=True, text=True, env=env, check=True,
    )
    return set(json.loads(out.stdout.strip().splitlines()[-1]))


def test_stdio_mode_registers_login_tools():
    names = _tool_names({"MONARCH_MCP_MODE": "stdio"})
    assert LOGIN_TOOLS <= names
    assert "check_auth_status" in names
    assert "get_accounts" in names


def test_serve_mode_omits_login_tools():
    names = _tool_names({
        "MONARCH_MCP_MODE": "serve",
        "MONARCH_MCP_AUTH_TOKEN": "x" * 40,
    })
    assert LOGIN_TOOLS.isdisjoint(names)
    assert "check_auth_status" in names
    assert "get_accounts" in names


def test_serve_mode_without_token_fails_fast():
    env = os.environ | {"MONARCH_MCP_MODE": "serve"}
    env.pop("MONARCH_MCP_AUTH_TOKEN", None)
    env.pop("MONARCH_MCP_AUTH_TOKEN_FILE", None)
    out = subprocess.run(
        [sys.executable, "-c", "import monarch_mcp_server.app"],
        capture_output=True, text=True, env=env,
    )
    assert out.returncode != 0
    assert "MONARCH_MCP_AUTH_TOKEN" in out.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_serve_mode.py -v`
Expected: `test_stdio_mode_registers_login_tools` PASSES already (current behavior); the serve-mode tests FAIL (no mode awareness exists).

- [ ] **Step 3: Rewrite `app.py`**

Replace the contents of `src/monarch_mcp_server/app.py` with:

```python
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


def _build_mcp() -> FastMCP:
    if MODE != "serve":
        return FastMCP("Monarch Money MCP Server")

    from mcp.server.auth.settings import AuthSettings
    from mcp.server.transport_security import TransportSecuritySettings

    from monarch_mcp_server.http_auth import StaticTokenVerifier

    cfg = ServeConfig.from_env()
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
    from starlette.responses import PlainTextResponse

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_: Request) -> PlainTextResponse:
        # Liveness only — no version or config details.
        return PlainTextResponse("ok")


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
```

- [ ] **Step 4: Make login-tool registration conditional in `tools/auth.py`**

In `src/monarch_mcp_server/tools/auth.py`: remove the five `@mcp.tool()` decorator lines from `setup_authentication`, `monarch_login`, `monarch_login_with_token`, `monarch_logout`, and `debug_session_loading` (keep the decorator on `check_auth_status`), and append at the end of the file:

```python
# Login tools accept credentials via the MCP channel, which is appropriate on
# a local stdio transport but not over a remote HTTP connection. In serve
# mode, sessions are installed on the host with login_setup.py instead.
if app_module.MODE == "stdio":
    mcp.tool()(setup_authentication)
    mcp.tool()(monarch_login)
    mcp.tool()(monarch_login_with_token)
    mcp.tool()(monarch_logout)
    mcp.tool()(debug_session_loading)
```

And change the import at the top from `from monarch_mcp_server.app import mcp` to:

```python
import monarch_mcp_server.app as app_module
from monarch_mcp_server.app import mcp
```

- [ ] **Step 5: Run the new tests and the full suite**

Run: `uv run pytest tests/test_serve_mode.py -v && uv run pytest`
Expected: all PASS. (`tests/test_auth.py` and `tests/test_server_auth.py` import the tool functions directly — they still exist as plain functions, so those tests must keep passing; if a test asserts on FastMCP registration of a login tool, run it with `MONARCH_MCP_MODE` unset, which is the default stdio.)

- [ ] **Step 6: Commit**

```bash
git add src/monarch_mcp_server/app.py src/monarch_mcp_server/tools/auth.py tests/test_serve_mode.py
git commit -m "Build FastMCP per run mode; register login tools only on stdio"
```

---

### Task 6: CLI dispatcher and entry point

**Files:**
- Create: `src/monarch_mcp_server/cli.py`
- Modify: `pyproject.toml:47` (entry point)
- Test: extend `tests/test_serve_mode.py`

**Interfaces:**
- Consumes: `monarch_mcp_server.app` (imported *after* mode env vars are set).
- Produces: console script `monarch-mcp-server` → `monarch_mcp_server.cli:main`. `monarch-mcp-server` (no args) = stdio exactly as before; `monarch-mcp-server serve [--host H] [--port P]` = streamable HTTP. CLI flags override env vars.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_serve_mode.py`:

```python
def test_cli_serve_subcommand_sets_mode_and_flags():
    from monarch_mcp_server import cli

    captured = {}

    def fake_run(transport=None):
        captured["transport"] = transport
        captured["mode"] = os.environ.get("MONARCH_MCP_MODE")
        captured["host"] = os.environ.get("MONARCH_MCP_HOST")
        captured["port"] = os.environ.get("MONARCH_MCP_PORT")

    def fake_import():
        class FakeApp:
            class mcp:
                run = staticmethod(fake_run)
        return FakeApp

    old_env = {k: os.environ.get(k) for k in
               ("MONARCH_MCP_MODE", "MONARCH_MCP_HOST", "MONARCH_MCP_PORT")}
    try:
        cli.main(["serve", "--host", "0.0.0.0", "--port", "9100"],
                 _app_loader=fake_import)
        assert captured == {
            "transport": "streamable-http",
            "mode": "serve",
            "host": "0.0.0.0",
            "port": "9100",
        }
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_serve_mode.py::test_cli_serve_subcommand_sets_mode_and_flags -v`
Expected: FAIL — `cli` module does not exist.

- [ ] **Step 3: Implement `cli.py`**

Create `src/monarch_mcp_server/cli.py`:

```python
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


def main(
    argv: Optional[List[str]] = None,
    _app_loader: Callable = _load_app,
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
        if parsed.port:
            os.environ["MONARCH_MCP_PORT"] = str(parsed.port)

        app = _app_loader()
        app.mcp.run(transport="streamable-http")
        return

    # Default: stdio, exactly as before.
    app = _app_loader()
    app.main()
```

- [ ] **Step 4: Update the entry point**

In `pyproject.toml`, change:

```toml
[project.scripts]
monarch-mcp-server = "monarch_mcp_server.cli:main"
```

Then run `uv sync --extra dev` to refresh the installed script.

- [ ] **Step 5: Run tests and a smoke check**

Run: `uv run pytest tests/test_serve_mode.py -v && uv run pytest`
Expected: PASS.

Run: `MONARCH_MCP_AUTH_TOKEN=$(openssl rand -base64 33) uv run monarch-mcp-server serve --port 8901 & sleep 3; curl -s http://127.0.0.1:8901/healthz; kill %1`
Expected: prints `ok`.

- [ ] **Step 6: Commit**

```bash
git add src/monarch_mcp_server/cli.py pyproject.toml uv.lock tests/test_serve_mode.py
git commit -m "Add serve subcommand dispatching mode before app import"
```

---

### Task 7: HTTP auth-boundary integration test

**Files:**
- Test: `tests/test_serve_http.py`

**Interfaces:**
- Consumes: the `monarch-mcp-server serve` process (Task 6), `httpx` (already a transitive dep of mcp).
- Produces: regression coverage for the full auth boundary over real HTTP.

- [ ] **Step 1: Write the integration test**

Create `tests/test_serve_http.py`:

```python
"""Integration tests: real serve-mode process, real HTTP, auth boundary."""

import os
import socket
import subprocess
import sys
import time

import httpx
import pytest

TOKEN = "integration-test-token-" + "x" * 20

INIT_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    },
}
MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    env = os.environ | {
        "MONARCH_MCP_MODE": "serve",
        "MONARCH_MCP_AUTH_TOKEN": TOKEN,
        "MONARCH_MCP_PORT": str(port),
    }
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "from monarch_mcp_server.cli import main; main(['serve'])"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                if httpx.get(f"{base}/healthz", timeout=1).status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.2)
        else:
            raise RuntimeError("server did not become healthy")
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_healthz_is_unauthenticated_and_bare(server):
    resp = httpx.get(f"{server}/healthz")
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_mcp_without_token_is_401(server):
    resp = httpx.post(f"{server}/mcp", json=INIT_BODY, headers=MCP_HEADERS)
    assert resp.status_code == 401
    assert "www-authenticate" in {k.lower() for k in resp.headers}


def test_mcp_with_wrong_token_is_401(server):
    resp = httpx.post(
        f"{server}/mcp", json=INIT_BODY,
        headers=MCP_HEADERS | {"Authorization": "Bearer " + "w" * 40},
    )
    assert resp.status_code == 401


def test_mcp_with_valid_token_initializes(server):
    resp = httpx.post(
        f"{server}/mcp", json=INIT_BODY,
        headers=MCP_HEADERS | {"Authorization": f"Bearer {TOKEN}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["serverInfo"]["name"] == "Monarch Money MCP Server"
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_serve_http.py -v`
Expected: PASS (4 tests). If the initialize response is SSE-framed rather than JSON despite `json_response=True`, parse the `data:` line — but with `json_response=True` it should be plain JSON.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest`
Expected: everything passes.

- [ ] **Step 4: Commit**

```bash
git add tests/test_serve_http.py
git commit -m "Add HTTP auth-boundary integration tests for serve mode"
```

---

### Task 8: Docker packaging

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `docker-compose.yml`

**Interfaces:**
- Consumes: the `monarch-mcp-server` console script (Task 6).
- Produces: an image whose default command is serve mode on `0.0.0.0:8000`, sessions persisted under the `/data` volume (via `HOME=/data`, so `secure_session`'s file fallback lands at `/data/.monarch-mcp-server/token`).

- [ ] **Step 1: Write `.dockerignore`**

```
.git
.venv
__pycache__
*.pyc
tests
docs
scripts
.pytest_cache
.mypy_cache
```

- [ ] **Step 2: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY login_setup.py ./

RUN pip install --no-cache-dir .

# Non-root user; HOME=/data puts the file-fallback session store
# (~/.monarch-mcp-server/token) on the persistent volume.
RUN useradd --create-home --uid 1000 monarch \
    && mkdir -p /data \
    && chown monarch:monarch /data
ENV HOME=/data \
    MONARCH_MCP_MODE=serve \
    MONARCH_MCP_HOST=0.0.0.0 \
    MONARCH_MCP_PORT=8000
USER monarch
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"

ENTRYPOINT ["monarch-mcp-server"]
CMD ["serve"]
```

- [ ] **Step 3: Write `docker-compose.yml`**

```yaml
services:
  monarch-mcp:
    build: .
    restart: unless-stopped
    # Bind to localhost only; a reverse proxy or tunnel provides TLS.
    # NEVER publish 8000 directly to the internet.
    ports:
      - "127.0.0.1:8000:8000"
    environment:
      # Generate with: openssl rand -base64 33
      # Prefer MONARCH_MCP_AUTH_TOKEN_FILE with a mounted secret in
      # production; env vars are visible via `docker inspect`.
      MONARCH_MCP_AUTH_TOKEN: ${MONARCH_MCP_AUTH_TOKEN:?set in .env}
      # Uncomment behind a proxy so Host-header checks are enforced:
      # MONARCH_MCP_ALLOWED_HOSTS: monarch.example.com
      # MONARCH_MCP_PUBLIC_URL: https://monarch.example.com
    volumes:
      - monarch-data:/data

  # Optional: Cloudflare Tunnel. Create a tunnel + token in the Zero Trust
  # dashboard, point its public hostname at http://monarch-mcp:8000, then:
  #   docker compose --profile tunnel up -d
  cloudflared:
    image: cloudflare/cloudflared:latest
    profiles: ["tunnel"]
    restart: unless-stopped
    command: tunnel --no-autoupdate run
    environment:
      TUNNEL_TOKEN: ${TUNNEL_TOKEN:?set in .env}
    depends_on:
      - monarch-mcp

volumes:
  monarch-data:
```

- [ ] **Step 4: Build and smoke-test the container**

Run:
```bash
docker build -t monarch-mcp-server:dev .
TOKEN=$(openssl rand -base64 33)
docker run -d --name mm-smoke -e MONARCH_MCP_AUTH_TOKEN="$TOKEN" -p 127.0.0.1:8902:8000 monarch-mcp-server:dev
sleep 5
curl -s http://127.0.0.1:8902/healthz           # expect: ok
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8902/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"c","version":"0"}}}'
# expect: 401
docker rm -f mm-smoke
```

Expected: `ok` then `401`.

- [ ] **Step 5: Verify multi-arch build works**

Run: `docker buildx build --platform linux/amd64,linux/arm64 -t monarch-mcp-server:multiarch . 2>&1 | tail -3`
Expected: builds succeed for both platforms (pure-Python deps have arm64 wheels). If buildx/QEMU is unavailable locally, note it and rely on CI/release tooling — do not block the task.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile .dockerignore docker-compose.yml
git commit -m "Add Docker packaging with compose and Cloudflare Tunnel example"
```

---

### Task 9: End-to-end script with the real MCP client

**Files:**
- Create: `scripts/e2e_http.py`

**Interfaces:**
- Consumes: a running serve-mode server (local process or Docker), env vars `E2E_URL` (default `http://127.0.0.1:8000/mcp`) and `E2E_TOKEN`.
- Produces: an executable check that a real `mcp` Python client completes initialize → list_tools → call `check_auth_status` over streamable HTTP, and that a wrong token is rejected.

- [ ] **Step 1: Write the script**

Create `scripts/e2e_http.py`:

```python
"""End-to-end check: real MCP client against a running serve-mode server.

Usage:
    E2E_TOKEN=<token> [E2E_URL=http://127.0.0.1:8000/mcp] \
        uv run python scripts/e2e_http.py
"""

import asyncio
import os
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = os.environ.get("E2E_URL", "http://127.0.0.1:8000/mcp")
TOKEN = os.environ.get("E2E_TOKEN")

LOGIN_TOOLS = {
    "setup_authentication",
    "monarch_login",
    "monarch_login_with_token",
    "monarch_logout",
    "debug_session_loading",
}


async def check_valid_token() -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with streamablehttp_client(URL, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            info = await session.initialize()
            assert info.serverInfo.name == "Monarch Money MCP Server", info
            print(f"✅ initialize: {info.serverInfo.name}")

            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert "get_accounts" in names, names
            assert LOGIN_TOOLS.isdisjoint(names), (
                f"login tools leaked into serve mode: {LOGIN_TOOLS & names}"
            )
            print(f"✅ list_tools: {len(names)} tools, no login tools")

            result = await session.call_tool("check_auth_status", {})
            text = result.content[0].text
            print(f"✅ check_auth_status: {text.splitlines()[0]}")


async def check_wrong_token() -> None:
    headers = {"Authorization": "Bearer " + "w" * 40}
    try:
        async with streamablehttp_client(URL, headers=headers) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
    except* (httpx.HTTPStatusError, Exception) as eg:
        print(f"✅ wrong token rejected ({type(eg.exceptions[0]).__name__})")
        return
    raise AssertionError("wrong token was accepted!")


async def main() -> None:
    if not TOKEN:
        sys.exit("Set E2E_TOKEN (the server's MONARCH_MCP_AUTH_TOKEN).")
    await check_valid_token()
    await check_wrong_token()
    print("\n🎉 E2E checks passed")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run it against the Docker container**

Run:
```bash
TOKEN=$(openssl rand -base64 33)
docker run -d --name mm-e2e -e MONARCH_MCP_AUTH_TOKEN="$TOKEN" -p 127.0.0.1:8903:8000 monarch-mcp-server:dev
sleep 5
E2E_URL=http://127.0.0.1:8903/mcp E2E_TOKEN="$TOKEN" uv run python scripts/e2e_http.py
docker rm -f mm-e2e
```

Expected: all ✅ lines and `🎉 E2E checks passed`. (`check_auth_status` legitimately reports "no token" — the container has no Monarch session; that still exercises a real tool call end-to-end.)

- [ ] **Step 3: Commit**

```bash
git add scripts/e2e_http.py
git commit -m "Add end-to-end HTTP check script using the real MCP client"
```

---

### Task 10: Documentation

**Files:**
- Modify: `README.md` (new "Remote access (HTTP)" section)

**Interfaces:**
- Consumes: everything above.
- Produces: operator docs for deploy + connect.

- [ ] **Step 1: Add the README section**

Append a "Remote access (HTTP)" section to `README.md` covering, with exact commands/snippets:

1. **What it is:** `monarch-mcp-server serve` = streamable HTTP + bearer token; stdio remains the default and is unchanged.
2. **Generate a token:** `openssl rand -base64 33`. Env vars table: `MONARCH_MCP_AUTH_TOKEN`, `MONARCH_MCP_AUTH_TOKEN_FILE` (preferred; env vars show in `docker inspect`), `MONARCH_MCP_HOST/PORT`, `MONARCH_MCP_ALLOWED_HOSTS`, `MONARCH_MCP_PUBLIC_URL`.
3. **Docker quick start:** `docker compose up -d`, `.env` with the token.
4. **Monarch login inside the container** (cookie-paste is the primary path — password login from VPS/datacenter IPs is frequently CAPTCHA-blocked):
   ```bash
   docker compose run --rm -it --entrypoint python monarch-mcp login_setup.py
   ```
   Sessions persist in the `monarch-data` volume, where the server reads them.
5. **Cloudflare Tunnel:** enable the `tunnel` profile, set `TUNNEL_TOKEN`, point the tunnel's public hostname at `http://monarch-mcp:8000`, set `MONARCH_MCP_ALLOWED_HOSTS` to the public hostname.
6. **Generic reverse proxy:** Caddy two-liner (`reverse_proxy 127.0.0.1:8000`) and the warning: never expose the port without TLS + token.
7. **Connect Claude Code:** `claude mcp add --transport http monarch https://monarch.example.com/mcp --header "Authorization: Bearer <token>"`.
8. **Connect Claude Desktop** via `mcp-remote`:
   ```json
   {
     "mcpServers": {
       "monarch": {
         "command": "npx",
         "args": [
           "mcp-remote", "https://monarch.example.com/mcp",
           "--header", "Authorization: Bearer ${MONARCH_TOKEN}"
         ],
         "env": { "MONARCH_TOKEN": "<token>" }
       }
     }
   }
   ```
   Note: the native paste-URL connector UI requires OAuth (future phase).
9. **Security notes:** token = full account access; rotate by restarting with a new token; `/healthz` is the only unauthenticated route; login MCP tools are disabled in serve mode by design.

- [ ] **Step 2: Proofread against the actual flags/vars implemented in Tasks 3-8**

Verify every env var name, flag, and command in the section matches the code. Fix drift.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Document remote HTTP deployment and client setup"
```

---

### Task 11: Final verification sweep

**Files:** none (verification only)

- [ ] **Step 1: Full test suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 2: Stdio regression check**

Run: `uv run python -c "from monarch_mcp_server.server import get_accounts, main, mcp; print('shim ok')"` and `printf '' | timeout 5 uv run monarch-mcp-server; echo "exit=$?"`
Expected: `shim ok`; stdio server starts and exits cleanly on closed stdin (exit 0 or the timeout's 124 — either proves it launched without error).

- [ ] **Step 3: Fresh Docker E2E (repeat Task 9 Step 2 from a clean image build)**

Expected: `🎉 E2E checks passed`.

- [ ] **Step 4: Manual pass checklist (operator, before release)**

Document as done/not-done in the PR description:
- Real Monarch cookie-paste login from the deployment host via `login_setup.py` in the container.
- `get_accounts` returns real data through a real tunnel/proxy with the bearer token.
- Wrong token rejected through the proxy.
