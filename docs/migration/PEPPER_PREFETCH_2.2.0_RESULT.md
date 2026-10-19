# Pepper selective recall release — 19 October 2026

Glyph Hold **2.2.0** is running and healthy on Pepper. Compose remains
`/opt/appdata/glyphhold2/docker-compose.yml`, project `glyphhold2`, port 5995.
Published image:
`ghcr.io/dosk3n/glyphhold:2.2.0@sha256:450a85db5f608f06a82ad417884b567466f14d0d24ee01a4c3e34dcd38c818d9`.
The installed retrieval source matches the frozen tested candidate.

Source/tag: `9a27fc0` / `v2.2.0`. Backend/dashboard CI and verified amd64/arm64
publication succeeded. All **236** local backend/adapter checks passed, including
the contract against Pepper's actual installed Hermes memory-provider base.
Disposable authenticated HTTP checks passed before release.

## Workflow evidence

Two blinded independent workers each answered the same 16 frozen cases correctly.
A third reviewer checked that all personal facts had same-case source support.
Complete prefetch JSON fell from 31,488 to 11,316 characters (64.1%); search calls
rose from nine to eleven. Each worker made one full-record read. This is a small
batch comparison, not isolated fresh turns, a multi-model study or a measurement
of the live Hermes model's answer accuracy.

The earlier 108-message retrieval-only comparison reduced unrelated injections
from 103 to 15 cases, while required-record coverage fell from 74/88 to 68/88.
This release deliberately treats automatic recall as selective first-stage context
with explicit search for missing facts. It does not enable semantic retrieval.
See [the workflow review](../../evaluations/prefetch/WORKFLOW_RELEASE_REVIEW.md).

## Installed integrations

- Hermes native provider **2.2.0**, source `d8ebf7a`, installed at the existing
  `/home/dean/.hermes/plugins/memory/glyphhold` path and alias. Profile connection
  settings are preserved. Gateway restarted and active; Hermes reports the provider
  installed, available and active. Actual native prefetch/search/get calls passed.
- MCP connector **2.2.0**, source `21c7609`, installed in the existing
  `/opt/appdata/glyphhold_mcp` environment. Fresh stdio handshake, 24-tool catalog,
  selective prefetch, explicit search and full-record read passed. Existing
  sessions need reconnection to receive the revised tool descriptions.
- Nexus pack **2.2.0**, source `f74bde6`, published and staged at
  `/opt/appdata/glyphhold2-migration/nexus-v2.2.0`. Actual pack calls passed in a
  disposable sidecar using Pepper's existing Nexus HTTP image. Glyph Hold is not
  in that HTTP instance's enabled pack list; that list/service was preserved.

The browser hostname's existing Authelia policy returns HTTP 401 HTML for API
requests before they reach Glyph Hold. Public HTTPS API success through that
hostname was therefore **not verified**. Local/native/MCP and Nexus calls passed.
No reverse-proxy policy was changed as part of this retrieval release.

## Data preservation and rollback

Private backup:
`/opt/appdata/backups/glyphhold/before-prefetch-2.2.0-20261019T085416Z`.
It contains the complete original Glyph Hold folder archive, installed adapters,
profile/configuration copies, a separately consistent SQLite snapshot, checksums
and restoration notes. Archives were fully read and the SQLite snapshot was
restored and integrity-checked. Directory 0700; files 0600. The folder archive
was taken online; its separate verified SQLite snapshot is authoritative for a
database restore.

Before/after fingerprints matched for all **80 memories**, categories, revisions,
**16 secret handles** and provenance, spaces, subjects, guidance, connection grants,
dashboard accounts, API key hashes/permissions, provider settings, Advanced Memory
configuration, encryption material and the Codex authentication file. Database
integrity remains OK. Validation created no production memories or secrets.

The old 2.1.3 image and `docker-compose.before2.2.0.yml` remain available. No schema
migration occurred. For a code rollback retain current data, restore the previous
image and adapter source, restart Hermes and verify its provider. Preserve later
writes before considering a full backup restore. Do not use GH1 against this DB.
Earlier GH1 folders/backups and the GH1 `latest` image policy remain unchanged.

Machine-readable outcome:
`/opt/appdata/glyphhold2-migration/PREFETCH_2.2.0_RESULT.json` and
[release-validation.json](../../evaluations/prefetch/release-validation.json).
