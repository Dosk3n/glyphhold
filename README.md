# Glyph Hold 2

A self-hosted memory and secrets service shared by agents on different machines.
Work, Personal and General spaces keep ownership explicit. Hermes native memory
and tool-based clients use the same scoped HTTP API. Projects are optional.

Core memory uses SQLite/FTS5 and requires no AI account, API credits, embeddings
or vector service. Optional **Advanced Memory** uses the official Codex CLI with
ChatGPT subscription sign-in to maintain source-backed profiles and propose
consolidation and space placement. It is disabled by default.

## Local isolated evaluation

Do not point this test service at a live Glyph Hold data directory.

```bash
docker compose -p glyphhold2-test -f docker-compose.gh2-test.yml up --build -d
```

Open **http://localhost:5996**, create a dashboard administrator, and use the
Spaces page to configure connection defaults and read/write grants. This Compose
file uses `glyphhold:gh2-local-test` and its own named volume. It does not replace
the existing instance on port 5995. No image publishing is required.

```bash
docker compose -p glyphhold2-test -f docker-compose.gh2-test.yml logs --tail=100
docker compose -p glyphhold2-test -f docker-compose.gh2-test.yml down
```

`down` retains the test volume; `down -v` permanently removes its data, encryption
key and saved logins. Do not use `-v` when preserving an installation.

## Single-container installation

The image contains the web application, dashboard, Codex CLI and Bitwarden CLI.
Only one service and one persistent data volume are required. Pin a tested image
version such as `ghcr.io/dosk3n/glyphhold:2.2.0`. The `latest` tag also tracks
the current release; use a version tag when you want upgrades to be explicit.

```yaml
services:
  glyphhold:
    image: ghcr.io/dosk3n/glyphhold:2.2.0
    ports:
      - "127.0.0.1:5995:5995"
    volumes:
      - glyphhold-data:/data
    environment:
      GLYPHHOLD_DB_PATH: /data/glyphhold.sqlite
    restart: unless-stopped
volumes:
  glyphhold-data:
```

Use a TLS reverse proxy for remote access and secure cookies when serving HTTPS.
Container `/data` includes the database, installation encryption key and private
provider/runner state. The Codex subprocess uses a separate unprivileged account
and receives a bounded memory batch rather than database access.

## Spaces and connections

Each record has one owning space. Every API key needs explicit space grants;
even an API `admin` scope does not implicitly grant all spaces. A connection's
default space is the fallback for normal writes/recall. Explicit request context
and isolated session context can override it within the same grants.

Automatic recall includes the active space and permitted General records within
a size budget. Broader discovery is explicit. Searching another space does not
change where subsequent writes go. Categories classify information and never
act as permission boundaries. General is not a destination for unknown ownership.

## Automatic recall

Automatic recall uses quoted whole-word full-text queries, conservative inflections,
exact address/hostname matching and confirmed subject aliases. Conversational filler
and repeated terms do not increase ranking. BM25 leads the ordering, with bounded
priority and subject boosts; weak matches can return no topical context. Explicit
search remains available for wider discovery and does not change the write space.

Category `allow_auto_prefetch=false`, archived/superseded/merged records, stale
derived records and per-record `never` are excluded. `high` and `low` adjust the
ranking of relevant records. A `pinned` record in General provides bounded background
context; a pin in another space still needs to match the request. No memories are
automatically moved to General. Existing task pins may consequently appear less
often than in older versions.

Selected memories share the context budget before packing. Long bodies return
query-matching passages and ending context, labelled `excerpted` and `truncated`;
clients can retrieve the full record by ID. Excerpts copy source text rather than
generate a new account of the facts. The serialized result size stays within the
requested character budget.

This lexical path needs no model or API credits. It does not understand every
paraphrase or resolve conversational pronouns. Local semantic fallback is currently
an evaluation experiment, not a runtime dependency. See
[the retrieval evaluation](evaluations/prefetch/CANDIDATE_REVIEW.md) for measured
trade-offs and deployment status.

The dashboard supports spaces, grants, confirmed placement guidance, memory
editing with version checks, history, migration and optional integration settings.

## Advanced Memory

Enable it under Settings after completing official Codex sign-in. The server
shows a device sign-in link and code for your browser; GH2 does not ask for your
ChatGPT password. The server must have internet access and your account must
permit device-code login. Saved login state persists in the data volume.

Choose a model from the runner's available catalog or enter a supported model
ID, then choose reasoning effort where supported. The account default is also
available. Models and reasoning support depend on your account and CLI version;
GH2 does not claim that any particular model is free or available to everyone.

Schedules support hourly (minute), daily (hour/minute), weekly (day/hour/minute),
an explicit timezone, next-run display and Run now. No changed work means no
model call. Initial review can include older/imported records. Batch, context
and runtime controls bound work. Failures pause for inspection/resume and never
fall back to a paid API.

The model proposes evidence-backed profiles/summaries, duplicate merges,
superseding and placement questions. Existing-record moves always require review.
Choose proposal-only or automatic reversible maintenance. Source changes
invalidate dependent summaries; originals and revisions remain traceable.
Generated profiles are not independent corroborating facts. Uncertain identities
and contradictions stay unresolved. Secret values are excluded from maintenance.

Codex runs consume your existing subscription allowance. The desktop app need
not be open. Login, model availability and actual semantic quality must be tested
with your own account; mock tests do not establish these live behaviours.

## Secrets and Bitwarden / Vaultwarden

Built-in secrets work by default. First startup generates `/data/encryption.key`
with restrictive permissions, independently of SQLite. Restarts and upgrades
reuse it. Missing/incompatible keys over encrypted data fail rather than silently
replace the key. `GLYPHHOLD_ENCRYPTION_KEY` remains an advanced external-key
option; retain the original v1 key when upgrading existing encrypted data.

Settings offers an optional Password Manager provider, disabled by default.
Enter the self-hosted server URL (or Bitwarden service URL), personal API client
ID/secret and master password. Sensitive configuration is encrypted in SQLite;
saved credentials are never returned to the browser. Automatic unlock uses the
official CLI and an in-memory unlock session. A separate password file is not
required. Bitwarden Secrets Manager is a different product and is not used.

Secrets are global and independent of memory spaces. When enabled, searches
query all accessible vault entries directly, including existing logins, SSH keys,
secure notes, cards, identities and custom fields. No registration, linking or
import into Glyph Hold is needed. Metadata excludes values; reveal selects one
field. Search matches entry names, folder names, saved website origins and
hostnames, including IP addresses. URL metadata strips userinfo, paths, queries
and fragments; full website queries also match their hostname, including entries saved without
a scheme or with a different port/protocol.
Multiple matches remain separate and require an explicit target ID. Existing built-in secrets remain available, identified by provider.

Folders are optional organisation: list/create folders, pass a folder ID when
creating a secret, or use the configured default/unfiled destination. They do
not map to memory spaces or restrict secret access. API keys still need the
separate `secrets:reveal` and `secrets:write` permissions. External writes have
an additional enable switch. Save settings before testing; the saved connection
can be tested while the provider remains disabled.

Duplicate names produce conflicts instead of creating or choosing an item.
Use IDs and a selected field to resolve ambiguity. `migrate_secret` transfers
built-in values server-to-server: verify an existing target has the identical
value, or create only if no same-name item exists. Different values stop for
review; no plaintext export or silent overwrite occurs. Transfers are explicit,
not a consequence of enabling the provider. Existing IDs remain compatible.

Vaultwarden outages produce errors, not empty searches or silent local writes.
Built-in-only searches remain available with `provider_name=builtin`. Provider
IDs are account-bound, and metadata versions detect stale edits. The official
CLI maintains its own encrypted cache and syncs before operations; external
values are not saved in Glyph Hold's SQL tables. Atomic conflict detection
against simultaneous edits in another Bitwarden client cannot be guaranteed.
Compatibility validation: Bitwarden CLI 2026.10.0 with Vaultwarden 1.37.4;
also verified against an existing 600-item self-hosted vault. The latter check
used search and retrieval; write/conflict/transfer tests used disposable items.
Direct vault deletion stays in Bitwarden/Vaultwarden; removing a legacy Glyph
Hold reference retains its upstream item. Back up the full data volume and key.

## Migration and backups

Before an in-place v1-to-v2 schema upgrade, GH2 creates a consistent SQLite
snapshot in `/data/backups/pre-gh2-*.sqlite`. Back up the original key separately.
Older records and secrets enter restricted Import review ownership. Assign
spaces deliberately before granting agents access.

To export another installation's memories using a read-only source database:

```bash
glyphhold-admin export-memory --database /path/to/source.sqlite --output memories.json
```

This excludes secrets. The dashboard Migration page previews the export with a
source namespace and destination space, then performs a repeatable import.
Use a different namespace per source installation. Preserve source backups until
counts, revisions, references and representative searches have been checked.
Advanced Memory classification is optional and follows faithful import.

```bash
glyphhold-admin backup --output /safe/path/glyphhold-backup.sqlite
```

A complete recovery also needs the installation encryption key or original
external key. Private Codex/Bitwarden state contains authentication material;
protect full-volume backups accordingly. Stop the service when restoring a
matched database/key backup. Reverting to v1 after new v2 writes requires
reconciliation; never run v1 against a migrated database as a rollback shortcut.

## Agent API and upgrades

Use `/api/v2`; see `/docs` for the running API. Key capabilities:

- `GET /capabilities`, `/spaces`, `/guidance`, `/subjects`, `/context`.
- `POST /recall` and `/search` with `query`, optional `space_id`, explicit `broaden`.
- `POST /memories` with a stable `idempotency_key` (or `Idempotency-Key` header).
- `PATCH /memories/{id}` with `expected_version`; stale writes return HTTP409.
- Memory revisions, explicit moves/restores and global provider-neutral secret metadata/reveal.

`glyphhold_client.GlyphHoldV2Client` is the standard-library client. The sibling
`glyphhold-hermes-memory` provider is upgraded separately. Tool packs should
advertise version/idempotency and space selection instead of forwarding old
unscoped calls. Tool access alone does not guarantee automatic prefetch in hosts
without lifecycle integration.

Old v1 data routes return HTTP410 by default to prevent bypassing space grants.
`/api/v1/health` and category discovery remain available. A temporary
`GLYPHHOLD_ALLOW_LEGACY_API=true` switch exists for controlled regression/migration
only: it exposes unscoped legacy data access and must not be enabled in a normal
GH2 multi-space deployment. Upgrade clients before cutover.

See [GLYPHHOLD_2_PLAN.md](GLYPHHOLD_2_PLAN.md) for the product design and quality
requirements, and [CONTRIBUTING.md](CONTRIBUTING.md) for local checks.
