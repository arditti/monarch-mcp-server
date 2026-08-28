"""Unit tests for the ?token= -> Authorization header ASGI shim."""

import pytest

from monarch_mcp_server.query_token_auth import QueryTokenAuthMiddleware


class _RecordingApp:
    """Minimal ASGI app that records the headers it was called with."""

    def __init__(self):
        self.received_scope = None

    async def __call__(self, scope, receive, send):
        self.received_scope = scope


def _http_scope(*, query_string: bytes = b"", headers: list | None = None) -> dict:
    return {
        "type": "http",
        "query_string": query_string,
        "headers": headers or [],
    }


def _header_value(scope: dict, name: bytes) -> bytes | None:
    for k, v in scope["headers"]:
        if k.lower() == name.lower():
            return v
    return None


@pytest.mark.asyncio
class TestQueryTokenAuthMiddleware:
    async def test_query_token_becomes_authorization_header(self):
        inner = _RecordingApp()
        mw = QueryTokenAuthMiddleware(inner)

        await mw(_http_scope(query_string=b"token=abc123"), None, None)

        assert _header_value(inner.received_scope, b"authorization") == b"Bearer abc123"

    async def test_existing_authorization_header_wins_over_query_token(self):
        inner = _RecordingApp()
        mw = QueryTokenAuthMiddleware(inner)
        headers = [(b"authorization", b"Bearer real-header-token")]

        await mw(_http_scope(query_string=b"token=abc123", headers=headers), None, None)

        assert _header_value(inner.received_scope, b"authorization") == b"Bearer real-header-token"

    async def test_no_query_token_and_no_header_leaves_request_unauthenticated(self):
        inner = _RecordingApp()
        mw = QueryTokenAuthMiddleware(inner)

        await mw(_http_scope(), None, None)

        assert _header_value(inner.received_scope, b"authorization") is None

    async def test_empty_token_value_is_ignored(self):
        inner = _RecordingApp()
        mw = QueryTokenAuthMiddleware(inner)

        await mw(_http_scope(query_string=b"token="), None, None)

        assert _header_value(inner.received_scope, b"authorization") is None

    async def test_non_http_scope_passes_through_untouched(self):
        inner = _RecordingApp()
        mw = QueryTokenAuthMiddleware(inner)
        scope = {"type": "lifespan"}

        await mw(scope, None, None)

        assert inner.received_scope == {"type": "lifespan"}

    async def test_other_query_params_do_not_interfere(self):
        inner = _RecordingApp()
        mw = QueryTokenAuthMiddleware(inner)

        await mw(_http_scope(query_string=b"foo=bar&token=abc123&baz=qux"), None, None)

        assert _header_value(inner.received_scope, b"authorization") == b"Bearer abc123"
