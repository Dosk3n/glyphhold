# Glyph Hold 2 security review — 18 October 2026

## Scope and deployment boundary

Five independent agent reviews covered OWASP Top10:2025 A01–A05, followed by a combined architecture review and implementation. The dashboard is assumed to be protected by Authelia; the API is publicly reachable and must independently authenticate requests. Reviews used code inspection, temporary databases, synthetic credentials/evidence, dependency inventories and regression tests. No real secret values or model inference jobs were used in the review.

Authelia must cover `/dashboard/api/*`, dashboard assets/pages, setup/login and optional documentation paths. Exempting the whole hostname defeats that deployment boundary. The API has its own bearer keys, operation scopes and explicit space grants. It is still HTTPS-only outside a trusted local network.

## Findings and resolution

| Area | Finding and prerequisite | Change |
|---|---|---|
| A01 access | Medium: keys without memory-read scope could read subjects, guidance and context within a granted space. | Explicit memory-read checks at all metadata/context entry points. |
| A01 access | Medium: ordinary memory-write keys could change global categories; catalogue counts revealed inaccessible memory totals. | Category mutations require a signed dashboard administrator and CSRF; API catalogue omits global counts. |
| A02 configuration | Medium: unauthenticated health requests repeatedly performed full SQLite integrity checks. | Coalesced integrity snapshots refreshed at most once every60seconds; startup still checks integrity and failed snapshots return503. |
| A02 configuration | Medium: rotating login names evaded aggregate IP limits and limiter buckets persisted without bounds. | Independent IP budget, bounded credentials, expiring/bounded limiter storage and no allocation for empty lookups. |
| A02 configuration | Low: missing/malformed API credentials skipped the invalid-key limiter. | Same failure accounting as invalid bearer keys; valid credentials are not blocked by failed-key budgets. |
| A02 configuration | Hardening: public documentation disclosed administrative API structure. | Documentation disabled by default; explicit opt-in and protected proxy paths. Local HTTP secure-cookie default is retained; HTTPS deployments must enable secure cookies. |
| A03 supply chain | Unnecessary vulnerable npm installer tree and pip installer shipped in the runtime. | Only locked required CLI packages are copied; runtime installers/build tools are removed. |
| A03 supply chain | Mutable dependencies/action references and publication independent of verification. | Hash-locked Python artifacts, integrity-locked CLI tree, pinned base digests/action SHAs, verification-gated publication and final-runtime package audit. |
| A04 cryptography | High, requiring a database/backup leak: plaintext dashboard signing secret allowed forged administrator cookies accepted by the public API. | Domain-separated signing key derived from protected installation material; standalone0600key when secret storage is disabled; plaintext legacy setting removed. Existing dashboard cookies expire once. |
| A04 cryptography | Medium: restored key files could retain world-readable permissions. | Descriptor-based owner/regular-file checks, no symlink following, corrected0600permissions. |
| A04 cryptography | Medium, requiring a database leak: plaintext-secret import fingerprints allowed offline guesses. | Versioned keyed HMAC; legacy fingerprints encrypted and reconciled conservatively without overwriting destination secrets. Previously copied backups cannot be retroactively protected. |
| A05 injection | No confirmed SQL, shell/CLI or stored-XSS exploit. | Parameterized SQL, quoted FTS terms, argv subprocesses and escaped React rendering retained; option-like model/item identifiers rejected. |
| A05 AI boundary | Conditional medium: mixed-space model evidence could be misattributed despite valid source IDs. Reproduced using a synthetic model response, not a successful real-model injection. | Each inference batch contains one source space; related subjects/guidance are scoped accordingly. Destination definitions remain available for placement suggestions. Prompt construction rejects mixed evidence. |

## Combined review

The strongest chain was database disclosure → forged dashboard cookie → public API administrator authority. Protecting the dashboard with Authelia alone did not stop that chain because the API accepts valid dashboard sessions. Removing database-held signing material breaks it while preserving existing accounts and encrypted secrets.

Space grants must apply to metadata as well as memory bodies. Global catalogue management is administrative, and write access to one space must not change shared category policy. These fixes intentionally restrict category mutations previously available to ordinary API keys.

Public endpoints must perform bounded work even without credentials. Failure limits are process-local and protect authentication; they are not a substitute for reverse-proxy connection/request limits or upstream DDoS protection. The proxy example applies public API rate limits and protects every non-API path with Authelia.

AI-generated text cannot be proven semantically faithful merely by checking JSON and references. Single-space inference removes a cross-space context source, but incorrect summaries and poisoned content inside an authorized space remain possible. Review-first remains the default; automatic processing remains an explicit trust decision. OS identity separation and disabled worker tools remain permission boundaries.

## Residual upstream dependency risk

The exact final-image Python/npm inventory still contains four advisory records in the official BitwardenCLI2026.10.0 dependency tree:

- `tmp@0.0.33`: GHSA-52f5-9888-hmc6 and GHSA-ph9p-34f9-6g65; local temporary-file preconditions. GH2 uses noninteractive CLI commands.
- `multer@2.3.0`: GHSA-3pph-fpjx-jg34. GH2 does not run `bw serve` or expose its upload handler.
- `node-forge@1.4.0`: GHSA-86w9-cpqp-85rv. No patched upstream version was available at review time; reachability of its vulnerable signature verification through GH2 was not established.

These dependencies are not described as fixed. Exact-version advisory exceptions expire on18November2026; new or expired findings fail the build audit. See [the supply-chain report](A03_SUPPLY_CHAIN_REVIEW.md), [tmp advisory](https://github.com/advisories/GHSA-52f5-9888-hmc6), [multer advisory](https://github.com/advisories/GHSA-3pph-fpjx-jg34), and [node-forge advisory](https://github.com/advisories/GHSA-86w9-cpqp-85rv).

The inventory audit covers Python/npm metadata, not Debian packages or native CLI binaries. This review is not a formal penetration-test certification, and it did not test the user's external reverse proxy or Authelia configuration.

## Validation and operational notes

- Baseline:100backend tests passed before changes.
- Updated suite:131backend tests passed, including access, key/session migration, fingerprints, authentication limits, health concurrency and single-space evidence regressions.
- Frontend type checking and production build are checked separately; browser regression covers the served dashboard with fixture data.
- Runtime smoke checks exercise startup, authenticated encryption, password hashing, session creation and both official CLI entry points without real credentials.
- Final-image inventory ([machine-readable results](SUPPLY_CHAIN_AUDIT.json)):241distinct Python/npm package versions; four documented upstream Bitwarden advisory records, zero findings outside those scoped exceptions.
- Backup created at `/data/gh2-before-security-review.sqlite` before migration. Existing installation encryption key and Codex subscription state are preserved. Dashboard sessions expire once; log in again with the existing account.
- The GH2 image remains isolated onlocalhost5996. GH1 on5995 and external reverse-proxy configuration are outside the changed deployment.

## Deployment checklist for this architecture

1. Finish local first-admin setup before external routing is enabled.
2. Terminate HTTPS at the proxy; set `GLYPHHOLD_COOKIE_SECURE=true`.
3. Apply Authelia to all non-API paths, especially `/dashboard/api/*`, `/setup`, `/login`, `/docs`, `/redoc`, `/openapi.json`.
4. Public `/api/*` routes still require Glyph Hold bearer authentication except health. Keep legacy data access disabled and grant only needed operation scopes and spaces.
5. Restrict direct access to the application port. Trust forwarded client IP headers only from the actual proxy, never wildcard addresses.
6. Apply request-size, timeout, connection and rate limits. Adapt [the proxy example](../../deploy/nginx-authelia.example.conf) to the actual network; it has not been deployed automatically.
7. Keep database, installation keys, Codex login state and backups private. Retain installation keys separately from SQLite; retain session.key too if secret storage is disabled.


Final isolated deployment checks passed: GH2 healthy, SQLite quick_check=ok, legacy database signing-secret row absent, encryption.key mode0600, and worker UID10001 unable to read either database or key. Codex still reports installed/authenticated with ChatGPT mode. Unauthenticated memory API access returns401; disabled docs/schema endpoints return404. Served-frontend regression checks pass. GH1 remained healthy and unchanged.
