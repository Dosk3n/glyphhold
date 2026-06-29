# Agent Connections

Glyph Hold is an HTTP service. Agents should connect through `/api/v1` with a
dashboard-created API key.

Do not point agents at the SQLite database directly.

## Environment Variables

Use these values in the agent or tool that should remember things:

```text
GLYPHHOLD_URL=http://localhost:5995
GLYPHHOLD_API_KEY=gh_live_xxxxxxxxxxxxxxxxx
```

For another container on the same Docker network:

```text
GLYPHHOLD_URL=http://glyphhold:5995
GLYPHHOLD_API_KEY=gh_live_xxxxxxxxxxxxxxxxx
```

Recommended scopes:

- memory-only agent: `memories:read`, `memories:write`
- read-only context agent: `memories:read`
- secret reader: `secrets:reveal`
- secret manager: `secrets:write`, `secrets:reveal`
- dashboard activity reader: `events:read`

Only grant secret scopes to tools that need them.

## HTTP Examples

Health check:

```bash
curl "$GLYPHHOLD_URL/api/v1/health"
```

Search memories:

```bash
curl -s "$GLYPHHOLD_URL/api/v1/memories/search" \
  -H "Authorization: Bearer $GLYPHHOLD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"project context","limit":5}'
```

Store a memory:

```bash
curl -s "$GLYPHHOLD_URL/api/v1/memories" \
  -H "Authorization: Bearer $GLYPHHOLD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "category_id": "cat_projects",
    "title": "Deployment decision",
    "summary": "Glyph Hold runs on port 5995.",
    "body": "Use Docker and mount /data for persistent storage.",
    "tags": ["deployment"],
    "confidence": 4,
    "auto_prefetch_level": "normal"
  }'
```

Ask Glyph Hold what context should be injected before an agent response:

```bash
curl -s "$GLYPHHOLD_URL/api/v1/agent/prefetch" \
  -H "Authorization: Bearer $GLYPHHOLD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"agent":"codex","message":"What should I remember about deployment?"}'
```

Reveal one secret explicitly:

```bash
curl -s "$GLYPHHOLD_URL/api/v1/secrets/CUSTOM_API_KEY_HERE/reveal" \
  -H "Authorization: Bearer $GLYPHHOLD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"requesting_agent":"codex","purpose":"deployment"}'
```

Secret names must be uppercase environment variable names, such as
`CUSTOM_API_KEY_HERE`.

## Python Client

The `glyphhold_client` package is a thin wrapper around the same HTTP API.

```python
import os

from glyphhold_client import GlyphHoldClient

client = GlyphHoldClient(
    base_url=os.environ["GLYPHHOLD_URL"],
    api_key=os.environ["GLYPHHOLD_API_KEY"],
)

client.create_memory(
    category_id="cat_projects",
    title="Deployment decision",
    summary="Glyph Hold runs on port 5995.",
    body="Use Docker and mount /data for persistent storage.",
    tags=["deployment"],
    confidence=4,
)

context = client.prefetch(
    agent="codex",
    message="What should I remember about deployment?",
)

secret = client.reveal_secret(
    "CUSTOM_API_KEY_HERE",
    requesting_agent="codex",
    purpose="deployment",
)
```

Future Nexus and Hermes integrations should use this HTTP contract from their
own repositories.
