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
