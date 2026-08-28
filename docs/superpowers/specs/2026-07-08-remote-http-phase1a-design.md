# Remote HTTP Access — Phase 1a: Single-Tenant + Static Bearer Token

**Date:** 2026-07-08
**Status:** Draft — pending review
**Supersedes:** the earlier full multi-tenant OAuth draft in this file; that
design is preserved as the roadmap in the final section.

## Goal

Let the owner deploy monarch-mcp-server on a VPS, Raspberry Pi, or any Docker
host and reach it remotely over MCP streamable HTTP through Cloudflare Tunnel
or any TLS-terminating reverse proxy, authenticated with a static bearer
token. Claude Desktop connects via an `mcp-remote` config snippet; Claude Code
and other header-capable MCP clients connect directly.

Non-goals for this phase (see Roadmap): multiple tenants, OAuth 2.1
authorization server, web onboarding page, encrypted SQLite. Household members
who each want their own Monarch account run their own container.

## Design reviews incorporated

Three review passes (security, SDK feasibility, architecture) ran against the
original full-scope draft. Findings that apply at this scope are folded in
below; findings that only apply to multi-tenant/OAuth phases are recorded in
the Roadmap section.

## Run modes

| Mode | Invocation | Transport | Auth | Session storage |
|------|-----------|-----------|------|-----------------|
| stdio (default, unchanged) | `monarch-mcp-server` | stdio | none (local) | system keyring / file fallback |
| serve (new) | `monarch-mcp-server serve` | streamable HTTP | static bearer token | same keyring / file fallback |

Backward compatibility is a hard requirement: existing stdio installs (Claude
Desktop local config, `login_setup.py`, keyring sessions) keep working with no
changes.

## SDK prerequisite

Upgrade to `mcp>=1.28,<2` (currently locked at 1.13.1). Reasons verified
against SDK source:

- 1.13.1 stateful streamable HTTP does not bind sessions to credentials (a
  bearer-holder can replay another session's `mcp-session-id`); 1.28.x keeps
  `_session_owners` and rejects mismatches.
- 1.28.x adds `FastMCP.remove_tool()`, constant-time secret comparison, and
  the path-suffixed protected-resource metadata route needed by the OAuth
  phase later.

## Entry point & import-graph restructuring (key code change #1)

Both the SDK (`FastMCP` accepts `token_verifier`/`auth` only at construction)
and the current code (tools register via `@mcp.tool()` at import time in
`app.py`) require the mode to be known **before** `app.py` is imported.

- `main()` moves to a thin dispatcher module that parses the CLI
  (`serve` subcommand + flags, falling back to `MONARCH_MCP_MODE` env var),
  records the resolved mode (internal env var), **then** imports `app`.
- `app.py` reads the resolved mode at import and constructs `FastMCP`
  accordingly: stdio → exactly today's construction; serve → with
  `token_verifier` (see Auth), `stateless_http` left stateful (single user),
  `json_response=True` (proxy-safe; avoids SSE buffering issues), and
  `TransportSecuritySettings` with `allowed_hosts`/`allowed_origins` derived
  from config (DNS-rebinding protection is off by default in the SDK).
- In serve mode, the auth MCP tools (`monarch_login`,
  `monarch_login_with_token`, `setup_authentication`, `debug_session_loading`,
  `monarch_logout`) are not registered — `tools/__init__.py` skips the auth
  module's login tools based on mode. Monarch credentials never transit the
  remote MCP channel; login happens on the server via `login_setup.py` (SSH).
  `check_auth_status` stays, reporting session state and pointing at
  `login_setup.py` when missing.
- `secure_session` becomes lazily instantiated (module-level accessor instead
  of import-time instance) so importing the package doesn't probe the keyring
  (today it can pop a macOS Keychain prompt on any import).
- The `server.py` shim and `app = mcp` export keep working for stdio.

## Auth (serve mode)

A ~50-line implementation of the SDK's `TokenVerifier` protocol:

- Expected token comes from `MONARCH_MCP_AUTH_TOKEN` or
  `MONARCH_MCP_AUTH_TOKEN_FILE` (file preferred in docs; env vars leak via
  `docker inspect`). Server refuses to start in serve mode without one, and
  refuses tokens shorter than 32 characters.
- Comparison via `hmac.compare_digest` (constant-time).
- The SDK's `RequireAuthMiddleware` then 401s unauthenticated `/mcp` traffic.
- Global (not per-IP) failure rate limit: after N failed auth attempts per
  minute, delay responses. Per-IP limiting is deliberately avoided — behind a
  tunnel all traffic shares one peer IP, and trusting `X-Forwarded-For`
  invites spoofing (security review H1). uvicorn runs with proxy headers
  **disabled**; nothing in this phase needs the client IP.
- `GET /healthz` via `custom_route`, unauthenticated, returns `ok` only — no
  version/config (recon hygiene).

Token generation is the operator's job; docs show
`openssl rand -base64 33`.

## Serve-mode HTTP surface

- `POST/GET/DELETE /mcp` — MCP streamable HTTP (SDK-provided), bearer-protected.
- `GET /healthz` — liveness only.

Nothing else. No OAuth routes, no web pages in this phase.

## Configuration (env vars)

- `MONARCH_MCP_MODE` — `stdio` (default) | `serve`; CLI subcommand wins.
- `MONARCH_MCP_AUTH_TOKEN` / `MONARCH_MCP_AUTH_TOKEN_FILE` — required in serve mode.
- `MONARCH_MCP_HOST` / `MONARCH_MCP_PORT` — default `127.0.0.1:8000`
  (`0.0.0.0:8000` in the Docker image, where the container boundary is the
  isolation).
- `MONARCH_MCP_ALLOWED_HOSTS` — comma-separated Host header allowlist for
  transport security (e.g. `monarch.example.com`); default: the bind host.

No `PUBLIC_URL` needed in this phase (no absolute URLs are generated); it
arrives with OAuth in Phase 3.

## Monarch session on the server

Unchanged storage (`secure_session`: keyring, or file fallback at
`~/.monarch-mcp-server/token` — the file path is what headless Docker/VPS
hosts will use; it's already `chmod 600/700`).

Login on the deployment host uses `login_setup.py` over SSH (or
`docker exec`). Important caveat surfaced by review: Monarch password login
from datacenter IPs is frequently CAPTCHA-blocked
(`CaptchaRequiredException`), and email-OTP/MFA chaining makes the
interactive flow the only reliable password path. `login_setup.py` already
supports browser-cookie paste as the recommended alternative — the deployment
docs make **cookie-paste the primary documented path** for VPS installs.
Docker docs must cover running `login_setup.py` inside the container with the
data volume mounted so the session lands where the server reads it.

When Monarch rejects the stored session (401), tools return a structured
error directing the operator to re-run `login_setup.py`; the MCP connection
stays valid.

## Client connection story

- **Claude Code / header-capable clients:** point at `https://host/mcp` with
  `Authorization: Bearer <token>`.
- **Claude Desktop:** local config with the `mcp-remote` stdio→HTTP shim
  passing the header. Documented snippet in README. (The native paste-URL
  connector UI requires OAuth — Phase 3. Note: connector traffic originates
  from Anthropic's cloud, so even for Desktop the server must be
  internet-reachable when that phase lands.)

## Packaging & deployment

- Multi-arch Dockerfile (linux/amd64 + linux/arm64), non-root user, volume at
  `/data` (mapped to the session file location via `HOME`), `HEALTHCHECK`
  hitting `/healthz`.
- `docker-compose.yml` example with commented env vars and an optional
  `cloudflared` sidecar for Cloudflare Tunnel.
- README walkthrough: build/run, token generation, cookie-paste login inside
  the container, Cloudflare Tunnel, generic nginx/Caddy TLS example, and an
  explicit warning: never expose the port without TLS + token.
- No new Python dependencies (uvicorn ships with `mcp[cli]`).

## Testing

1. **Unit:** token verifier (valid/invalid/missing/short token, constant-time
   path), mode resolution (CLI vs env), mode-dependent tool registration
   (login tools absent in serve mode, present in stdio), lazy secure_session
   (no keyring probe on bare import).
2. **Integration (in-process ASGI, mocked Monarch client):** streamable HTTP
   initialize + tool call with valid bearer succeeds; missing/wrong bearer →
   401; `/healthz` unauthenticated; stdio path unchanged (existing suite keeps
   passing).
3. **End-to-end (required before done):** real server in Docker, real MCP
   Python client over streamable HTTP: container up → session installed via
   `login_setup.py` (stubbed Monarch for the repeatable scripted variant) →
   initialize with bearer → `get_accounts` returns data → wrong token
   rejected. One manual verification pass against a real Monarch account and
   a real tunnel/proxy before release, including confirming Monarch
   cookie-paste login works from the deployment host.

## Roadmap (later phases, designed but not built now)

- **Phase 2 — multi-tenant static tokens:** N operator-issued bearer tokens →
  N Monarch sessions in Fernet-encrypted SQLite; admin CLI (`user
  add/list/remove`); `get_monarch_client()` resolves the tenant from the
  verified token via `get_access_token()` (empirically confirmed working in
  the SDK); per-user client cache replaces the module-global
  `_cached_client`; cookie-paste web onboarding page. Carry-over review
  findings: WAL mode + busy_timeout for SQLite; DB file perms 600/700;
  onboarding is a multi-step state machine (credentials → email OTP → MFA)
  with cookie-paste primary; CSRF tokens on all forms; scrub request bodies
  from logs on credential routes.
- **Phase 3 — OAuth 2.1 AS** for the native Claude Desktop/claude.ai
  connector UX: SDK `OAuthAuthorizationServerProvider`,
  `ClientRegistrationOptions(enabled=True)` (off by default), setup-token
  identity step (reusable-until-expiry, no remember-browser cookie), PKCE
  S256 only, refresh rotation **with reuse detection** (revoke token family
  on replay), exact-match redirect URI validation bound through code
  exchange, encrypt (don't hash) OAuth client secrets (SDK compares
  retrievable values), rate-limit `/register`, `PUBLIC_URL` required and
  https-enforced, `MultiFernet` key-rotation story.

## Decisions log

- Scope cut from full multi-tenant OAuth to single-tenant static token after
  review: the full design is 3 phases of work and Phase 1a alone satisfies
  the immediate need (owner + Claude Desktop via mcp-remote).
- Per-IP rate limiting rejected (spoofable/meaningless behind tunnels);
  global failure throttle instead.
- Login tools disabled in serve mode; SSH + `login_setup.py` with
  cookie-paste is the credential path.
- `json_response=True` chosen for proxy friendliness over SSE streaming
  responses.
