"""Tests for the non-interactive login-cookies subcommand."""

import io

import pytest

from monarch_mcp_server import cli, login_cookies


class _FakeClient:
    def __init__(self, accounts):
        self._accounts = accounts

    async def get_accounts(self):
        return self._accounts


class TestLoginCookiesRun:
    def _patch_stdin(self, monkeypatch, value):
        monkeypatch.setattr("sys.stdin", io.StringIO(value))

    @pytest.mark.asyncio
    async def test_empty_stdin_fails_without_login_attempt(
        self, monkeypatch, capsys
    ):
        self._patch_stdin(monkeypatch, "   \n")
        called = []
        monkeypatch.setattr(
            login_cookies,
            "login_with_browser_cookies",
            lambda cookie: called.append(cookie),
        )
        assert await login_cookies._run() == 1
        assert called == []
        assert "stdin" in capsys.readouterr().err

    @pytest.mark.asyncio
    async def test_success_saves_session_without_echoing_cookie(
        self, monkeypatch, capsys
    ):
        cookie = "session_id=SECRETVALUE; csrftoken=ALSOSECRET"
        self._patch_stdin(monkeypatch, cookie + "\n")
        client = _FakeClient({"accounts": [{"id": "1"}, {"id": "2"}]})

        async def fake_login(cookie_string):
            assert cookie_string == cookie
            return client

        saved = []
        monkeypatch.setattr(
            login_cookies, "login_with_browser_cookies", fake_login
        )
        monkeypatch.setattr(
            login_cookies.secure_session,
            "save_authenticated_session",
            saved.append,
        )

        assert await login_cookies._run() == 0
        assert saved == [client]
        out = capsys.readouterr()
        assert "2 accounts" in out.out
        assert "SECRETVALUE" not in out.out + out.err

    @pytest.mark.asyncio
    async def test_login_failure_returns_error_and_saves_nothing(
        self, monkeypatch, capsys
    ):
        self._patch_stdin(monkeypatch, "session_id=whatever")

        async def fake_login(cookie_string):
            raise RuntimeError("401 from Monarch")

        saved = []
        monkeypatch.setattr(
            login_cookies, "login_with_browser_cookies", fake_login
        )
        monkeypatch.setattr(
            login_cookies.secure_session,
            "save_authenticated_session",
            saved.append,
        )

        assert await login_cookies._run() == 1
        assert saved == []
        assert "401 from Monarch" in capsys.readouterr().err


class TestCliRouting:
    def test_login_cookies_subcommand_does_not_load_app(self, monkeypatch):
        invoked = []
        monkeypatch.setattr(
            "monarch_mcp_server.login_cookies.main",
            lambda: invoked.append(True),
        )

        def fail_loader():  # pragma: no cover
            raise AssertionError("app must not be imported for login-cookies")

        cli.main(["login-cookies"], _app_loader=fail_loader)
        assert invoked == [True]
