# Glyph Hold Release Notes

## v0.1.0-beta

Glyph Hold is now in beta. It is intended for local agent memory and secret
storage with Docker, a dashboard, and the `/api/v1` HTTP API.

Back up mounted data and the encryption key before upgrading. Pin exact Docker
tags for anything important.

### Highlights

- FastAPI service on port `5995`.
- SQLite migrations through schema version 4.
- First-run dashboard setup and login.
- Dashboard API key creation with `gh_live_` bearer keys.
- Memory categories, CRUD, FTS search, revisions, and restore.
- Dashboard typed confirmations for destructive memory, secret, and API key
  actions.
- Encrypted secrets when `GLYPHHOLD_ENCRYPTION_KEY` is configured.
- Secret names are enforced as uppercase environment variable names.
- Optional secret reveal restrictions for allowed agents and tools.
- Secret reveal and env bundle endpoints.
- Conservative memory-only agent prefetch.
- `glyphhold_client` HTTP client helpers for health, categories, memories,
  prefetch, secret creation, reveal, and env bundles.
- Backup, restore, troubleshooting, and agent connection guides.
- CI runs ruff, pytest, Docker build, and migration smoke checks.

### Docker Images

Expected image tags:

```text
ghcr.io/dosk3n/glyphhold:0.1.0-beta
ghcr.io/dosk3n/glyphhold:sha-<commit>
```

Prerelease tags do not move `latest`.

### Pre-Tag Checklist

- `ruff check .`
- `pytest`
- `docker build -t glyphhold:ci .`
- `docker run --rm -e GLYPHHOLD_DB_PATH=/tmp/glyphhold-ci.sqlite glyphhold:ci python -c "from app.storage.migrations import apply_migrations,current_schema_version; apply_migrations(); assert current_schema_version() >= 4"`
- Review README and `.env.example`.
- Create and push tag `v0.1.0-beta`.

## v0.1.0-alpha

Initial alpha used to validate the Docker image, base API, dashboard setup,
memory flows, secret flows, revision restore, and the GitHub release workflow.
