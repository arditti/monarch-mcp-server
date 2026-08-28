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

    if code:
        mm = await _login_with_code(email, password, code)
    else:
        mm = await _login_without_code(email, password)
    if mm is None:
        return 1
    return await verify_and_save(mm)


async def _login_without_code(email: str, password: str):
    """First-run attempt with no code. Detects which challenge Monarch
    raises and instructs the operator to re-run with the emailed / TOTP
    code — returns None so the caller exits non-zero."""
    try:
        return await login_with_current_auth(email, password)
    except CaptchaRequiredException:
        print(
            "Programmatic login is blocked by Cloudflare CAPTCHA for this "
            "IP. Fall back to browser-cookie login (login-cookies).",
            file=sys.stderr,
        )
    except EmailOtpRequiredException:
        print(
            "Monarch sent a one-time code to the account email. Re-run with "
            "the code as a third stdin line.",
            file=sys.stderr,
        )
    except RequireMFAException:
        print(
            "Account has TOTP MFA enabled. Re-run with the current MFA code "
            "as a third stdin line.",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"Login failed: {type(e).__name__}: {e}", file=sys.stderr)
    return None


async def _login_with_code(email: str, password: str, code: str):
    """Apply a supplied code on the FIRST login call.

    Doing a no-code attempt first would make Monarch send a fresh email
    OTP and invalidate the code the operator already holds — so the code
    must ride the initial request. Monarch's email-OTP and TOTP codes are
    indistinguishable to us, so try it as an email OTP first (the common
    new-device case) and fall back to treating it as a TOTP MFA code if
    Monarch says it wanted MFA instead."""
    try:
        return await login_with_current_auth(email, password, email_otp=code)
    except (EmailOtpRequiredException, RequireMFAException):
        try:
            return await login_with_current_auth(email, password, mfa_code=code)
        except Exception as e:
            print(
                f"Login with code failed: {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            return None
    except CaptchaRequiredException:
        print(
            "Programmatic login is blocked by Cloudflare CAPTCHA for this "
            "IP. Fall back to browser-cookie login (login-cookies).",
            file=sys.stderr,
        )
        return None
    except Exception as e:
        print(f"Login with code failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def main() -> None:
    sys.exit(asyncio.run(_run()))
