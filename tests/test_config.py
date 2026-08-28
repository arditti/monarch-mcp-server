"""Tests for mode resolution and serve configuration."""

import pytest

from monarch_mcp_server.config import MIN_TOKEN_LENGTH, ServeConfig, get_mode

VALID_TOKEN = "x" * MIN_TOKEN_LENGTH


class TestGetMode:
    def test_default_is_stdio(self, monkeypatch):
        monkeypatch.delenv("MONARCH_MCP_MODE", raising=False)
        assert get_mode() == "stdio"

    def test_serve_from_env(self, monkeypatch):
        monkeypatch.setenv("MONARCH_MCP_MODE", "serve")
        assert get_mode() == "serve"

    def test_unknown_mode_raises(self, monkeypatch):
        monkeypatch.setenv("MONARCH_MCP_MODE", "bananas")
        with pytest.raises(ValueError, match="MONARCH_MCP_MODE"):
            get_mode()


class TestServeConfig:
    def _clear(self, monkeypatch):
        for var in (
            "MONARCH_MCP_AUTH_TOKEN",
            "MONARCH_MCP_AUTH_TOKEN_FILE",
            "MONARCH_MCP_HOST",
            "MONARCH_MCP_PORT",
            "MONARCH_MCP_PUBLIC_URL",
            "MONARCH_MCP_ALLOWED_HOSTS",
        ):
            monkeypatch.delenv(var, raising=False)

    def test_defaults(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("MONARCH_MCP_AUTH_TOKEN", VALID_TOKEN)
        cfg = ServeConfig.from_env()
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 8000
        assert cfg.auth_token == VALID_TOKEN
        assert cfg.issuer_url == "http://127.0.0.1:8000"
        assert cfg.allowed_hosts == []

    def test_missing_token_raises(self, monkeypatch):
        self._clear(monkeypatch)
        with pytest.raises(ValueError, match="MONARCH_MCP_AUTH_TOKEN"):
            ServeConfig.from_env()

    def test_short_token_raises(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("MONARCH_MCP_AUTH_TOKEN", "short")
        with pytest.raises(ValueError, match="32"):
            ServeConfig.from_env()

    def test_token_file_takes_precedence(self, monkeypatch, tmp_path):
        self._clear(monkeypatch)
        token_file = tmp_path / "token"
        token_file.write_text("f" * MIN_TOKEN_LENGTH + "\n")
        monkeypatch.setenv("MONARCH_MCP_AUTH_TOKEN", "e" * MIN_TOKEN_LENGTH)
        monkeypatch.setenv("MONARCH_MCP_AUTH_TOKEN_FILE", str(token_file))
        cfg = ServeConfig.from_env()
        assert cfg.auth_token == "f" * MIN_TOKEN_LENGTH  # stripped, file wins

    def test_missing_token_file_falls_back_to_env(self, monkeypatch, tmp_path):
        self._clear(monkeypatch)
        monkeypatch.setenv(
            "MONARCH_MCP_AUTH_TOKEN_FILE", str(tmp_path / "not-there")
        )
        monkeypatch.setenv("MONARCH_MCP_AUTH_TOKEN", VALID_TOKEN)
        assert ServeConfig.from_env().auth_token == VALID_TOKEN

    def test_missing_token_file_and_no_env_raises_with_path_hint(
        self, monkeypatch, tmp_path
    ):
        self._clear(monkeypatch)
        monkeypatch.setenv(
            "MONARCH_MCP_AUTH_TOKEN_FILE", str(tmp_path / "not-there")
        )
        with pytest.raises(ValueError, match="not-there"):
            ServeConfig.from_env()

    def test_custom_host_port_public_url_and_allowed_hosts(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("MONARCH_MCP_AUTH_TOKEN", VALID_TOKEN)
        monkeypatch.setenv("MONARCH_MCP_HOST", "0.0.0.0")
        monkeypatch.setenv("MONARCH_MCP_PORT", "9100")
        monkeypatch.setenv("MONARCH_MCP_PUBLIC_URL", "https://monarch.example.com")
        monkeypatch.setenv(
            "MONARCH_MCP_ALLOWED_HOSTS", "monarch.example.com, localhost:9100"
        )
        cfg = ServeConfig.from_env()
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 9100
        assert cfg.issuer_url == "https://monarch.example.com"
        assert cfg.allowed_hosts == ["monarch.example.com", "localhost:9100"]
