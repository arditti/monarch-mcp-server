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
