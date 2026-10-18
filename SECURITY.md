# Security Policy

Glyph Hold stores memories and encrypted secrets for local agents. Treat the
database, Docker volume, API keys, and encryption key as sensitive operational
assets.

## Supported Versions

Security fixes are provided for the latest published `v1.x` release. Users
should keep the container image current and retain a backup before upgrading.
GH2 is currently a local development build; publishing and production cutover
are separate steps after validation.

## Reporting A Vulnerability

Do not open a public issue containing real secrets, API keys, database files, or
exploit details that would expose users.

For now, report vulnerabilities privately to the repository owner through
GitHub's private vulnerability reporting feature if enabled, or by direct
contact if the owner documents a preferred channel.

## Secret Handling Rules

- Secret values must never be logged.
- Secret values must never appear in event logs.
- Secret values must never be returned by memory search, prefetch, or secret
  metadata endpoints.
- Secret reveal must use explicit POST endpoints.
- Installation keys are generated in the persistent volume outside SQLite;
  advanced deployments can supply the original runtime key explicitly.
- Bitwarden credentials are encrypted settings; saved passwords are never
  returned to the browser. External Password Manager connections require HTTPS.
- Provider bindings are pinned by account/item/field, with approved folders and
  explicit space grants checked on reveal. An outage never selects a fallback value.
- Model workers receive bounded evidence, have no secret tools, and run under a
  separate OS identity in Docker. The database/key/provider state is unreadable
  to that account. The prompt is not a permission boundary.
- Source-linked profiles must be invalidated when evidence changes ownership or
  is removed. Generated text is not independent evidence.

## Deployment

- Use an HTTPS reverse proxy when Glyph Hold crosses an untrusted network.
- Set `GLYPHHOLD_COOKIE_SECURE=true` when the dashboard is served through HTTPS.
- Direct HTTP access is intended only for trusted internal networks.
- Complete first-run dashboard setup before exposing the service beyond a
  trusted network.
- Grant API keys only the scopes their agent or integration requires.
- Assign explicit space grants as well as operation scopes. Keep legacy v1 data
  access disabled; enabling it bypasses the v2 ownership model.
- Preserve encryption keys and protect saved Codex/Bitwarden login state in
  backups. Use the default asyncio event loop for worker privilege isolation.


## GH2 review and public API deployments

The local GH2 security review and fixes are documented in [GH2_SECURITY_REVIEW.md](docs/security/GH2_SECURITY_REVIEW.md), including remaining upstream Bitwarden dependencies and the audit's limits. The dashboard signing key is now derived from protected installation material rather than stored in SQLite. Upgrading expires old dashboard cookies once; passwords, encrypted secrets and Codex sign-in are retained. Secret-disabled installs use a private persistent session.key file instead.

Authelia should protect every non-API path, including dashboard APIs and setup/login; public API calls still need Glyph Hold bearer keys and explicit grants. Use [the Nginx example](deploy/nginx-authelia.example.conf) as a starting point, set secure cookies under HTTPS, and restrict direct backend access. Documentation endpoints are disabled by default; GLYPHHOLD_EXPOSE_API_DOCS=true is an explicit opt-in. Health integrity results are refreshed at most once per minute.

Memory metadata requires memory-read scope. Global category mutations require the local dashboard administrator; ordinary API keys cannot change global policy. Advanced Memory inference receives source evidence from one space at a time. Review-first remains the default, and automatic processing cannot guarantee factual correctness against poisoned evidence inside a permitted space.
