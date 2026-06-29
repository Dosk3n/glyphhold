# Glyph Hold

Glyph Hold is a local memory and secrets service for AI agents.

It gives your agents a shared place to store durable notes, decisions, project
context, procedures, preferences, and operational secrets without sending that
data to a hosted AI service.

Open the dashboard, create memories and secrets, create an API key, then point
your agents at Glyph Hold.

## Why Run It?

AI agents are more useful when they can remember stable context:

- who people are
- how your projects are structured
- which servers and services exist
- what decisions have already been made
- repeatable procedures and runbooks
- preferences you do not want to repeat every session
- secrets that should be revealed only when explicitly requested

Glyph Hold keeps that information local, deterministic, and inspectable.

## What It Does

- Stores memories with categories, tags, confidence, and revision history.
- Searches memories with deterministic SQLite FTS5.
- Provides conservative memory prefetch for agents.
- Stores secrets encrypted at rest when an encryption key is configured.
- Reveals secret values only through explicit reveal/env endpoints.
- Keeps secret values out of memory prefetch.
- Provides a browser dashboard for setup, memories, secrets, API keys, and audit
  events.
- Uses bearer API keys for agents and signed cookies for dashboard sessions.
- Runs as a Docker container on port `5995`.

## What It Does Not Do

Glyph Hold does not use or include:

- LLM calls
- embeddings
- vector databases
- Ollama
- hosted AI APIs
- paid APIs

Agents remain HTTP clients. Glyph Hold owns the SQLite database.

## Status

Glyph Hold is currently beta software. It is suitable for local agent memory
use, but you should keep backups of the mounted data directory and encryption
key before upgrading.

For the project contract and compatibility policy, see [PLAN.md](PLAN.md). For
release notes, see [RELEASE_NOTES.md](RELEASE_NOTES.md).

## Quick Start

For real secret storage, use a persistent encryption key. The command below
generates one and prints it once. Save it somewhere safe before storing secrets.

Run Glyph Hold with one Docker command:

```bash
GLYPHHOLD_KEY="$(openssl rand -hex 32)" && \
docker run -d \
  --name glyphhold \
  --restart unless-stopped \
  -p 5995:5995 \
  -v glyphhold-data:/data \
  -e GLYPHHOLD_DB_PATH=/data/glyphhold.sqlite \
  -e GLYPHHOLD_ENCRYPTION_KEY="$GLYPHHOLD_KEY" \
  ghcr.io/dosk3n/glyphhold:0.1.0-beta && \
printf 'Save this Glyph Hold encryption key: %s\n' "$GLYPHHOLD_KEY"
```

Open:

```text
http://localhost:5995
```

On first run, Glyph Hold asks you to create the dashboard username and password.
After setup, create an API key from the dashboard and use that key in your
agent.

## Docker Compose

Create a `docker-compose.yml`:

```yaml
services:
  glyphhold:
    image: ghcr.io/dosk3n/glyphhold:0.1.0-beta
    container_name: glyphhold
    ports:
      - "5995:5995"
    volumes:
      - ./data:/data
    environment:
      GLYPHHOLD_DB_PATH: /data/glyphhold.sqlite
      GLYPHHOLD_ENCRYPTION_KEY: change-this-to-a-long-random-value
      GLYPHHOLD_LOG_LEVEL: INFO
      GLYPHHOLD_LOG_FORMAT: pretty
    healthcheck:
      test:
        [
          "CMD",
          "python",
          "-c",
          "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5995/api/v1/health', timeout=3).read()",
        ]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
    restart: unless-stopped
```

Start it:

```bash
docker compose up -d
```

Open:

```text
http://localhost:5995
```

You can also copy the included examples:

```bash
cp .env.example .env
cp docker-compose.example.yml docker-compose.yml
```

Edit `.env` before storing real secrets.

Generate a persistent encryption key with:

```bash
openssl rand -hex 32
```

## First Run

1. Open `http://localhost:5995`.
2. Create the first dashboard admin user.
3. Go to **API Keys**.
4. Create an API key for your agent.
5. Copy the key immediately. It is shown once.

API keys use the `gh_live_` prefix. Glyph Hold stores only a hash and a short
non-sensitive prefix.

## Connect An Agent

Agents call Glyph Hold over HTTP:

```text
GLYPHHOLD_URL=http://localhost:5995
GLYPHHOLD_API_KEY=gh_live_xxxxxxxxxxxxxxxxx
```

For another container on the same Docker network, use:

```text
GLYPHHOLD_URL=http://glyphhold:5995
GLYPHHOLD_API_KEY=gh_live_xxxxxxxxxxxxxxxxx
```

The public API starts at `/api/v1`.

More connection examples are in [AGENT_CONNECTIONS.md](AGENT_CONNECTIONS.md).

Useful endpoints:

```text
GET  /api/v1/health
GET  /api/v1/categories
POST /api/v1/memories/search
POST /api/v1/agent/prefetch
POST /api/v1/secrets/GLYPHHOLD_SONARR_API_KEY/reveal
POST /api/v1/secrets/env
```

## Python Client

Glyph Hold includes a small Python HTTP client package named `glyphhold_client`.
It is a convenience wrapper around `/api/v1` for projects that want to call
Glyph Hold without hand-writing HTTP requests.

```python
from glyphhold_client import GlyphHoldClient

client = GlyphHoldClient(
    base_url="http://localhost:5995",
    api_key="gh_live_xxxxxxxxxxxxxxxxx",
)

results = client.search_memories(query="project context")
```

The client can also create memories, create secrets, reveal individual secrets,
and request scoped env-style secret bundles.

Future Nexus and Hermes integrations will live in separate repositories so this
project stays focused on the Glyph Hold service.

## Memories

Memories are structured notes for agents. They can be categorized, tagged,
searched, edited, archived, and restored from revisions.

Default categories include:

- people
- servers
- services
- projects
- procedures
- preferences
- decisions
- facts
- temporary

Search is deterministic. There is no semantic/vector search.

## Secrets

Secret storage requires:

```text
GLYPHHOLD_ENCRYPTION_KEY=<long-random-value>
```

If no encryption key is configured, Glyph Hold still runs and memory features
continue to work. Secret create/reveal/env actions return a clear configuration
error until the key is set.

Secret rules:

- Secret names must be uppercase `GLYPHHOLD_*` environment variable names.
- Secret values are encrypted at rest.
- Secret values are never returned by memory search.
- Secret values are never included in agent prefetch.
- Secret metadata and reveal access require `secrets:reveal`.
- Secret create/update/delete requires `secrets:write`.
- Secret values are shown only for explicit reveal actions.

Use a persistent encryption key. If you lose or change the key, existing stored
secret values cannot be decrypted.

## Data And Backups

Glyph Hold stores data in SQLite. In Docker, mount `/data` and back it up.

With the compose example, the database lives under:

```text
./data/glyphhold.sqlite
```

Before upgrading:

1. Stop the container.
2. Back up the `data` directory.
3. Pull or switch to the new image tag.
4. Start the container again.

Startup applies pending migrations automatically.

Detailed backup and restore steps are in
[BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md).

Troubleshooting steps are in [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Image Tags

Images are published to GitHub Container Registry:

```text
ghcr.io/dosk3n/glyphhold:0.1.0-beta
ghcr.io/dosk3n/glyphhold:sha-<commit>
ghcr.io/dosk3n/glyphhold:latest
```

Recommended usage:

- Pin an exact version such as `0.1.0-beta` for predictable deployments.
- Use `latest` only when you are comfortable receiving newer changes.
- Back up `/data` before major upgrades.

Prerelease tags do not move `latest`.

## Security Notes

- Do not expose Glyph Hold publicly without a reverse proxy, HTTPS, and access
  controls.
- Do not commit `.env`, SQLite databases, encryption keys, API keys, or exported
  secrets.
- Dashboard setup happens on first browser visit.
- Agents authenticate with bearer API keys created from the dashboard.
- Secret values are encrypted at rest when `GLYPHHOLD_ENCRYPTION_KEY` is set.
- Secret values are not included in memory prefetch.

## For Contributors

Development setup, tests, and release checks are in [CONTRIBUTING.md](CONTRIBUTING.md).
