# Connecting Agents to GH2

GH2 uses `/api/v2` for scoped data access. The old unscoped v1 data endpoints are
closed by default. Upgrade adapters before switching an existing client URL.
Do not repoint a live agent at the test service during development.

## Connection setup

1. Create a dashboard API key with the required operation scopes.
2. In Spaces, grant explicit read/write access and choose its default space.
3. Give each host/profile its own key when defaults or permissions differ.
4. Configure the chosen adapter's GH URL and key in its private environment.
5. Verify capabilities, empty/scoped recall, one test write and a version conflict.

A work laptop can default to Work and a home PC to Personal. General requires an
explicit read grant. An API `admin` scope does not implicitly grant every space.
Explicit request space takes precedence over session context, then connection
default; all choices remain constrained by grants. Broader search does not switch
the write destination. Start a fresh conversation for strong context separation;
GH2 cannot remove already injected information from a running model conversation.

## Local adapters

The following sibling repositories have GH2 implementations:

- `glyphhold-hermes-memory` **2.0.1**: native Hermes prefetch plus explicit durable tools.
- `nexus-tools-glyphhold` **0.2.0**: Nexus tool pack for scoped recall and lifecycle.
- `glyphhold-mcp` **0.2.0**: direct MCP server for Codex and other MCP clients.

They remain separate packages and must be installed/restarted in their host
runtimes deliberately. Local tests are not a claim that installed live runtime
packages have changed. Nothing requires switching your currently working v1
agents while evaluating GH2.

The standard-library `glyphhold_client.GlyphHoldV2Client` provides the common
HTTP contract. Preserve IDs, versions, spaces, source references and freshness
when rendering recalled context. Mutations require expected versions; creates
need stable operation idempotency keys. On HTTP409, reread and reassess rather
than blindly overwriting.

## Hermes ownership

Hermes automatic prefetch uses profile-isolated configuration and supplies
session context. Explicit Glyph Hold tools are the authoritative shared-write
path. The incomplete v1 additions-only native mirror is removed; local
MEMORY.md/USER.md can still serve host-local purposes, without implying that
local scratchpad deletion globally removes a shared fact. No transcript capture
is added just because a turn hook exists. Backend failures are observable.

## Advanced Memory

All clients benefit from the maintained records through the same recall API.
They do not need a separate model call to generate each profile on read and must
not each start a consolidation schedule. GH2 owns the schedule and job policy.
The bundled Codex worker has its own official subscription sign-in under
Settings; agent API keys and secrets are not its OpenAI authentication.

## Secrets

Secret metadata and explicit reveals use the same GH2 API regardless of built-in
or Bitwarden/Vaultwarden storage. A client needs both the appropriate operation
scope and space grant. Secret values never belong in prefetch or ordinary memory
exports. Use IDs when identical names exist in multiple permitted spaces. Only
retrieve values for an explicitly authorised task; do not print them into chats
or logs unnecessarily.
