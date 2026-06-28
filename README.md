# Tomewarden

Tomewarden is a local, deterministic memory and secrets service for agents.

It is designed to provide:

- structured memories
- dynamic categories
- entities and aliases
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

Copy the example compose file and environment file when they are added for a
real deployment:

```bash
cp .env.example .env
cp docker-compose.example.yml docker-compose.yml
```

Then start the service:

```bash
docker compose up -d
```

## Security Notes

- Do not commit `.env`, SQLite databases, encryption keys, API keys, or exported
  secrets.
- Dashboard setup happens on first browser visit.
- Agent access uses bearer API keys created from the dashboard.
- Secret values are encrypted at rest when `TOMEWARDEN_ENCRYPTION_KEY` is set.

