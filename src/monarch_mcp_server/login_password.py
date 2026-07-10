"""Non-interactive email/password login for headless deployments.

Reads newline-separated credentials from stdin — line 1 email, line 2
password, optional line 3 a one-time code — verifies the resulting
session against the live Monarch API, and saves it. The login_setup.py
option 2 flow without the prompts, for remote hosts where the session
must be seeded via docker exec from a CI runner.

Monarch commonly emails a one-time code for a new device (even with MFA
off). The first attempt without a code triggers that email and exits with
instructions; the operator re-runs with the code as line 3. A TOTP MFA
code goes in the same slot — whichever challenge Monarch raises, the code
is applied to it. Stdin keeps credentials out of argv and shell history;
nothing derived from them is printed.
"""

import asyncio
import sys

from monarchmoney import CaptchaRequiredException, RequireMFAException

from monarch_mcp_server.login_cookies import verify_and_save
from monarch_mcp_server.monarch_auth import (
    EmailOtpRequiredException,
    login_with_current_auth,
)


async def _run() -> int:
    lines = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
    if len(lines) < 2:
        print(
            "Expected credentials on stdin: line 1 email, line 2 password, "
            "optional line 3 a one-time code (email OTP or TOTP).",
            file=sys.stderr,
        )
        return 1
    email, password = lines[0], lines[1]
    code = lines[2] if len(lines) > 2 else None

    try:
        mm = await login_with_current_auth(email, password)
    except CaptchaRequiredException:
        print(
            "Programmatic login is blocked by Cloudflare CAPTCHA for this "
            "IP. Fall back to browser-cookie login (login-cookies).",
            file=sys.stderr,
        )
        return 1
    except EmailOtpRequiredException:
        if not code:
            print(
                "Monarch sent a one-time code to the account email. Re-run "
                "with the code as a third stdin line.",
                file=sys.stderr,
            )
            return 1
        try:
            mm = await login_with_current_auth(email, password, email_otp=code)
        except RequireMFAException:
            print(
                "Monarch also requires a TOTP MFA code after email "
                "verification — this headless flow handles one code per "
                "run. Use browser-cookie login (login-cookies) instead.",
                file=sys.stderr,
            )
            return 1
        except Exception as e:
            print(
                f"Login with email code failed: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            return 1
    except RequireMFAException:
        if not code:
            print(
                "Account has TOTP MFA enabled. Re-run with the current MFA "
                "code as a third stdin line.",
                file=sys.stderr,
            )
            return 1
        try:
            mm = await login_with_current_auth(email, password, mfa_code=code)
        except Exception as e:
            print(
                f"Login with MFA code failed: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            return 1
    except Exception as e:
        print(f"Login failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    return await verify_and_save(mm)


def main() -> None:
    sys.exit(asyncio.run(_run()))
