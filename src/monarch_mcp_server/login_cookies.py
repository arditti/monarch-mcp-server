"""Non-interactive cookie login for headless deployments.

Reads a browser ``Cookie`` header string from stdin, verifies it against
the live Monarch API, and saves the session to secure storage — the same
flow as ``login_setup.py`` option 1, minus the prompts. Built for remote
hosts where no interactive terminal exists (e.g. ``docker exec`` driven
by a CI runner): stdin keeps the cookie out of process listings and shell
history, and nothing derived from the cookie is ever printed.
"""

import asyncio
import sys

from monarch_mcp_server.monarch_auth import login_with_browser_cookies
from monarch_mcp_server.secure_session import secure_session


async def verify_and_save(mm) -> int:
    """Verify a logged-in client against the live API, then persist it.

    Shared by the headless login subcommands (login-cookies,
    login-password). Prints only a success line — never credentials.
    """
    try:
        accounts = await mm.get_accounts()
    except Exception as e:
        print(
            f"Verification call failed: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return 1
    account_count = (
        len(accounts.get("accounts", [])) if isinstance(accounts, dict) else 0
    )
    secure_session.save_authenticated_session(mm)
    print(
        f"Monarch session verified ({account_count} accounts visible) and saved."
    )
    return 0


async def _run() -> int:
    cookie_string = sys.stdin.read().strip()
    if not cookie_string:
        print(
            "No cookie data on stdin. Pipe the browser Cookie header value, "
            "e.g.: cat cookie.txt | monarch-mcp-server login-cookies",
            file=sys.stderr,
        )
        return 1

    try:
        mm = await login_with_browser_cookies(cookie_string)
    except Exception as e:
        print(f"Cookie login failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    return await verify_and_save(mm)


def main() -> None:
    sys.exit(asyncio.run(_run()))
