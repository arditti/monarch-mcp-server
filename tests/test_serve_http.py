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
