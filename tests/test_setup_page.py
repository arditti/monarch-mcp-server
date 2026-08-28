"""Tests for the root ("/") client-config page."""

from monarch_mcp_server.config import ServeConfig
from monarch_mcp_server.setup_page import current_auth_token, render_setup_page


def _cfg(**overrides):
    defaults = dict(
        host="0.0.0.0",
        port=8000,
        auth_token="startup-token-" + "x" * 20,
        issuer_url="https://monarch-home.arditti.io",
        allowed_hosts=["monarch-home.arditti.io"],
        auth_token_file="",
    )
    defaults.update(overrides)
    return ServeConfig(**defaults)


class TestCurrentAuthToken:
    def test_no_token_file_uses_startup_value(self):
        cfg = _cfg()
        assert current_auth_token(cfg) == cfg.auth_token

    def test_token_file_present_reads_live_value(self, tmp_path):
        token_file = tmp_path / "auth_token"
        token_file.write_text("rotated-token-" + "y" * 20 + "\n")
        cfg = _cfg(auth_token_file=str(token_file))
        assert current_auth_token(cfg) == "rotated-token-" + "y" * 20

    def test_token_file_missing_falls_back_to_startup_value(self, tmp_path):
        cfg = _cfg(auth_token_file=str(tmp_path / "nope"))
        assert current_auth_token(cfg) == cfg.auth_token

    def test_token_file_empty_falls_back_to_startup_value(self, tmp_path):
        token_file = tmp_path / "auth_token"
        token_file.write_text("   \n")
        cfg = _cfg(auth_token_file=str(token_file))
        assert current_auth_token(cfg) == cfg.auth_token


class TestRenderSetupPage:
    def test_contains_live_token_and_url_not_startup_token(self, tmp_path):
        token_file = tmp_path / "auth_token"
        token_file.write_text("live-token-" + "z" * 20)
        cfg = _cfg(auth_token="stale-startup-token", auth_token_file=str(token_file))

        page = render_setup_page(cfg)

        assert "live-token-" + "z" * 20 in page
        assert "stale-startup-token" not in page
        assert "https://monarch-home.arditti.io/mcp" in page

    def test_html_escapes_token_special_characters(self):
        cfg = _cfg(auth_token="tok<en>&\"needs'escaping" + "x" * 10)
        page = render_setup_page(cfg)
        assert "<en>" not in page
        assert "&lt;en&gt;" in page

    def test_claude_code_command_present(self):
        cfg = _cfg()
        page = render_setup_page(cfg)
        assert "claude mcp add --transport http monarch" in page
        assert cfg.auth_token in page

    def test_desktop_json_block_present_and_valid(self):
        import html
        import json
        import re

        cfg = _cfg()
        page = render_setup_page(cfg)
        assert "mcpServers" in page  # HTML-escaped quotes, so check unquoted
        match = re.search(r'<pre id="v2">(.*?)</pre>', page, re.DOTALL)
        assert match is not None
        parsed = json.loads(html.unescape(match.group(1)))
        assert parsed["mcpServers"]["monarch"]["args"][1] == f"{cfg.issuer_url}/mcp"

    def test_connector_url_block_present_with_token_query_param(self):
        cfg = _cfg()
        page = render_setup_page(cfg)
        expected_url = f"{cfg.issuer_url}/mcp?token={cfg.auth_token}"
        assert expected_url in page
        assert "Add custom connector" in page
        assert "Leave OAuth Client ID/Secret blank" in page

    def test_connector_url_uses_live_token_not_startup_token(self, tmp_path):
        token_file = tmp_path / "auth_token"
        token_file.write_text("live-token-" + "z" * 20)
        cfg = _cfg(auth_token="stale-startup-token", auth_token_file=str(token_file))

        page = render_setup_page(cfg)

        assert f"{cfg.issuer_url}/mcp?token=live-token-" + "z" * 20 in page
        assert "token=stale-startup-token" not in page
