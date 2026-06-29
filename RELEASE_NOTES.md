# Glyph Hold Release Notes

## v0.1.0-alpha Draft

Glyph Hold is still an early alpha. Back up mounted data before upgrading and
pin exact Docker tags for anything important.

### Highlights

- FastAPI service on port `5995`.
- SQLite migrations through schema version 4.
- First-run dashboard setup and login.
- Dashboard API key creation with `gh_live_` bearer keys.
- Memory categories, CRUD, FTS search, revisions, and restore.
- Encrypted secrets when `GLYPHHOLD_ENCRYPTION_KEY` is configured.
- Secret reveal and env bundle endpoints.
- Conservative memory-only agent prefetch.
- Dashboard edit/delete flows for memories and secrets.
- Thin HTTP client, Hermes provider, and Nexus tool-pack skeletons.
- CI runs ruff, pytest, Docker build, and migration smoke checks.

### Docker Images

Expected image tags:

```text
ghcr.io/Dosk3n/glyphhold:0.1.0-alpha
ghcr.io/Dosk3n/glyphhold:sha-<commit>
```

Prerelease tags do not move `latest`.

### Pre-Tag Checklist

- `ruff check .`
- `pytest`
- `docker build -t glyphhold:ci .`
- `docker run --rm -e GLYPHHOLD_DB_PATH=/tmp/glyphhold-ci.sqlite glyphhold:ci python -c "from app.storage.migrations import apply_migrations,current_schema_version; apply_migrations(); assert current_schema_version() >= 4"`
- Review README and `.env.example`.
- Create and push tag `v0.1.0-alpha`.
