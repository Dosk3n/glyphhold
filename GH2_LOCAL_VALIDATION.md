# Glyph Hold 2 local validation

Date: 18 October 2026. This is a local development build, not a published release
or a production migration. The existing GH container and its data were not
modified. Live client registrations were not switched to the new adapters.

## Deployment

- Image:`glyphhold:gh2-local-test`.
- Compose project:`glyphhold2-test`, using `docker-compose.gh2-test.yml`.
- Dashboard:`http://localhost:5996`.
- Separate named data volume:`glyphhold2-test_glyphhold2-test-data`.
- Bundled official Codex CLI0.163.0 and Bitwarden CLI2026.10.0.
- Advanced Memory and external secrets return to disabled after verification.
- The owner's official Codex subscription sign-in is preserved privately in the
  test volume; no OpenAI API key was used or required.

## Automated checks

**99 backend tests passed** on the host and inside the Python 3.12 image,
including all three adapter-conformance checks.
Run the backend suite with `pytest`; use Python3.12+ and the dev dependencies.
The container rehearsal also mounts the three sibling integration repositories
read-only so adapter-conformance tests run rather than skip.

Coverage includes ownership grants, default/session/request precedence, scoped
recall, bounded indexed candidates, exact serialized budgets, idempotency,
concurrent version conflicts, revisions, source invalidation, provenance loops,
migration repeatability/history, encrypted transfers, CSRF, secret-provider
bindings, scheduled jobs/DST, runner failures and disablement during execution.

The checked-in `scripts/gh2_concurrency_check.py` always creates a disposable
database. Six independent processes perform300 creates, 300 versioned updates and
300 recalls; both SQLite and external-content FTS integrity checks must pass.
Additional tests verify that opening a second connection retains process file
locks and that concurrent subprocess writers preserve all committed rows.

Sibling integration packages were upgraded locally to0.2.0:

- `glyphhold-hermes-memory`:8 tests.
- `nexus-tools-glyphhold`:8 tests.
- `glyphhold-mcp`:15 tests.

Three conformance tests call the actual GH2 backend through those adapter
implementations. These tests do not replace testing each installed host runtime.
No running Hermes/Nexus/MCP installation was changed as part of this rehearsal.

Frontend checks:TypeScript, production Vite build, and npm dependency audit.

## Browser checks

Independent Playwright review exercised:

- Administrator login and all dashboard sections.
- Memory create/edit, version checks, explicit verification, move, revision
  restore, archive and explicit subject registration/attachment.
- Built-in secret create, explicit reveal, edit and unlink.
- Advanced settings, account model catalog and hourly/daily/weekly dropdowns.
- Password-encrypted secret package preview/import with metadata-only output and
  clearing of the transfer passphrase after use.
- Explicit built-in-to-Vaultwarden preview and transfer.
- Mobile390px layout without horizontal overflow and accessible select labels.

Temporary review scripts/screenshots are under `/tmp/gh2-ui-review/`; they use
only synthetic fixtures and a privately stored temporary test administrator.
The test administrator is removed after final verification so the owner can
complete first-run setup with their own credentials.

## Live subscription test

The owner completed the official browser/device login. The signed-in account's
model catalog was loaded without an inference turn. Tests selected GPT-6-Luna,
low reasoning, and fictional Ada Example household facts.

Observed results:

- A profile cited its original source IDs and versions without adding unsupported
  facts.
- Review approval was idempotent and the profile appeared in scoped recall.
- A later automatic run updated the existing profile from an additional fact,
  retaining three original source references.
- A fresh-store run repeated automatic source-backed profile creation after the
  storage fix, with available token usage recorded in run history.
- Unchanged follow-up jobs skipped the model.
- Subscription login survived container recreation. No paid API fallback exists.

This verifies a small real workflow, not universal semantic correctness. The
pending-review path remains necessary for uncertain identity, conflict and moves.

## Live external-secret test

Tests used a disposable Vaultwarden 1.37.4 server with a private test TLS CA,
synthetic account, API credentials and generated keys. The user's real vault was
not accessed. Standard certificate validation remained enabled.

Verified official-CLI authentication/unlock, folders, secure-note creation,
selected-field reveal, value edits/version checks, existing-item links,
automatic unlock after process restart, disabled-provider rejection and an actual
upstream outage without local fallback. Native login username/password and native SSH private/public/fingerprint bindings
also passed against the real CLI and disposable server. Only the requested field
was returned, and the ephemeral SSH key was generated solely for the test. The disposable provider is disabled/cleared afterward.

Warm CLI operations take several seconds; a cold login/unlock may take20–25s.
Secret requests therefore have a longer timeout in the upgraded adapters without
extending their normal recall timeout. External edits cannot promise atomic
conflict detection against independent Bitwarden clients.

## Defects found and corrected during review

- A malformed Authorization header could bypass cookie CSRF checks.
- The SPA catchall shadowed newly added Settings GET routes.
- uvloop did not support subprocess UID/GID arguments; Docker uses asyncio.
- Prior-source moves could leak stale derived or replayed content.
- Provenance and lifecycle cycles needed explicit rejection.
- Legacy revision backfill/export could omit or double history.
- Reconfiguring the saved Bitwarden server while already logged in broke restart.
- The older FTS external-content schema named its tags column differently from
  its source table; a read-only generated alias now supports integrity/rebuild.
- Startup and HTTP health checks now detect database integrity failures and return
  unhealthy status instead of treating a successful SELECT1 as sufficient.
- Opening/closing an existing database file outside SQLite while setting file
  permissions could release POSIX locks and corrupt concurrent writes. Existing
  databases are no longer opened that way. This is the mechanism documented in
  [SQLite section2.2](https://sqlite.org/howtocorrupt.html#_posix_advisory_locks_canceled_by_a_separate_thread_doing_close_).
  The damaged synthetic test database was quarantined; it was not repaired and
  presented as healthy. Fresh-data regression, multiprocess and live tests were
  rerun while preserving the owner's Codex login.

## Release boundary

Publishing images, upgrading the running v1 instance, moving actual memories and
secrets, and installing upgraded adapters into live hosts remain separate
operator actions. The current evidence covers the local app, disposable provider
and a small subscription-authenticated workload. Before real cutover, rehearse on
copies of the owner's actual exports and preserve original encryption keys.

Final state: both v1 (port 5995) and GH2 (port 5996) report healthy. GH2
first-run dashboard setup is available, with the temporary administrator/API
keys removed. Optional features are disabled, Codex sign-in is retained, and
disposable provider containers were removed. Final SQLite and FTS integrity
checks pass. No GitHub push or production cutover was performed.


## Approved dashboard design integration

Implemented the approved light neutral/teal design in the React dashboard, including a generated transparent logo for navigation, authentication and favicon. Shared compact controls, typography and responsive layouts cover all nine pages. Memory/secret/category creation uses explicit actions and dialogs; Settings separates Advanced Memory, secret storage and access guidance, with contextual explanation and collapsible resource limits.

Frontend type checking and Docker production build pass. Browser validation covers all nine pages at four viewport sizes, actual memory create/archive and secret create/reveal/remove, schedule controls and Settings tab navigation. Visual review feedback about tablet account wrapping, card alignment, stretched badges and Activity filters was fixed. The retained Codex connection reports installed=true, authenticated=true, auth_mode=chatgpt.


### Content-length and connection-control regression checks

Memory row metadata now has a fixed260px desktop column, separate badge/date rows, and a deliberate stacked mobile layout. Long summaries, unbroken strings and long titles are clipped without changing date positioning. The redundant idle sign-in callout is hidden; an available worker with no running job shows Idle. Active sign-in instructions and failures remain visible. The Codex model field is now a native select like reasoning, populated from reported models and retaining any saved model absent from that list.

`scripts/gh2_ui_layout_check.cjs` exercises the production frontend with intercepted fixture responses only: six content variants at1500,900,768,390px; idle/pending/failed authentication; native model/reasoning selection; save payload and reload persistence. It can use built assets or a running GH2 via GH2_ASSET_ORIGIN without touching live records.


### Dedicated Memory reviews navigation

Moved proposed improvements, manual review execution and run history from Settings to `/dashboard/memory-reviews`. Settings retains configuration and a link to the operational page; Activity remains the audit log. The new menu item is visible only while Advanced Memory is enabled. Its badge counts pending approvable proposals, excluding clarification questions and completed/rejected entries. Save/decision events update visibility/count immediately, with periodic refresh for background changes.

A count endpoint computes the badge independently of the200-record history window, and pending proposals sort ahead of historical records. Sixteen Advanced Memory backend tests pass, including a205-history-record regression. Browser fixture tests verify off/on/off menu visibility, two approvals plus a clarification question, count changes after approval, deep-link navigation, run details, and layout at desktop/tablet/mobile widths.


## OWASP A01–A05 security review

Five category agents plus a combined review are recorded in [the security report](docs/security/GH2_SECURITY_REVIEW.md). Permission, session-signing, key-file, import-fingerprint, authentication limiter, public-health and mixed-space AI-context fixes are implemented. Runtime dependencies and publishing inputs are locked; unnecessary package installers were removed. Four upstream Bitwarden advisory records remain explicitly documented.

Final checks:131backend tests, Ruff, frontend type/build, served browser regressions, isolated runtime cryptography/session smoke checks and final-image package inventory passed. Live GH2 health/integrity are good; no legacy signing-secret row remains; key0600; worker cannot read key/DB; Codex subscription authentication retained. Anonymous v2memory access401 and docs/schema404. GH1 remained healthy. Existing dashboard cookies expire once, requiring a new local sign-in. External Authelia/proxy routing was not modified; a documented example is provided.
