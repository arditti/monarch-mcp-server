"""Tests for the non-interactive login-password subcommand."""

import io

import pytest
from monarchmoney import CaptchaRequiredException, RequireMFAException

from monarch_mcp_server import cli, login_password
from monarch_mcp_server.monarch_auth import EmailOtpRequiredException


class _FakeClient:
    def __init__(self, accounts):
        self._accounts = accounts

    async def get_accounts(self):
        return self._accounts


@pytest.fixture
def saved(monkeypatch):
    saved = []
    monkeypatch.setattr(
        "monarch_mcp_server.login_cookies.secure_session.save_authenticated_session",
        saved.append,
    )
    return saved


def _stdin(monkeypatch, value):
    monkeypatch.setattr("sys.stdin", io.StringIO(value))


class TestLoginPasswordRun:
    @pytest.mark.asyncio
    async def test_missing_password_line_fails(self, monkeypatch, saved, capsys):
        _stdin(monkeypatch, "user@example.com\n")
        assert await login_password._run() == 1
        assert saved == []
        assert "stdin" in capsys.readouterr().err

    @pytest.mark.asyncio
    async def test_plain_login_saves_session(self, monkeypatch, saved, capsys):
        _stdin(monkeypatch, "user@example.com\nhunter2secret\n")
        client = _FakeClient({"accounts": [{"id": "1"}]})

        async def fake_login(email, password, *, email_otp=None, mfa_code=None):
            assert (email, password) == ("user@example.com", "hunter2secret")
            assert email_otp is None and mfa_code is None
            return client

        monkeypatch.setattr(login_password, "login_with_current_auth", fake_login)
        assert await login_password._run() == 0
        assert saved == [client]
        out = capsys.readouterr()
        assert "1 accounts" in out.out
        assert "hunter2secret" not in out.out + out.err

    @pytest.mark.asyncio
    async def test_email_otp_required_without_code_instructs_retry(
        self, monkeypatch, saved, capsys
    ):
        _stdin(monkeypatch, "user@example.com\nhunter2secret\n")

        async def fake_login(email, password, *, email_otp=None, mfa_code=None):
            raise EmailOtpRequiredException()

        monkeypatch.setattr(login_password, "login_with_current_auth", fake_login)
        assert await login_password._run() == 1
        assert saved == []
        assert "one-time code" in capsys.readouterr().err

    @pytest.mark.asyncio
    async def test_supplied_code_is_applied_on_first_call(
        self, monkeypatch, saved
    ):
        # The provided code must ride the FIRST request (email_otp) so no
        # fresh OTP email is triggered — a no-code attempt first would
        # invalidate the operator's code.
        _stdin(monkeypatch, "user@example.com\nhunter2secret\n123456\n")
        client = _FakeClient({"accounts": []})
        calls = []

        async def fake_login(email, password, *, email_otp=None, mfa_code=None):
            calls.append((email_otp, mfa_code))
            assert email_otp == "123456"
            return client

        monkeypatch.setattr(login_password, "login_with_current_auth", fake_login)
        assert await login_password._run() == 0
        assert calls == [("123456", None)]  # exactly one call, no no-code probe
        assert saved == [client]

    @pytest.mark.asyncio
    async def test_supplied_code_falls_back_to_mfa_slot(self, monkeypatch, saved):
        # If Monarch rejects the code as an email OTP with an MFA-required
        # signal, retry it as a TOTP code — still no fresh-email probe.
        _stdin(monkeypatch, "user@example.com\nhunter2secret\n654321\n")
        client = _FakeClient({"accounts": []})
        calls = []

        async def fake_login(email, password, *, email_otp=None, mfa_code=None):
            calls.append((email_otp, mfa_code))
            if email_otp is not None:
                raise RequireMFAException("wanted totp")
            assert mfa_code == "654321"
            return client

        monkeypatch.setattr(login_password, "login_with_current_auth", fake_login)
        assert await login_password._run() == 0
        assert calls == [("654321", None), (None, "654321")]
        assert saved == [client]

    @pytest.mark.asyncio
    async def test_captcha_points_to_cookie_flow(self, monkeypatch, saved, capsys):
        _stdin(monkeypatch, "user@example.com\nhunter2secret\n")

        async def fake_login(email, password, *, email_otp=None, mfa_code=None):
            raise CaptchaRequiredException("blocked")

        monkeypatch.setattr(login_password, "login_with_current_auth", fake_login)
        assert await login_password._run() == 1
        assert saved == []
        assert "login-cookies" in capsys.readouterr().err


class TestCliRouting:
    def test_login_password_subcommand_does_not_load_app(self, monkeypatch):
        invoked = []
        monkeypatch.setattr(
            "monarch_mcp_server.login_password.main",
            lambda: invoked.append(True),
        )

        def fail_loader():  # pragma: no cover
            raise AssertionError("app must not be imported for login-password")

        cli.main(["login-password"], _app_loader=fail_loader)
        assert invoked == [True]
