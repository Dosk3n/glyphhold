# Security Policy

Glyph Hold stores memories and encrypted secrets for local agents. Treat the
database, Docker volume, API keys, and encryption key as sensitive operational
assets.

## Supported Versions

Security fixes are provided for the latest published `v1.x` release. Users
should keep the container image current and retain a backup before upgrading.

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
- Encryption keys must come from runtime configuration, not the database.

## Deployment

- Use an HTTPS reverse proxy when Glyph Hold crosses an untrusted network.
- Set `GLYPHHOLD_COOKIE_SECURE=true` when the dashboard is served through HTTPS.
- Direct HTTP access is intended only for trusted internal networks.
- Complete first-run dashboard setup before exposing the service beyond a
  trusted network.
- Grant API keys only the scopes their agent or integration requires.
