"""Self-service copy-paste client setup page (serve mode only).

Rendered at root "/", behind Cloudflare Access at the edge (this module
adds no auth of its own — see docs/SECRETS.md in home-infra for the
whole-hostname Access Application that gates it to a specific Google
account, with narrow bypass Applications carving out /mcp and /healthz).
Reads the bearer token live off disk on every request when the operator
uses MONARCH_MCP_AUTH_TOKEN_FILE, so a same-container token rotation
(delete the file, let an init step regenerate it) shows up here without a
page reload needing anything more than a fresh network request.
"""

import html
import json
from pathlib import Path

from monarch_mcp_server.config import ServeConfig


def current_auth_token(cfg: ServeConfig) -> str:
    """Return the token to display right now — re-read from disk if the
    operator configured a token file, so rotations are picked up live."""
    if cfg.auth_token_file:
        try:
            live = Path(cfg.auth_token_file).read_text().strip()
        except OSError:
            live = ""
        if live:
            return live
    return cfg.auth_token


def render_setup_page(cfg: ServeConfig) -> str:
    token = current_auth_token(cfg)
    mcp_url = f"{cfg.issuer_url}/mcp"

    claude_code_cmd = (
        f"claude mcp add --transport http monarch {mcp_url} \\\n"
        f'  --header "Authorization: Bearer {token}"'
    )
    desktop_json = json.dumps(
        {
            "mcpServers": {
                "monarch": {
                    "command": "npx",
                    "args": [
                        "mcp-remote",
                        mcp_url,
                        "--header",
                        f"Authorization: Bearer {token}",
                    ],
                }
            }
        },
        indent=2,
    )

    e = html.escape
    blocks = [
        ("Claude Code", claude_code_cmd),
        ("Claude Desktop (claude_desktop_config.json)", desktop_json),
        ("MCP URL", mcp_url),
        ("Bearer token", token),
    ]
    sections = "\n".join(
        f"""
        <section>
          <h2>{e(title)}</h2>
          <div class="block">
            <pre id="v{i}">{e(value)}</pre>
            <button onclick="copyBlock('v{i}', this)">Copy</button>
          </div>
        </section>"""
        for i, (title, value) in enumerate(blocks)
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>monarch-mcp — client setup</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg: #f7f7f8; --fg: #1a1a1a; --card: #ffffff; --border: #e2e2e4;
    --mono-bg: #f0f0f2; --accent: #6a4cff;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #16161a; --fg: #ececee; --card: #201f24; --border: #33323a; --mono-bg: #100f13; --accent: #a48bff; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 2rem 1rem 4rem; background: var(--bg); color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }}
  main {{ max-width: 42rem; margin: 0 auto; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 0.25rem; }}
  p.lede {{ opacity: 0.7; margin-top: 0; }}
  section {{
    background: var(--card); border: 1px solid var(--border); border-radius: 10px;
    padding: 1rem 1.25rem; margin-bottom: 1rem;
  }}
  h2 {{ font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.04em; opacity: 0.65; margin: 0 0 0.6rem; }}
  .block {{ display: flex; align-items: flex-start; gap: 0.6rem; }}
  pre {{
    flex: 1; min-width: 0; overflow-x: auto; background: var(--mono-bg); border-radius: 8px;
    padding: 0.75rem 0.9rem; margin: 0; font-size: 0.85rem; white-space: pre-wrap; word-break: break-all;
  }}
  button {{
    flex-shrink: 0; border: 1px solid var(--border); background: transparent; color: var(--fg);
    border-radius: 8px; padding: 0.5rem 0.8rem; cursor: pointer; font-size: 0.85rem;
  }}
  button:hover {{ border-color: var(--accent); color: var(--accent); }}
  button.copied {{ border-color: var(--accent); color: var(--accent); }}
  .warn {{ font-size: 0.85rem; opacity: 0.75; margin-top: 2rem; }}
</style>
</head>
<body>
<main>
  <h1>monarch-mcp client setup</h1>
  <p class="lede">Copy what your client needs. The token below is live — if it was just rotated, reload this page.</p>
  {sections}
  <p class="warn">This token grants full read/write access to the Monarch account. Don't share this page or its contents.</p>
</main>
<script>
function copyBlock(id, btn) {{
  const text = document.getElementById(id).textContent;
  navigator.clipboard.writeText(text).then(() => {{
    const original = btn.textContent;
    btn.textContent = "Copied";
    btn.classList.add("copied");
    setTimeout(() => {{ btn.textContent = original; btn.classList.remove("copied"); }}, 1500);
  }});
}}
</script>
</body>
</html>"""
