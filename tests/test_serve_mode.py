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
