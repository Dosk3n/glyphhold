# Tomewarden

Tomewarden is a local, deterministic memory and secrets service for agents.

It is designed to provide:

- structured memories
- dynamic categories
- tags for filtering and deterministic matching
- encrypted env-style secrets
- audit logs
- conservative agent prefetch
- a simple dashboard
- HTTP APIs for agent integrations

Tomewarden does not use LLMs, embeddings, vector databases, hosted AI APIs, or
paid services internally.

## Current Status

This repository is under active early development. See [PLAN.md](PLAN.md) for
the project contract, build stages, and compatibility policy.

## Local Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8787
```

Open:

```text
http://localhost:8787
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
http://localhost:8787
```

On the first visit, Tomewarden asks you to create the dashboard username and
password. After that, the setup page is disabled unless the database is reset.

## Agent API Keys

Create API keys from the dashboard.

Each key has:

- name
- actor
- scopes
- enabled/disabled state

The generated key is shown once. Tomewarden stores only a hash and a short
prefix.

Agents call the API with:

```http
Authorization: Bearer tw_live_xxxxxxxxxxxxxxxxx
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
ghcr.io/<github-username>/tomewarden:latest
ghcr.io/<github-username>/tomewarden:0.1.0
ghcr.io/<github-username>/tomewarden:0.1
ghcr.io/<github-username>/tomewarden:sha-<commit>
```

Pin exact versions for stable deployments.

## Security Notes

- Do not commit `.env`, SQLite databases, encryption keys, API keys, or exported
  secrets.
- Dashboard setup happens on first browser visit.
- Agent access uses bearer API keys created from the dashboard.
- Secret values are encrypted at rest when `TOMEWARDEN_ENCRYPTION_KEY` is set.
- If `TOMEWARDEN_ENCRYPTION_KEY` is not set, secret features are disabled while
  memory features continue to work.
