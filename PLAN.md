# Glyph Hold Project Plan

Glyph Hold is a local, deterministic memory and secrets service for agents. It
owns shared memories and shared secrets; agents are HTTP clients.

The service must be safe to publish on GitHub, easy to run in Docker, and
designed so users can pull newer images without breaking existing data.

## Core Principles

- Local-first and self-hosted.
- No LLM calls, embeddings, hosted AI APIs, vector databases, Ollama, or paid
  services inside Glyph Hold.
- SQLite is owned only by the Glyph Hold service.
- Agents, dashboards, plugins, and integrations use the HTTP API.
- Secrets are operationally separate from memories.
- Secret values are never returned except from explicit reveal/env endpoints.
- Secret values are never logged.
- Public API starts versioned at `/api/v1`.
- Database upgrades are handled by migrations.
- Docker image releases are tagged so users can pin stable versions.

## Public API Versioning

All public API routes start at:

```text
/api/v1
```

Examples:

```text
GET  /api/v1/health
POST /api/v1/memories/search
POST /api/v1/secrets/{id_or_name}/reveal
POST /api/v1/agent/prefetch
```

Compatibility policy:

- Patch releases should not break API behavior.
- Minor releases may add optional fields, routes, filters, and response data.
- Major releases may introduce breaking API or database changes.
- Deprecated fields/routes should remain available for at least one minor
  release where practical.

## Docker And GitHub Container Registry

The project will publish Docker images to GitHub Container Registry under the
owner's personal GitHub account.

The service listens on port `5995` inside the container. The default Docker
mapping is `5995:5995`, so users open `http://localhost:5995`.

Expected image names:

```text
ghcr.io/dosk3n/glyphhold:latest
ghcr.io/dosk3n/glyphhold:0.1
ghcr.io/dosk3n/glyphhold:0.1.0
ghcr.io/dosk3n/glyphhold:sha-<commit>
```

Recommended user behavior:

- Use `latest` only when comfortable receiving new changes.
- Pin `0.1` for compatible updates within a minor series.
- Pin `0.1.0` for an exact release.
- Back up the mounted data directory before major upgrades.

## Repository Safety

The repository is intended to be public.

Never commit:

- Real `.env` files.
- SQLite databases.
- WAL/SHM files.
- Encryption keys.
- API keys.
- Exported secrets.
- Local Docker volumes.
- Local compose overrides containing secrets.

Commit examples and templates instead:

- `.env.example`
- `docker-compose.example.yml`
- test fixtures with fake data only

## Runtime Configuration

Important environment variables:

```text
GLYPHHOLD_DB_PATH=/data/glyphhold.sqlite
GLYPHHOLD_ENCRYPTION_KEY=<long-random-value>
GLYPHHOLD_LOG_LEVEL=INFO
GLYPHHOLD_LOG_FORMAT=pretty
GLYPHHOLD_EVENT_RETENTION_DAYS=90
GLYPHHOLD_MAX_EVENT_ROWS=100000
```

Dashboard bootstrap should not require a preconfigured admin password. First-run
setup happens in the browser.

## Dashboard Authentication

Dashboard users authenticate with username and password.

First-run flow:

1. User starts the Docker container.
2. User opens the dashboard.
3. Glyph Hold checks whether any dashboard admin user exists.
4. If no admin exists, the dashboard shows a setup page.
5. User enters username, password, and confirm password.
6. Glyph Hold stores the username and a password hash.
7. Setup mode is disabled permanently unless the database is reset.
8. User is redirected to the normal login page.

Dashboard user table should include:

```text
dashboard_users
- id
- username
- password_hash
- is_admin
- created_at
- updated_at
- last_login_at
```

Password rules:

- Store password hashes only.
- Use Argon2 or bcrypt.
- Never store plaintext passwords.
- Never log passwords.

Session rules:

- Use signed HTTP-only cookies.
- Use secure cookies when running behind HTTPS.
- Sessions are separate from agent API keys.

## API Key Authentication

Agents authenticate with bearer API keys.

Users may create:

- one shared API key used by several clients, or
- one API key per agent/tool for better auditing and revocation.

API keys are created from the dashboard.

API key creation flow:

1. Dashboard user opens API Keys page.
2. User creates a key with name, actor, description, and scopes.
3. Glyph Hold generates a long random key.
4. The key is shown once.
5. Glyph Hold stores only a hash and a non-sensitive prefix.
6. User copies the key into the agent's environment/config.

Example agent config:

```text
GLYPHHOLD_URL=http://glyphhold:5995
GLYPHHOLD_API_KEY=gh_live_xxxxxxxxxxxxxxxxx
```

API key table should include:

```text
api_keys
- id
- name
- actor
- description
- key_prefix
- key_hash
- scopes_json
- enabled
- created_at
- updated_at
- last_used_at
```

Initial scopes:

```text
memories:read
memories:write
secrets:write
secrets:reveal
events:read
admin
```

The authenticated API key determines the actor for audit logs. Actor headers may
be accepted as additional context, but they must not override a named key's
identity.

## Secret Encryption

Secret values are encrypted at rest.

Required behavior:

- Encryption key comes from `GLYPHHOLD_ENCRYPTION_KEY`.
- Encryption key is never stored in SQLite.
- Encryption key is never printed or logged.
- Secret values are never logged.
- Secret values are masked in the dashboard by default.

Recommended v1 behavior if `GLYPHHOLD_ENCRYPTION_KEY` is missing:

- App still starts.
- Memories, categories, tags, events, and dashboard auth continue to work.
- Secret create/reveal/env endpoints return a clear configuration error.
- Dashboard secrets page shows that secret storage is disabled until an
  encryption key is configured.

Secrets table should include crypto metadata for future migration:

```text
encrypted_value
encryption_version
encryption_key_id
```

## Database And Migrations

SQLite is the v1 database.

Use:

```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;
```

Migrations are required from the first implementation.

Migration table:

```text
schema_migrations
- version
- name
- applied_at
```

Rules:

- Startup applies pending migrations automatically.
- Migrations are ordered and deterministic.
- Avoid destructive migrations in v1.
- Do not drop columns in patch/minor releases unless a major migration plan
  exists.
- Downgrades are not guaranteed.
- Users should back up `/data` before major upgrades.

## Logging And Audit

Glyph Hold has two logging layers:

- app logs to stdout/stderr for Docker logs
- internal event log in SQLite for dashboard inspection

Every request gets a request ID:

- accept `X-Request-ID` from the client when provided
- otherwise generate one
- return `X-Request-ID` in the response
- include the same ID in app logs and event logs

Event log tracks:

```text
agent.prefetch
memory.search
memory.find_similar
memory.prepare_write
memory.create
memory.update
memory.confidence_update
memory.archive
memory.supersede
secret.search
secret.create
secret.update
secret.delete
secret.reveal
secret.env
category.create
category.update
auth.failed
request.error
```

Never log raw request bodies by default. Redact fields named or treated as:

```text
value
secret
password
token
api_key
webhook
encrypted_value
```

## Dashboard Scope

The dashboard is part of v1 and should be server-rendered with FastAPI and
Jinja templates.

Pages:

- first-run setup
- login/logout
- home/status
- memories
- memory detail and revisions
- categories
- secrets
- API keys
- activity/audit

The dashboard should be functional and plain. It should prioritize safety,
clarity, and reliable forms over visual polish.

## Memory Scope

Memories include:

```text
id
category_id
title
summary
body
tags_json
metadata_json
source
confidence
auto_prefetch_level
archived
superseded_by
created_at
updated_at
```

Default categories:

```text
people
servers
services
projects
procedures
preferences
decisions
facts
temporary
```

Memory search is deterministic:

- SQLite FTS5
- exact title matching
- category filters
- tag matching
- confidence
- auto-prefetch level
- archived/superseded filtering

No semantic/vector search.

## Secrets Scope

Secrets include:

```text
id
name
description
encrypted_value
encryption_version
encryption_key_id
value_type
service
host
scope
tags_json
allowed_agents_json
allowed_tools_json
created_at
updated_at
last_revealed_at
```

Secret search returns metadata only and requires `secrets:reveal`. Glyph Hold
does not expose secret names or metadata to API keys without secret access.

Secret values are returned only by:

```text
POST /api/v1/secrets/{id_or_name}/reveal
POST /api/v1/secrets/env
```

Both actions are audited and must never log returned values.

## Prefetch Scope

Prefetch is conservative and deterministic.

Default behavior:

```text
max_memories: 3
max_chars: 1200
max_tokens: 300
summaries_only: true
include_secrets: false
include_archived: false
```

It is acceptable and expected for prefetch to return zero memories.

Prefetch never returns secret values.

## Integrations

Integrations are thin HTTP clients.

Glyph Hold includes one generic Python HTTP client package:

```text
glyphhold_client/
```

External integrations should live in separate repositories so Glyph Hold remains
focused on the server, dashboard, storage, API, Docker image, and generic
client.

Planned external repositories:

```text
glyphhold-nexus
glyphhold-hermes
```

Nexus and Hermes integrations must use the HTTP API and must not access SQLite
directly.

## Build Stages

### Stage 0: Project Contract And Safety

- Create `PLAN.md`.
- Create `.gitignore`.
- Create `.dockerignore`.
- Decide public API versioning.
- Decide dashboard auth model.
- Decide API key model.
- Decide Docker/GHCR release model.

### Stage 1: Core Service

- FastAPI app.
- Config loading.
- SQLite connection management.
- Migration runner.
- Health endpoint at `/api/v1/health`.
- Dockerfile.
- Docker compose example.
- Request ID middleware.
- Structured logging.
- Event log repository.

### Stage 2: Dashboard Auth And API Keys

- First-run setup page.
- Dashboard login/logout.
- Session cookies.
- Dashboard users table.
- Password hashing.
- API keys table.
- API key creation UI.
- Bearer auth for API routes.
- Scope checks.

### Stage 3: Memory CRUD And Search

- Categories.
- Memories.
- FTS5 table and triggers/repository sync.
- Memory search endpoint.
- Dashboard memory/category pages.
- Event logging for memory actions.

### Stage 4: Memory Revisions And Write Workflow

- Save revisions before updates.
- Revision history dashboard.
- Confidence update.
- Archive.
- Supersede.
- Find similar.
- Prepare write.

### Stage 5: Secrets

- Encryption helper.
- Secret CRUD.
- Secret metadata search.
- Secret reveal endpoint.
- Secret env bundle endpoint.
- Dashboard secret pages.
- Strict redaction tests.
- Event logging for secret actions.

### Stage 6: Agent Prefetch

- Deterministic scoring.
- Tag/category/title/FTS matching.
- Conservative prefetch endpoint.
- Character/token budget enforcement.
- Prefetch event logging.
- Dashboard visibility for prefetch events.

### Stage 7: Packaging And Release Automation

- GitHub Actions test workflow.
- Docker build workflow.
- GHCR publish workflow.
- Version tags.
- Release notes.
- Upgrade notes.

### Stage 8: Integrations

- Python API client package.
- Documentation for agent setup.
- Separate Nexus repository plan.
- Separate Hermes repository plan.

## First Public Milestones

### v0.1.0-alpha

- Docker image builds.
- SQLite migrations work.
- Dashboard first-run setup and login work.
- API key creation works.
- Health endpoint works.
- Categories and memories work.
- FTS search works.
- Event log works.
- Basic dashboard loads.
- Python checks run in CI.

### v0.2.0-alpha

- Encrypted secrets.
- Secret reveal.
- Secret env bundle.
- Dashboard secrets UI.
- Redaction tests.
- Secret reveal auditing.
- Dashboard edit/delete flows for memories and secrets.

### v0.3.0-alpha

- Prefetch.
- Find similar.
- Prepare write.
- Memory revisions.
- Memory revision restore.
- Python API client package.
- Nexus/Hermes split documented as separate future repositories.

### v1.0.0

- Stable `/api/v1` contract.
- Documented upgrade policy.
- Documented Docker deployment.
- Dashboard covers all v1 domains.
- Core acceptance criteria pass.
- GHCR publishing is working.

## Open Decisions

- Whether to support multiple dashboard users in v1 or only one admin user.

## Decisions Made During Initial Build

- Public API uses `/api/v1` from the start.
- Dashboard uses first-run username/password setup.
- API keys are created from the dashboard and stored as hashes.
- Users may create one shared API key or one key per agent.
- Docker publishing uses GitHub Container Registry through GitHub Actions.
- GHCR image name is `ghcr.io/dosk3n/glyphhold`.
- Project license is MIT.
- Dashboard sessions use signed HTTP-only cookies with a 14-day timeout.
- API keys use the `gh_live_` prefix.
- First-run dashboard passwords must be at least 12 characters.
- Secrets are disabled when `GLYPHHOLD_ENCRYPTION_KEY` is missing.
