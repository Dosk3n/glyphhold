# Contributing To Glyph Hold

This document is for developers working on Glyph Hold itself. If you only want
to run Glyph Hold, use the Docker instructions in [README.md](README.md).

## Local Development

Glyph Hold requires Python 3.12 or newer.

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

## Checks

Run these before committing:

```bash
ruff check .
pytest
docker build -t glyphhold:ci .
docker run --rm -e GLYPHHOLD_DB_PATH=/tmp/glyphhold-ci.sqlite glyphhold:ci \
  python -c "from app.storage.migrations import apply_migrations,current_schema_version; apply_migrations(); assert current_schema_version() >= 4"
```

## Project Boundaries

Glyph Hold is deliberately local and deterministic.

Do not add:

- LLM calls
- embeddings
- vector databases
- Ollama integration inside the service
- hosted AI APIs
- paid APIs

Integrations must use the HTTP API and must not access SQLite directly.

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
