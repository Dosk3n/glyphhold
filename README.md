# Glyph Hold

Glyph Hold is a local, deterministic memory and secrets service for agents.

It is designed to provide:

- structured memories
- dynamic categories
- tags for filtering and deterministic matching
- encrypted env-style secrets
- audit logs
- conservative agent prefetch
- a simple dashboard
- HTTP APIs for agent integrations

Glyph Hold does not use LLMs, embeddings, vector databases, hosted AI APIs, or
paid services internally.

## Current Status

This repository is under active early development. See [PLAN.md](PLAN.md) for
the project contract, build stages, and compatibility policy.

## Local Development

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --host 0.0.0.0 --port 5995
```

Open:

```text
http://localhost:5995
```

Run checks before committing:

```bash
ruff check .
pytest
docker build -t glyphhold:ci .
docker run --rm -e GLYPHHOLD_DB_PATH=/tmp/glyphhold-ci.sqlite glyphhold:ci \
  python -c "from app.storage.migrations import apply_migrations,current_schema_version; apply_migrations(); assert current_schema_version() >= 4"
```

## Docker

Copy the example compose file and environment file for a local deployment:

```bash
cp .env.example .env
cp docker-compose.example.yml docker-compose.yml
```

Then start the service:

```bash
docker compose up -d
```

Open:

```text
http://localhost:5995
```

On the first visit, Glyph Hold asks you to create the dashboard username and
password. After that, the setup page is disabled unless the database is reset.

The Docker container listens on port `5995` internally and the example compose
file maps host port `5995` to container port `5995`.

## Agent API Keys

Create API keys from the dashboard.

Each key has:

- name
- actor
- scopes
- enabled/disabled state

The generated key is shown once. Glyph Hold stores only a hash and a short
prefix.

Agents call the API with:

```http
Authorization: Bearer gh_live_xxxxxxxxxxxxxxxxx
```

Secret scopes are deliberately simple:

- `secrets:write` lets an agent create, update, and delete secrets.
- `secrets:reveal` lets an agent search/list secrets and reveal actual values.
- Without a secret scope, an agent cannot see or use secrets.

Secret values are never included in agent prefetch.

## Public API

The public API starts at `/api/v1`.

Examples:

```text
GET  /api/v1/health
GET  /api/v1/categories
POST /api/v1/memories/search
POST /api/v1/agent/prefetch
POST /api/v1/secrets/SERVICE_API_KEY/reveal
```

## Docker Images

The project is configured to publish Docker images to GitHub Container Registry
when version tags are pushed:

```text
ghcr.io/Dosk3n/glyphhold:latest
ghcr.io/Dosk3n/glyphhold:0.1.0
ghcr.io/Dosk3n/glyphhold:0.1
ghcr.io/Dosk3n/glyphhold:sha-<commit>
```

Prerelease tags such as `v0.1.0-alpha` publish prerelease and SHA tags, but do
not move `latest`.

Pin exact versions for stable deployments.

## Integration Skeletons

Thin HTTP-only integration skeletons live under `app/integrations/`:

- `client` provides `GlyphHoldClient` for `/api/v1` calls.
- `hermes` provides a prefetch provider wrapper.
- `nexus` provides a small tool-pack wrapper.

These integrations do not access SQLite directly and do not add LLM, embedding,
vector database, hosted AI, or paid API behavior.

## Security Notes

- Do not commit `.env`, SQLite databases, encryption keys, API keys, or exported
  secrets.
- Dashboard setup happens on first browser visit.
- Agent access uses bearer API keys created from the dashboard.
- Secret values are encrypted at rest when `GLYPHHOLD_ENCRYPTION_KEY` is set.
- If `GLYPHHOLD_ENCRYPTION_KEY` is not set, secret features are disabled while
  memory features continue to work.
