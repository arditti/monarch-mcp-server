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
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


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


def test_root_serves_setup_page_unauthenticated(server):
    # No auth of its own (relies on Cloudflare Access at the edge in
    # production) — but must not collide with the MCP transport's own
    # root-adjacent routing, and must not require the bearer token.
    resp = httpx.get(f"{server}/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert TOKEN in resp.text
    assert "claude mcp add" in resp.text


def test_mcp_endpoint_unaffected_by_root_route(server):
    # Guards against a regression where adding "/" ever shadows "/mcp".
    resp = httpx.post(
        f"{server}/mcp", json=INIT_BODY,
        headers=MCP_HEADERS | {"Authorization": f"Bearer {TOKEN}"},
    )
    assert resp.status_code == 200


def test_mcp_with_valid_token_as_query_param_initializes(server):
    # Custom MCP connectors (Claude Desktop/mobile's "Remote MCP server
    # URL" field) can't set a header — this is the path they use instead.
    resp = httpx.post(
        f"{server}/mcp?token={TOKEN}", json=INIT_BODY, headers=MCP_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["serverInfo"]["name"] == "Monarch Money MCP Server"


def test_mcp_with_wrong_token_as_query_param_is_401(server):
    resp = httpx.post(
        f"{server}/mcp?token=" + "w" * 40, json=INIT_BODY, headers=MCP_HEADERS,
    )
    assert resp.status_code == 401


def test_mcp_header_wins_over_query_token_when_both_present(server):
    # A real Authorization header must never be silently overridden by a
    # query param — even a WRONG header should still fail, not fall back
    # to a valid query token.
    resp = httpx.post(
        f"{server}/mcp?token={TOKEN}", json=INIT_BODY,
        headers=MCP_HEADERS | {"Authorization": "Bearer " + "w" * 40},
    )
    assert resp.status_code == 401
