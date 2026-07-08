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
