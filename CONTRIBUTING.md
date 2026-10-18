# Contributing To Glyph Hold

This document is for developers working on Glyph Hold itself. If you only want
to run Glyph Hold, use the Docker instructions in [README.md](README.md).

## Local Development

Glyph Hold requires Python 3.12 or newer and Node 22 or newer.

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
cd dashboard-ui
npm ci
npm run build
cd ..
GLYPHHOLD_DB_PATH=/tmp/glyphhold2-dev/glyphhold.sqlite uvicorn app.main:app --reload --host 127.0.0.1 --port 5996
```

For active dashboard work, run Vite in another terminal:

```bash
cd dashboard-ui
npm run dev
```

Open:

```text
http://localhost:5996
```

## Checks

Run these before committing:

```bash
ruff check .
pytest
cd dashboard-ui && npm ci && npm run typecheck && npm run build && cd ..
docker build -t glyphhold:ci .
docker run --rm -e GLYPHHOLD_DB_PATH=/tmp/glyphhold-ci.sqlite glyphhold:ci \
  python -c "from app.storage.migrations import apply_migrations,current_schema_version; apply_migrations(); assert current_schema_version() >= 4"
```

## Project Boundaries

Core memory remains local and deterministic, without required model calls,
embeddings, vector databases or paid APIs. GH2's explicitly enabled Advanced
Memory uses an isolated official Codex CLI worker with subscription sign-in.
Keep it disabled by default and never fall back to paid API billing. Model
output is evidence-backed proposed maintenance, constrained by server policy.

Use the isolated `docker-compose.gh2-test.yml` project for deployment testing.
Never attach the test image to an existing installation's volume or reuse its
port. Test source/version checks, grants, derived-data invalidation and runner
failure behaviour before evaluating live semantic quality with owner login.

External integrations must use the HTTP API and must not access SQLite directly.
Nexus and Hermes integrations should live in separate repositories.

## Repository Safety

Never commit:

- real `.env` files
- SQLite databases
- WAL/SHM files
- encryption keys
- API keys
- exported secrets
- local Docker volumes

Use examples and fake test fixtures only.
