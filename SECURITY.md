# Security Policy

Glyph Hold stores memories and encrypted secrets for local agents. Treat the
database, Docker volume, API keys, and encryption key as sensitive operational
assets.

## Supported Versions

Glyph Hold is currently in early development. Until `v1.0.0`, compatibility and
security fixes are provided on the main development line.

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
