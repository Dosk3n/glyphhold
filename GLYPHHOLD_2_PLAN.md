# Glyph Hold 2 — Product and Development Plan

Status: local implementation and validation completed; production cutover has not occurred.  
Date: 18 October 2026.  
Basis: product discussions, review of the Glyph Hold v1.0.3 source and the
Glyph Hold Hermes provider v0.1.0, and a three-agent architecture, integration,
and product review.

This document records the intended direction for Glyph Hold 2. It is the
starting point for detailed API and schema design, rather than a claim that
every proposed field, endpoint, or ranking rule has been finalised. The
original [PLAN.md](PLAN.md) describes the v1 foundation; this document governs
the proposed v2 work.

Implementation evidence, local test coverage, defects corrected during review
and the boundary before production cutover are recorded in
[GH2_LOCAL_VALIDATION.md](GH2_LOCAL_VALIDATION.md).

## 1. Product objective

Build one self-hosted memory service that gives multiple agents relevant,
traceable knowledge and allows them to maintain that knowledge reliably across
machines, conversations, and integrations.

The immediate use case is consolidating separate work and personal Glyph Hold
installations. A work laptop normally operates in Work, a home PC normally
operates in Personal, and both can use permitted General knowledge. An agent
can deliberately search another permitted area when the request calls for it.

Memory must support ordinary questions, server checks, research, people,
preferences, procedures, and decisions. Projects are optional context; users
and agents must never have to invent a project to use memory.

Success means better agent behaviour, not simply more storage organisation:

- Relevant context is available when needed, within a controlled budget.
- Agents can identify, inspect, correct, and cite the records they recall.
- Concurrent agents cannot silently overwrite one another's changes.
- Retries and repeated imports do not produce duplicate records.
- Agents can distinguish confidence, provenance, and freshness.
- Hermes native integration and Nexus tools use the same service rules.
- Existing memories can migrate without losing their meaning or history.
- Core memory remains usable without AI API credits; optional Advanced Memory
  can use an agent subscription the owner already has.

## 2. Agreed direction and boundaries

### One service, multiple spaces

Use a small, enforced ownership boundary called a **space** in this plan.
Initial examples are Work, Personal, and General; users can create others.
The final user-facing name may be space, vault, or another clear term.

This is deliberately vault-like ownership. Its value comes from combining it
with context-aware retrieval and reliable memory maintenance. Renaming vaults
to domains would not itself improve the system.

Each memory has one owning space. A connection can access several spaces,
subject to explicit read/write grants. General is explicitly granted, not
public or automatically available to every agent.

### Preserve the core deployment model

- Self-hosted HTTP service; Glyph Hold alone owns SQLite.
- Integrations remain in separate repositories and use the public API.
- Keep deterministic retrieval as the initial v2 foundation.
- No required LLM calls, embeddings, vector database, or paid service for core
  storage and retrieval. Advanced Memory is an explicitly enabled extension
  using a connected AI runner; it must never become a core dependency.
- Keep secrets operationally separate from memory retrieval.
- Versioned releases, database migrations, recoverable upgrades, and Docker
  remain supported.

### Not required for the first v2 release

- Bidirectional synchronisation between independent Glyph Hold installations.
- A full knowledge graph or mandatory entity/project registry for normal writes.
- Multiple owning spaces for one memory.
- Automatic ingestion of all conversation transcripts.
- Unrestricted autonomous actions or unsupported automatic conflict resolution.
- Replacement of every agent's conversation history or working context.

## 3. Context and ownership model

Keep these concepts separate:

| Concept | Meaning |
| --- | --- |
| Permission | Which spaces and operations the authenticated connection may access |
| Default space | The connection's normal destination and retrieval starting point |
| Active context | The space and optional subjects applicable to this request or conversation |
| Owning space | The space containing a stored record |
| Category | The kind of memory: preference, server, procedure, decision, etc. |
| Subjects/tags | Optional associations with a host, service, person, topic, or project |

Context selection must be request- or conversation-scoped. There must be no
service-wide current space that concurrent agents can change for each other.

Resolution should use explicit request choices first, established session or
workspace associations next, and connection defaults when no more specific
context exists. The exact precedence and override rules must be specified and
tested before implementation. Every resolved choice is constrained by the
authenticated connection's grants.

Textual hints may help rank results or prompt an agent to search elsewhere.
They must not grant access or silently establish a permanent association.
Missing context is a normal case, especially for messaging agents.

Normal writes may use tags or simple structured metadata. Advanced Memory adds
minimal stable subject identities and evidence-backed aliases for people,
servers, organisations, services, and other topics. These are optional for
normal use; a full knowledge graph remains deferred. A name match alone must
not establish that two subjects are the same.

### Example behaviour

| Request | Expected behaviour |
| --- | --- |
| “Check my servers” | Recall relevant server facts and procedures in the active context; clarify if the target remains ambiguous |
| “Check my home server” from a work laptop | Permit deliberate Personal discovery if authorised; do not permanently change the connection's default |
| “Research backup options” | Use relevant existing knowledge and preferences; no project or automatic durable write required |
| “Continue Glyph Hold development” | Use an established project association if available |
| An unrelated general question | Return relevant General preferences or no memory |

General holds broadly applicable information. Work-specific preferences stay
in Work. Where a specific preference differs from a general one, preserve both
and expose their applicability; do not silently merge contradictory prose.

## 4. Memory records and lifecycle

Retain useful v1 content: stable identity, title, summary, body, categories,
tags, source information, timestamps, archive state, and revision history.

Add or formalise:

- Owning space.
- A record version usable as an update precondition.
- Provenance, including source system and original record identity for imports
  or mirrored records.
- Optional verification information, separate from modification time.
- Optional subject context.
- Explicit recall policy independent of category permissions.
- For Advanced Memory, derived-record type, source IDs and source versions,
  freshness/invalidation state, and reversible merge/supersede relationships.

The exact schema is a design-stage deliverable. Prefer a small set of fields
with integration-populated defaults over a form the model must fill in for
every write.

### Confidence and freshness

Confidence is not freshness. A confidently recorded server address can become
obsolete, while an old communication preference can remain valid.

Support a meaningful last-verified timestamp and, where appropriate, a review
or validity policy. Unknown verification time must remain unknown. Reading,
importing, or cosmetically editing a memory must not count as verification.
Evaluate whether the existing five-level confidence score helps agents enough
to retain unchanged; preserve legacy values during migration regardless.

### Concurrent updates

Updates must support an expected version. The service checks the version and
commits the change plus revision atomically. A stale update returns a conflict
with enough information for the caller to reread and decide how to proceed.

Do not silently merge conflicting prose. Apply equivalent protection to
archive, restore, supersede, move, and other operations that change a record.

### Retry protection

Writes and imports need idempotency support. Repeating the same operation must
return its previous result without creating another memory. Reusing an
idempotency key with different content must produce a clear error. Define key
scope and retention in the API specification.

Idempotency prevents repeated operations; similarity checks assist with
different operations describing the same subject. Neither proves that two
facts are equivalent or contradictory.

## 5. Recall and search

### Automatic recall

Recall selects a bounded amount of relevant memory from the active space and
permitted General context. It is acceptable to return no memories.

- Apply authorisation before ranking and before producing result metadata.
- Scope pinned memories and reserve sensible budgets so pins cannot consume
  all useful context.
- Use optional subjects to improve relevance without requiring them.
- Preserve useful context while respecting the caller's size budget.
- Do not automatically inject all accessible spaces.

### Explicit search and broader discovery

Search allows narrower filters and explicit or configured broader discovery
across permitted spaces. Zero results is not the only reason to broaden: an
explicit reference to a home server may justify another search even when Work
contains matching words.

Search results must identify their owning space. Finding a record elsewhere
must not silently change the destination of later writes. An explicit update
to that record retains its ownership unless a separate authorised move occurs.

### Traceable responses

Recall and search should return record IDs, versions, ownership, relevant
source/freshness information, and concise content. Responses should describe
the effective context, the permitted spaces searched, and whether expansion
occurred. Avoid exposing inaccessible space names or record existence.

Distinguish no relevant matches from service failure. Provide useful diagnostic
information without flooding the agent's context with internal implementation
details. Token counts should be labelled estimates unless actually tokenised.

## 6. Common integration contract

Design one versioned HTTP contract around these capabilities:

| Capability | Purpose |
| --- | --- |
| Discover capabilities/context | Learn supported features, permitted destinations, and effective defaults |
| Recall | Obtain concise applicable context for a request |
| Search/get | Find and inspect records, including deliberate broader discovery |
| Prepare/write | Inspect similar records and persist durable knowledge |
| Update/maintain | Correct, archive, restore, supersede, or move records safely |
| Advanced Memory jobs | Discover availability, claim bounded jobs, read authorised sources, submit proposed changes, and inspect outcomes |

These are capability names, not final endpoint names. Use a clean `/api/v2`
contract. Decide whether a temporary v1 adapter is necessary after inventorying
the integrations; any adapter needs a defined support window and must not
bypass v2 permissions or write protections.

Glyph Hold owns permission enforcement, default resolution, retrieval policy,
version checks, and retry protection. Integrations supply available session
context, invoke the appropriate operations, and present the results faithfully.

Advanced Memory profiles and consolidated records use the same recall contract
for all clients. Include derived status, source references and freshness; a
stale profile must not conceal newer source facts. Hermes automatic prefetch
and Nexus explicit recall should both benefit without requiring another model
call to generate a profile on every read. Runner/job capabilities are separate
from ordinary client permissions and must be advertised honestly.

### Hermes native provider

The provider must benefit from v2 before the model chooses a tool:

- Bind clients, credentials, and defaults correctly per Hermes profile.
- Supply session identity and available context to automatic prefetch.
- Refresh context or support explicit changes when a workspace/conversation
  changes; do not assume startup working-directory information stays current.
- Preserve memory identity, version, space, and relevant provenance in recall.
- Make backend failures observable while allowing the host to choose graceful
  degradation.
- Keep background work and any cache isolated by principal, profile, session,
  and effective context.

Choose one authoritative shared-write path. Initial preference: Glyph Hold
tools own shared durable facts. If native Hermes memory mirroring is retained,
it needs stable source mappings, retry protection, and defined add/change/remove
semantics. Never interpret removal from a local scratchpad as global deletion
without an explicit policy.

The existing additions-only mirror defaults to `cat_temporary`, which is
excluded from automatic prefetch under v1 defaults. Resolve this deliberately.
The existing queued prefetch discards its result; remove it unless a useful,
isolated cache is implemented. The empty turn-sync hook does not require
transcript ingestion to be added.

Hermes local memory may remain for defined bootstrap or local purposes. Avoid
maintaining competing authoritative copies of shared facts.

### Nexus and other tool clients

Expose the same recall/search/write contract through the Nexus tool pack and
other supported tool integrations. Defaults should minimise repeated model
arguments while allowing explicit context choices.

Tool availability alone cannot guarantee recall before every response. Document
host capabilities honestly. Build native adapters for other agents when their
lifecycle offers a useful automatic integration point.

### Context switching limitation

Changing spaces prevents future out-of-scope retrieval; it cannot retract
information already injected into a model's conversation. Strong separation
requires a fresh conversation or host-supported context reset.

## 7. Keep, replace, remove, or evaluate

| Existing feature | Proposed v2 treatment |
| --- | --- |
| Categories | Keep classification; replace category-based access policy with explicit permissions |
| Tags | Keep flexible subjects; do not use as ownership or security boundaries |
| Category prefetch gate | Replace with explicit recall policy |
| Confidence 1–5 | Evaluate usefulness; keep distinct from freshness and preserve imported values |
| Prefetch levels/global pins | Simplify where useful; enforce space scope and budgets |
| Similarity/prepare-write | Keep duplicate assistance; accurately describe limits of conflict guidance |
| Revision history | Keep and add atomic version preconditions |
| Native additions-only mirroring | Replace with defined lifecycle or remove in favour of authoritative tools |
| Discarded queued prefetch | Remove unless justified caching is implemented |
| Silent integration failures | Replace with observable, distinguishable outcomes |
| API/client duplication | Consolidate shared contracts and conformance fixtures; choose packaging during design |

This is a review list, not authorisation to delete working features before
their replacement and migration consequences are specified.

## 8. Permissions and secrets

Space grants must apply consistently to lists, direct lookups, recall, search,
pins, revisions, similarity checks, moves, exports, and mutations. Client-supplied
agent names or context never override authenticated authority.

Secrets are global and independent of memory spaces. Separate API key secret
permissions and explicit reveal operations still apply. Recall must never reveal
secret values. Names must be unambiguous across providers; duplicate names require
an explicit ID and new writes must not create silent duplicates.

Secrets require a distinct transfer procedure: decrypt only through an
authorised migration path, encrypt with the destination key, and prevent values
from entering logs or ordinary memory exports. Reusing source ciphertext with
an unrelated destination key is not a valid migration.

### Automatic encryption-key setup and persistence

Agreed default: generate a cryptographically random, installation-specific
encryption key on first container startup and persist it outside SQLite in the
mounted data volume, for example `/data/encryption.key` alongside
`/data/glyphhold.sqlite`. Never generate or bake a shared key into the image.

Normal installation must not require users to generate or paste an encryption
key into Docker Compose. Reuse the persisted key across restarts, container
recreation, `docker compose down` followed by `up`, and image upgrades using the
same volume. Removing the volume removes the persisted data and key.

Create the key atomically with restrictive filesystem permissions and protect
against concurrent startup generating different keys. Load an existing key
without replacing it. If encrypted data exists and its required key is missing,
invalid, or incompatible, report an actionable error and block affected secret
operations; never silently generate a replacement or overwrite encrypted data.

Retain an explicit external-key option for advanced deployments. Define key
source precedence and validate it against existing encrypted data. A v1 upgrade
must retain or explicitly transfer its original key; automatic generation must
not make existing secrets unreadable. Changing key sources is not key rotation.

Backups and restore procedures must preserve both database and encryption key,
or the separately supplied external key. Explain that a key stored in the same
volume protects against a database-only leak, while access to the entire volume
allows decryption. Protect backups accordingly.

### Optional Bitwarden / Vaultwarden secret provider

Implementation status (18 October 2026): released in Glyph Hold 2.1.0 and
deployed on Pepper. Verified with the bundled Bitwarden CLI 2026.10.0 against
Vaultwarden 1.37.4 in disposable tests, and with direct discovery of 600 entries
in the user's existing vault. The integration remains optional and disabled
by default behind Settings.
The built-in encrypted secret provider remains the default. Disabling the
external integration does not mean disabling all secret functionality.

The target is the Password Manager vault containing the user's existing
credentials and folders. Bitwarden Secrets Manager is a separate product and
must not be assumed to provide access to these items.

Use a provider interface behind GH2's secret API. Hermes, Nexus, and other
clients continue to search metadata and explicitly reveal secrets through GH2.
Secrets are global, independent of memory ownership spaces. When Vaultwarden
is enabled, the selected provider is a live proxy over all accessible items,
including entries created outside Glyph Hold. No per-item registration, linking,
or SQL import is required. GH2 retains audit records and backward compatibility
for existing built-in secret IDs. External values remain in the external vault.

Recommended initial implementation route: an isolated official Bitwarden CLI
worker, using its local Vault Management API where suitable. This keeps vault
cryptography in the Bitwarden client. The worker must be private to GH2, with
isolated state and an authenticated/restricted boundary; do not publish an
unlocked CLI HTTP server as a general network service.

Authentication needs more than a server URL and personal API credentials.
The personal API key authenticates the CLI but does not replace the master
password for vault decryption.

Agreed setup: administrators enter the server URL, personal API credentials,
and master password through Settings. GH2 encrypts sensitive settings before
saving them in its database, using its installation encryption key. These
credentials must be recoverable for automatic use, so hashing is insufficient.
Do not require a separate master-password file.

When the integration is enabled, GH2 decrypts the saved configuration server-side,
signs in as needed, and unlocks the vault automatically after restart. Prefer
passing the password through a supported non-persistent input mechanism; avoid
plaintext temporary files and command-line password arguments. Keep the unlock
session in memory rather than treating it as a permanent API credential.
Bootstrap credentials cannot depend on the provider they unlock.

Settings show that credentials are configured and allow replacement or clearing;
never return the saved master password or API secret to the browser, agents,
logs, or ordinary configuration exports. Define explicit connection/unlock
states and errors for invalid credentials or unavailable providers. Automatic
access means the GH2 runtime holds the ability to unlock the connected vault.

Folders are optional organisation and do not map to memory spaces. Support
listing/creating folders, an optional default destination, and an optional
per-create folder ID. Omission uses the default or unfiled destination; an
explicit empty/null destination means unfiled. Search covers all accessible
folders and unfiled entries. Personal/work organisation is for memories only.

Metadata returns safe names, IDs, folder names and available field selectors,
never secret values or vault notes. A reveal returns one selected field, such
as a login username/password, SSH key, notes, card/identity or named custom field.
Use an explicit ID for duplicate names and a field selector for ambiguity.
Existing provider-bound legacy IDs continue to work. New external references
are bound to the configured account, preventing accidental reuse after a switch.

Built-in secrets remain accessible when Vaultwarden is selected. Normal new
writes use the active provider; provider outages fail explicitly and do not
create local duplicates. A built-in-only filter allows access during an outage.
External writes have a separate enable switch. Normal create rejects duplicate
names. Updates require current metadata versions and preserve unrelated fields.
Bitwarden's CLI cannot guarantee atomic conflict detection against simultaneous
edits by other clients; document that limitation rather than promise SQL-like
transactions across the provider. Direct external deletion remains in the vault
application; deleting a legacy reference does not delete its upstream item.

An explicit server-to-server migration tool checks existing vault items first.
If a selected target field has the same value, verify it and replace the local
handle with the verified reference. A different value requires review; do not
overwrite it. If no matching name exists, create then verify the destination
before changing the built-in record. Retain the original on errors. Never route
migration values through agent responses or plaintext export files. Toggling the
provider is not a migration. Preserve backups and older IDs.

Settings expose connection fields, enablement, write permissions and an optional
default folder. Save before testing; a saved connection can be tested while the
integration remains disabled. Official CLI cache/sync is an implementation detail,
not a requirement to copy items into GH2's database. Test authentication, direct
search, field retrieval, optional folders, duplicate handling, conflicts, outage
behaviour, account switching, restart recovery, UI and all three adapters.

Research references:

- [Bitwarden API overview](https://bitwarden.com/help/bitwarden-apis/): the
  organisation Public API differs from the CLI-backed Vault Management API.
- [Personal API authentication](https://bitwarden.com/help/personal-api-key/):
  login credentials do not substitute for vault unlock.
- [Password Manager CLI](https://bitwarden.com/help/cli/): self-hosted server
  configuration, folder/item operations, local API, and vault synchronisation.
- [Folders](https://bitwarden.com/help/folders/): personal organisation rather
  than shared permissions.
- [Vaultwarden project](https://github.com/dani-garcia/vaultwarden) and
  [folder implementation](https://github.com/dani-garcia/vaultwarden/blob/main/src/api/core/folders.rs):
  compatible client APIs and folder operations.
- [SSH items](https://bitwarden.com/help/about-ssh/): structured key material
  and the distinction between stored keys and the desktop signing agent.

## 9. Advanced Memory

### Agreed product behaviour

Provide one **Advanced Memory** on/off setting, disabled by default. This
supersedes the earlier Off / Basic / Agent-assisted proposal; there is no Basic
consolidation mode.

With Advanced Memory off, GH2 stores and retrieves memories normally. It runs
no scheduled semantic cleanup, profile generation, or consolidation and needs
no AI account or API credits. Ordinary database integrity, retry protection,
permissions, and user/agent-requested memory operations still apply.

Turning it on lets the administrator connect an AI runner, choose permitted
spaces and configure a schedule. Activation requires a working runner; show
disconnected or paused status explicitly. The AI performs semantic assessment:
which facts belong together, whether records are duplicates, and what a profile
should say. Deterministic code handles job preparation, scheduling, permissions,
validation and history. Similarity scores, matching names and age alone never
authorise a semantic merge, identity link, deletion or factual replacement.

The original product motivation remains a requirement: useful shared memory
without mandatory paid AI services. The owner's first runner should use Codex
through their existing ChatGPT subscription, without requiring OpenAI API
credits. Advanced Memory uses some of that subscription's allowance; it is not
unlimited or free inference. Other runners can implement the same contract.

### Capabilities

- Maintain source-backed profiles for people and other subjects, and summaries
  of procedures, preferences, services or topics. Projects remain optional.
- Combine semantically duplicate or overlapping records when evidence supports
  it, preserving distinct details, applicability and original source records.
- Mark outdated facts as superseded where evidence establishes a change;
  preserve historical facts and their time context.
- Identify contradictions and ambiguous identities, leaving unresolved facts
  separate and creating a review question when clarification is needed.
- Refresh only affected profiles and summaries as their source facts change.
- Assess whether records belong in Work, Personal, General or another permitted
  space, using content, provenance, session context and confirmed associations.

Profile building, duplicate merging, superseding and higher-order inference are
distinct operations internally. A useful profile does not require merging or
removing its source memories. Explicit facts and AI conclusions must remain
distinguishable. Inferences require evidence and uncertainty labels and must
not silently become verified facts. The initial emphasis is faithful synthesis
of known information, rather than speculative personality conclusions.

For example, facts about Jess can contribute to one profile once their subject
identity is supported. “My sister likes pasta” cannot be assigned to Jess from
similar wording or proximity. An uncertain relationship stays unresolved.

“Dreaming” in research references means background memory review. It does not
authorise invented events, unrelated tasks, server administration or autonomous
research. Consolidation operates on information GH2 actually holds; automatic
capture of otherwise unsaved conversations is a separate feature.

### Space classification and placement

Use the same space definitions and confirmed associations for two workflows:

- At write time, an active Hermes/Nexus/other agent can choose the destination
  using the current request and authorised GH2 context. Clear evidence supports
  automatic placement within its grants; the connection default is the fallback.
  This does not require a separate background model call for every write.
- During scheduled Advanced Memory review, the runner can identify potentially
  misplaced records and classify historical/imported memories. Existing-record
  moves initially remain proposals requiring authorised review, even when
  profile updates and consolidation are allowed to apply automatically.

Scheduled review cannot prevent an initial wrong placement because it runs
later. With Advanced Memory off, ordinary agent-selected destinations and the
existing context/default rules still work; no background classification runs.

Examples of confirmed guidance might associate Luxury Leisure operational
systems with Work, the owner's home network with Personal, and broadly
applicable communication preferences with General. These are contextual
associations, not unconditional keyword rules: a work procedure mentioning a
home PC does not automatically become Personal. User instructions and explicit
applicability take precedence over inferred associations.

Uncertain records stay in their current space, or remain in the restricted
import-review space after migration, with a clarification proposal. General is
never a catch-all for uncertainty. If a new write is clearly private but its
connection cannot write to the appropriate space, return an actionable placement
problem rather than silently use an unsuitable default.

When the user resolves a case, retain the confirmed association with provenance,
scope and revision history so later jobs and writing agents can reuse it.
Distinguish confirmed guidance from AI suggestions; allow correction and
revocation. Keep associations subject to normal access controls, and re-evaluate
affected pending proposals when guidance changes. Associations never grant
permission or establish that every mention of a person belongs in one space.

For every proposed move, record the memory ID/version, present and proposed
spaces, supporting sources, concise reason and unresolved uncertainty. GH2 must
check authority for both spaces at approval/commit time, retain one record
identity and its history, and invalidate affected profiles and caches. Define
how history and derived material are protected after an ownership change so
the move does not leak the previous space's other information. A classifier's
recommendation cannot broaden access by itself.

### Job prompt and supplied context

Each job uses a reusable, versioned maintenance prompt populated with bounded
job-specific context. The prompt must contain:

| Input | Purpose |
| --- | --- |
| Assigned tasks | State which profile updates, duplicate checks, superseding or space-classification reviews this job may perform |
| Space definitions | Describe applicable permitted spaces and confirmed placement associations without exposing inaccessible information |
| Evidence batch | Supply selected memories, IDs, versions, owning spaces, provenance, timestamps and relevant existing profiles |
| Decision rules | Preserve distinct facts, require supporting evidence, distinguish inference, and leave ambiguous identity/conflict/placement unresolved |
| Allowed operations | State job scope, execution policy and that existing-record moves are proposals under the initial policy |
| Output contract | Require structured proposed operations, target IDs/versions, source references, destinations where relevant, brief explanations and review questions |
| Job limits | Identify batch/context/runtime limits and how to request more authorised evidence or defer incomplete work |

The prompt guides semantic judgement. GH2 independently enforces grants,
versions, idempotency, operation policy and audit/reversibility; prompt compliance
is not a security boundary. Source memory content remains quoted evidence and
cannot override maintenance instructions. Store the prompt template version and
effective policy with run metadata so changes can be evaluated and results traced.
Keep source snapshots/logs subject to retention, deletion and access rules.

Populate each job with affected records and necessary supporting context rather
than sending the entire memory store every time. Permit additional authorised
lookups when needed, and return unresolved questions instead of guessing when
evidence or budget is insufficient. The result requires concise explanations
and evidence references, not private chain-of-thought.

### Settings and schedule

Expose the following behind Settings when Advanced Memory is enabled:

| Control | Behaviour |
| --- | --- |
| AI connection | Select/configure a supported runner and show connection/authentication status |
| Model and reasoning | Select an account-supported Codex model and supported reasoning effort, with account default/custom model options and clear subscription usage implications |
| Scope | Choose permitted spaces; each job still enforces the runner's grants |
| Placement guidance | Inspect/edit space definitions and confirmed associations; review proposed moves and unresolved classifications |
| Hourly | Minute-past-the-hour dropdown |
| Daily | Hour and minute dropdowns |
| Weekly | Day-of-week, hour and minute dropdowns |
| Timezone | Explicit selectable timezone, displayed alongside scheduled times |
| Next run | Show the next scheduled execution in that timezone |
| Run now | Queue a bounded run through the same job and permission checks |
| Execution controls | Batch/runtime limits, pause/cancel and automatic reversible changes or proposal-only operation |
| Run history | Last outcome, changes, source evidence, unresolved questions and available usage information |

Hourly, daily and weekly are the agreed initial frequencies. Monthly scheduling
was discussed earlier but is deferred from the initial controls. Daily is the
recommended starting cadence for this installation, enabled only by the owner.

Use named timezones so daylight-saving changes are handled deliberately. Define
and test skipped/repeated local-time behaviour: a daily/weekly occurrence runs
at most once, and a nonexistent local time moves to the next valid time. After
downtime, coalesce missed occurrences into one bounded catch-up job rather than
replaying every missed interval. Schedule edits recompute the next run.

Each occurrence first checks for relevant pending changes without a model call.
No changes means a recorded skip and no AI use. Corrections, removals and
permission/ownership changes can also require work. An explicitly requested
initial or full review is work even when no recent writes exist. Overlapping
scheduled/manual runs must not process the same batch concurrently.

Disabling Advanced Memory stops new dispatch and prevents in-flight proposals
from being applied after disablement. Existing profiles and history remain;
derived freshness continues to reflect source changes. Re-enabling resumes
pending work without duplicating previously committed operations.

### Runner and job architecture

GH2 owns the schedule, durable queue and commit rules. Agreed installation
default: bundle the official Codex CLI and worker in the same GH2 image and
Docker Compose service. The worker runs as a separate, restricted process on
the always-on GH2 server. No second container, desktop app or agent laptop is
required. Persist its private authentication state in the installation volume.
A separate worker remains a future advanced deployment option. Claims/leases
ensure one active owner per job even if execution is later distributed.

Settings must let users select a supported model and reasoning effort, where
available. Obtain supported choices from the signed-in Codex catalog without
running a paid/inference turn; permit account defaults and explicit model IDs
with validation on execution. Do not assume an account's default is cheapest or
silently upgrade a selected model. Explain that larger/deeper runs consume more
subscription allowance without inventing model prices or remaining quota.

Recommended first adapter: the official Codex CLI using ChatGPT sign-in and
non-interactive `codex exec`, with structured output for proposed operations.
Persist its supported authentication state across worker restarts and let Codex
handle token refresh. Use the official login flow; GH2 should not collect the
ChatGPT password or turn subscription credentials into a general API proxy.
Keep runner authentication separate from ordinary memory and secret recall.

The documented subscription authentication path is a research-backed design
choice, not a tested GH2 integration. Prove it with a bounded end-to-end
prototype against supported Codex versions and the owner's account before
committing to packaging. Account limits, session expiry and runner availability
must produce explicit queued/paused/failed outcomes. Never fall back silently
to a paid API or repeatedly retry a quota failure.

Job flow:

1. Track source changes and select a bounded set of affected subjects/records.
2. Claim a job with a lease and supply the current profile, relevant evidence,
   source versions, effective space, confirmed placement guidance, allowed
   operations and size limits through the versioned maintenance prompt.
3. Let the AI inspect additional authorised evidence when necessary. Candidate
   preparation is a starting point, not proof or a restriction to exact words.
4. Receive structured proposed operations with source references and a concise
   justification. Require evidence, not disclosure of private chain-of-thought.
5. Validate ownership, permissions, operation types, source/output versions,
   provenance and retry identity. Schema validation cannot establish factual
   truth; uncertain semantic decisions remain unresolved or await review.
6. Apply permitted changes atomically with revisions, or stage proposals under
   the selected policy. Requeue stale proposals for reassessment.
7. Record progress and outcome so interruption/retry resumes safely. Keep
   completed batches committed and remaining work pending.

The runner gets only the maintenance capabilities and data scope it needs.
Memory text is evidence, never an instruction to execute tools or change the
job policy. Exclude secret values and secret-provider access. Bound source size,
runtime, batches, retries and concurrency; record model usage where available
without claiming precise remaining subscription allowance if unavailable.

The runner contract should also permit a future Hermes worker or another chosen
agent. Ordinary Hermes and Nexus clients read the same improved records; they
must not each start an independent consolidation schedule.

### Evidence, reversibility and isolation

- Store source record IDs and versions for generated statements/profiles, the
  producing job/runner, and previous output revisions.
- Keep originals recoverable when merging. Define canonical references so old
  IDs remain traceable; normal recall can hide merged duplicates while history
  inspection can include them.
- Keep superseded facts available as labelled history. Age or a newer timestamp
  alone does not prove a fact is wrong. Consolidation is not verification.
- Prevent recalled context, profiles and generated summaries from becoming new
  independent evidence. Track original lineage through derived records.
- Invalidate affected outputs when sources are corrected, deleted, moved or
  become inaccessible. Do not allow summaries to resurrect forgotten facts;
  define deletion propagation across derived content, caches and job artifacts.
- Keep derived records within an ownership/access boundary no broader than their
  evidence. Start with per-space profiles; do not publish Personal/Work facts
  into General. Cross-space retrieval remains subject to normal grants.
- Require version preconditions on all affected sources and targets, including
  merge/supersede operations, so concurrent agent writes cannot be lost.
- Record a reviewable change set and support reversal. Undo must check current
  versions and handle later dependent changes rather than overwrite them.
- Ask about ambiguous identities or conflicts through a pending-review queue;
  do not guess or repeatedly raise the same unanswered question every run.

### Research adapted to GH2

| Reference | Adaptation |
| --- | --- |
| Hindsight mental models | Source-backed persistent profiles, freshness signals and incremental refresh of affected subjects |
| Mem0 Dream | Separate merge, supersede and synthesis operations, recoverable originals and traceable results |
| Honcho | Stable subject identities, evolving representations and separation of recorded facts from conclusions |
| Hermes Dreaming community plugin | Cheap change/work detection before waking an AI; semantic decisions stay with the agent |
| Letta dreaming | Background consolidation; an extra model review pass may be offered later with its additional usage made clear |
| Supermemory Hermes integration | Prevent recalled/generated context from feeding back as fresh independent evidence |

These are design precedents, not dependencies or claims of feature parity.
Do not copy provider-specific paid tiers, minimum-memory thresholds or historical
processing restrictions. A second AI review pass is optional and deferred until
evaluation shows its value; it is not required for each GH2 update.

## 10. Migration and consolidation

Support both upgrading one installation and importing another v1 installation
into it. The intended user sequence is to upgrade the personal installation,
then transfer work memories into the consolidated service.

### Required migration behaviour

1. Inventory supported source schema versions and export capabilities.
2. Create a consistent backup and a dry-run report before modifying source
   data or performing an in-place database upgrade.
3. Preserve content, source identity, original timestamps, categories, tags,
   metadata, revisions, and archived/superseded relationships where present.
4. Map IDs deterministically within a source namespace and remap relationships
   so collisions between installations do not corrupt references.
5. Preserve original fields in provenance where v2 semantics differ. Do not
   fabricate ownership, verification dates, or confidence.
6. Make imports resumable and repeatable without duplication. Report failures
   and collisions rather than silently dropping or merging records.
7. Reconcile counts, relationships, representative content, and searchability
   before declaring success.
8. Keep source installations/backups intact until validation and cutover are
   complete. Document that rollback after new v2 writes needs reconciliation.

Use explicit source-to-space mapping when the owner is known. Otherwise place
records in a restricted import-review space and mark their classification as
unresolved. Unclassified is not General. Agents can propose batch moves and
ask about ambiguous groups after faithful import succeeds.

Classification, semantic merging, and deletion are separate reviewable steps.
Moving a record preserves its identity and history and must recheck access to
both source and destination. Do not copy facts into several spaces merely to
make them discoverable.

Advanced Memory is not required for migration. First import faithfully and
validate the result; then allow a separately enabled, previewable initial review
of existing/imported memories, including older records. Process it in bounded,
resumable batches using the same evidence, permissions and revision rules as
scheduled maintenance. Unknown ownership remains restricted until resolved.
Keep classification/moves separate from semantic merging; enabling Advanced
Memory does not automatically grant permission to move facts between spaces.

## 11. Evaluation and release gates

Create representative fixtures before changing retrieval. Compare v1,
tags-only filtering, and the proposed design using the same questions and
context budgets. Do not claim improved recall solely because new fields exist.

Measure useful recall, irrelevant context, wrong-space injection, write
destination accuracy, clarification frequency, freshness handling, latency,
and context size. Choose numerical performance targets after establishing the
baseline; correctness gates below are mandatory.

Required scenarios:

- Ordinary questions and research work without a project.
- Work and Personal server names overlap; ambiguous requests are handled.
- Work on a home machine and home-server requests on a work machine.
- General preferences and space-specific exceptions remain distinguishable.
- Unknown or stale operational facts are not presented as newly verified.
- Pins and broad searches never bypass space grants.
- Equivalent Hermes and Nexus requests resolve equivalent permitted context.
- Two agents updating one version produce a conflict, not a lost update.
- Retried writes and repeated imports do not duplicate records.
- Concurrent Hermes profiles do not share the wrong client, context, or cache.
- Workspace changes and missing context behave predictably.
- Empty results, denied access, and service failure remain distinguishable
  without leaking inaccessible record existence.
- Migration preserves records, revisions, relationships, and provenance.
- Secret values never enter recall, ordinary exports, or logs.
- Fresh installations generate one unique key; restarts, container recreation,
  and image upgrades preserve access using the same mounted volume.
- Missing or incompatible keys never trigger replacement over existing encrypted
  data; v1 key transfer and full backup/restore preserve decryptability.
- Saved Vaultwarden settings contain encrypted sensitive fields, never return
  saved credentials to clients, and support automatic unlock after restart
  without a separate master-password file.
- The same GH2 secret operations work through the built-in and external providers
  without provider-specific credentials or arguments in Hermes/Nexus clients.
- Bitwarden and Vaultwarden compatibility is tested against declared supported
  versions, including folder selection/creation, direct item field selection, secret
  creation/reveal/update, and explicitly defined unlink/trash behaviour.
- External folder renames preserve optional destinations by ID; moves, deletions, duplicate
  names, and edits in another Bitwarden client produce predictable results.
- Disabling or losing access to the external provider never silently redirects
  an existing secret binding to a different value or creates a local duplicate.
- With Advanced Memory off, core use requires no runner or AI credentials and
  produces no scheduled consolidation calls or semantic mutations.
- Subscription-authenticated Codex completes a bounded maintenance job without
  an API key; auth/quota failures pause or queue work without paid fallback.
- Hourly/daily/weekly dropdowns, timezone, next-run display and Run now agree
  with actual execution, including daylight-saving transitions and downtime.
- Unchanged scopes skip AI execution; changes affect only relevant jobs, and
  explicit initial review includes historical/imported memories.
- Overlapping jobs, expired leases, retries and worker restarts do not apply the
  same operation twice; disabling prevents later commits from in-flight work.
- Ambiguous names and relationships remain unresolved without evidence; lexical
  similarity alone never merges records or assigns subject identity.
- Profiles preserve distinct facts, source references and uncertainty. Newer
  conflicting statements and old valid facts are handled without blind replacement.
- Merges/supersedes retain inspectable history, and undo respects later edits.
- Source corrections, deletions, moves and grant changes invalidate or restrict
  derived outputs; recalled summaries do not become independent corroboration.
- Malicious instructions in source memories cannot extend the runner's scope,
  reveal secrets or trigger unrelated actions.
- Concurrent source/target edits reject stale proposals instead of losing data.
- Hermes prefetch and Nexus recall expose equivalent maintained knowledge with
  provenance and freshness, without per-read profile generation.
- Write-time and scheduled classification reuse confirmed guidance; explicit
  user context overrides device defaults without bypassing grants.
- Ambiguous/private records never fall into General merely through uncertainty;
  no access to a destination produces an actionable result rather than a leak.
- Existing-record moves remain review proposals under the initial policy, with
  both-space authorisation, current versions, history and derived-data handling.
- Correcting or revoking a confirmed association affects subsequent decisions
  and pending proposals without silently moving existing records.
- Job prompts contain the bounded evidence, placement guidance and output
  contract; source instructions cannot override service-enforced job policy.

Evaluate Advanced Memory separately from retrieval: compare answers before and
after consolidation, factual preservation, unsupported claims, incorrect merges,
identity mistakes, profile freshness, review burden and AI usage per useful
change. Include a fully offline/no-runner core configuration. Establish semantic
quality thresholds on representative fixtures before allowing automatic changes;
structural validity and a successful AI response alone are insufficient.

## 12. Delivery stages

### Stage A — Baseline and detailed design

Inventory current integrations and source versions. Capture evaluation
fixtures. Specify schema, context precedence, permission semantics, freshness,
write conflicts, idempotency, and API responses. Resolve keep/remove decisions
and secret naming. Specify the common secret-provider contract and prototype
Bitwarden/Vaultwarden authentication, unlock, folder operations, and item-field
access against supported versions. Produce a migration mapping and compatibility
policy.

Specify Advanced Memory subject identity, evidence lineage, lifecycle operations,
job permissions, schedule semantics, space-classification guidance, versioned
prompt/output contract and review policy. Prototype a complete
subscription-authenticated Codex job on sample memories: prepare a batch,
receive structured proposals, validate/apply a revision, and recover from a
failed or stale run. Verify the no-API-credit path before building full runner
packaging and scheduling UI.

Exit: a reviewable design and executable baseline evaluation, with no silent
assumptions about Hermes lifecycle or existing data.

### Stage B — Core v2 foundation

Implement spaces/grants, record versions, atomic revisions, idempotent writes,
provenance, and migration primitives. Implement persistent installation-key
generation, external-key compatibility, and encrypted integration settings.
Apply access checks to every data path.

Add optional subject identities, derived-record lineage, invalidation and
reversible lifecycle primitives needed by Advanced Memory. Implement durable
job state, leases and idempotent commits without introducing an AI dependency
into ordinary storage/retrieval.

Exit: ownership, concurrency, retry, and migration correctness tests pass.

### Stage C — Recall and maintenance contract

Implement context resolution, scoped recall/pins, deliberate broader search,
traceable responses, freshness handling, and accurate duplicate guidance.
Build minimal dashboard support for spaces, permissions, and record review.
Add Settings controls for optional integrations, with Bitwarden/Vaultwarden
disabled by default and encrypted credential configuration.

Add the default-off Advanced Memory setting, connected-runner status, permitted
scope, hourly/daily/weekly dropdowns, timezone, next run, Run now, execution
limits, run history and pending-review views. Implement deterministic change
tracking and source freshness; semantic actions require the connected AI.
Include editable space descriptions, confirmed associations and proposed-move
review, with common guidance available to both writing agents and the runner.

Exit: retrieval comparisons show the intended behaviour within agreed budgets.

### Stage D — Integration upgrades

Upgrade the generic client, Hermes provider, and Nexus tool pack against common
contract fixtures. Validate automatic recall and explicit tools end to end.
Document local/native memory ownership and supported host capabilities.

Implement the Bitwarden/Vaultwarden secret provider behind GH2's common secret
API, including automatic authentication/unlock, optional folder selection and creation,
direct access to existing items, supported value/field types, and controlled
mutations. Validate provider state, external edits, restart recovery, and
failure behaviour. Confirm Hermes and Nexus can use both providers through the
same GH2 operations.

Implement the Codex companion runner and GH2-owned scheduling/queue workflow.
Validate subscription login persistence, bounded source loading, structured
proposals, automatic reversible/proposal-only operation, usage reporting,
auth/quota failures and restart recovery. Extend Hermes and Nexus recall to
surface derived knowledge, source identity and freshness consistently. Keep the
job interface reusable for future runners.
Validate write-time placement guidance and scheduled classification with the
same space definitions, plus review and commit of authorised move proposals.

Exit: the same memory can be created, recalled, corrected, and reread across
integrations with consistent permissions and versions. The optional external
secret provider passes its compatibility and provider-conformance checks.
Advanced Memory passes its semantic and operational gates while the core remains
fully usable with the feature off and no AI credentials.

### Stage E — Migration rehearsal and release

Rehearse upgrade and multi-source import on copies. Validate classification,
relationships, secret transfer (including optional built-in-to-external
provider migration), backups, and recovery. Publish operator and
integration upgrade guides, then perform a deliberate cutover.

Rehearse the optional initial Advanced Memory review on imported data after
faithful migration. Validate preservation of evidence, scope, reversibility and
resumable progress. Document runner setup, expected subscription usage, scheduling,
failure recovery and how to disable the feature without losing history.

Exit: existing knowledge is accounted for, integrations work with the new
service, and release/rollback limitations are documented.

## 13. Remaining design decisions

- Final naming of spaces and default onboarding configuration.
- Exact optional subject representation and association persistence.
- Simplification of confidence and recall priority controls.
- Verification/review policy for different memory types.
- Native Hermes mirroring versus explicit shared-write ownership.
- Secret name uniqueness and space selection semantics.
- Need and support window for a v1 compatibility adapter.
- Detailed import format, audit retention/export scope, and recovery procedure.
- Exact subject/alias and per-statement provenance schema for Advanced Memory.
- Runner packaging and supported Codex versions after the subscription prototype.
- Initial automatic-change policy, semantic quality thresholds, and numeric
  execution limits; whether an optional second AI review pass is justified.
- Detailed canonical-reference, undo, deletion-propagation and job-artifact
  retention semantics.
- Placement-association schema, prompt template versioning and review-question
  delivery; access to historical revisions after authorised space moves.

Resolve these through the detailed design and evaluation. They do not change
the agreed objective or justify requiring projects for all memory.

## 14. Reference material

- [Glyph Hold v1 plan](PLAN.md), [contribution boundaries](CONTRIBUTING.md),
  and [backup guidance](BACKUP_AND_RESTORE.md).
- Sibling repository `glyphhold-hermes-memory`: provider implementation,
  README, and tests reviewed for this plan.
- [Hermes memory-provider contract](https://hermes-agent.nousresearch.com/docs/developer-guide/memory-provider-plugin/):
  lifecycle hooks, initialization context, and profile isolation.
- [Hermes persistent memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory/):
  native memory and external-provider coexistence.
- [LangChain memory concepts](https://docs.langchain.com/oss/python/concepts/memory):
  separate conversation state, durable memory, and write/retrieval concerns.
- [Letta stateful-agent concepts](https://docs.letta.com/v1-sdk/concepts/stateful-agents):
  selectively supplied and shared context as a comparative design reference.
- [Hindsight mental models](https://hindsight.vectorize.io/developer/mental-models):
  maintained summaries, scoped refresh, provenance and revision history.
- [Mem0 Dream](https://docs.mem0.ai/platform/features/dream): separate synthesis,
  supersede and merge actions; this reference describes platform functionality,
  not a guarantee that the same feature exists in the self-hosted OSS edition.
- [Hermes provider comparison](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers):
  Honcho representations and cadence controls, Supermemory context fencing,
  and provider lifecycle differences.
- [Honcho memory tools](https://github.com/plastic-labs/honcho/blob/main/mcp/instructions.md):
  peer identity, representations, source-linked conclusions and dream operations.
- [Hermes Dreaming](https://hermes-agent.nousresearch.com/docs/plugins/hermes-dreaming):
  community plugin using deterministic preparation before agent review; not a
  built-in GH2 dependency or a claim of model-free semantic consolidation.
- [Letta memory and dreaming](https://docs.letta.com/configuration/memory):
  background agents and optional additional model review.
- [Codex authentication](https://learn.chatgpt.com/docs/auth) and
  [non-interactive execution](https://learn.chatgpt.com/docs/non-interactive-mode):
  ChatGPT subscription sign-in, saved authentication, structured outputs and
  account-authenticated automation. Confirm supported behaviour during prototype.

External designs are useful precedents, not evidence that this proposal already
outperforms Glyph Hold v1. Verify host contracts against the supported versions
when implementing each integration.
