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
    except (httpx.HTTPStatusError, Exception) as e:
        print(f"✅ wrong token rejected ({type(e).__name__})")
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
