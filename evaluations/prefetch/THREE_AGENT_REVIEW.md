# Three-agent prefetch evaluation — 19 October 2026

Three agents independently authored 15 additional questions each against the same
22 synthetic memories. All **45 messages are unique** and none exactly repeats the
initial baseline questions. Each set was evaluated across the same five configurations:
**225 query/configuration combinations**, plus 45 verification calls through the real
Hermes prefetch wrapper with only its HTTP transport substituted. No runtime algorithms, live settings, memories,
secrets or deployments were changed.

## Default results

| Independently authored style | Required records found | Questions with unrelated context | Questions missing a required record | Strict passes |
| --- | ---: | ---: | ---: | ---: |
| Direct/technical | 13/13 (100%) | 14/15 | 0/15 | 1/15 |
| Everyday conversational | 8/12 (67%) | 15/15 | 4/15 | 0/15 |
| Varied, typos, multiple intents and follow-up | 15/16 (94%) | 13/15 | 1/15 | 2/15 |

Required-record counts can exceed question counts when several facts are requested.
Each set has 12 topical questions plus three questions that need no topical memory.
Across defaults, **42 of 45 questions receive unrelated records**. All **nine**
no-topical-memory requests receive unrelated context, including simple calculations.
These are small synthetic stress sets; these proportions are not estimates of live
failure rates or final-answer accuracy. Questions and optional-label policies differ
between authors, so the table is descriptive, not a controlled ranking of styles.

## Comparable intents, different wording

- **People:** the terse request “Jess: relationship status and excluded ingredient.”
  retrieves both needed records. The conversational request “I want to take Jess out
  for a meal this weekend. What sort of place would suit her, and is there anything
  to steer clear of?” returns a garden checklist and a storage runbook, missing her
  food preferences despite explicitly naming Jess.
- **Password lookup:** “When looking up a saved login, should I search its domain
  name?” retrieves the Vaultwarden record, with noise. “I cannot find a saved login.
  Where do I usually keep passwords, and what should I try searching for?” misses
  that record and returns planning, delivery, person and backup records instead.
- **SSH/restart procedure:** the direct technical request retrieves SSH keys and
  the permission rule. The conversational restart-permission request misses that
  record. The varied request with “Peper” also misses SSH while finding the backup
  record; that is not proof the typo alone caused the miss, since the rest differs.
- **General questions:** “Convert 4096 bytes to KiB.” receives SSH, DNS and backup
  records. “Why do rainbows have different colours?” receives backup instructions.
  These are unrelated injections regardless of leniency about optional background.

Each author subsequently inspected the visible context and wrote a review:
[direct](agent_direct_review.md), [conversational](agent_conversational_review.md),
[varied](agent_varied_review.md). Labels and results were not revised after inspection.

## Important false assurance: record found, answer missing

The varied set asks for the critical command from the storage recovery runbook.
Defaults return the right record ID but truncate away `RESTORE-VERIFY-OMEGA`.
The original author did not specify an evidence substring, so the automated score
counts that case as a strict pass. Post-run review records it as an evidence failure
without changing the original score. The larger budget makes the command visible.

Consequently, the varied set's two automated strict passes include one case that
does **not** actually supply the requested answer under defaults. Future suites need
answer-bearing evidence labels for all topical cases, not merely record IDs.

## Configuration comparisons

Removing unmatched pin injection alone makes little difference:

| Style | Unrelated cases, defaults | Unrelated cases, pins changed to normal |
| --- | ---: | ---: |
| Direct | 14/15 | 14/15 |
| Conversational | 15/15 | 14/15 |
| Varied | 13/15 | 13/15 |

This makes it clearer that common-word matching and ranking are substantial issues
independently of the semantics of “pinned”. A pinned record matching ordinary query
words can still appear even when the pin designation is removed.

Returning ten records with a larger budget raises conversational required-record
recall from 8/12 to 11/12, but lowers precision from 18% to 12.4%. The dining and
password examples recover their records only after many distractions. More results
therefore masks weak ranking rather than providing clean context. Explicitly
broadening all granted spaces worsens the varied set's missed-record count from
one to three through competition; automatic indiscriminate broadening is not a fix.

## What this changes in the recommendation

The second round supports concentrating on **relevance and ordering first**, with
evidence preservation as a separate requirement. It does not establish that an LLM
must run on each prefetch, or that local embeddings alone would fix the problem.

The next isolated comparison should include:

1. A stronger lexical baseline with exact identifiers and entities, less influence
   from conversational filler, and a deliberate no-topical-memory outcome.
2. Answer-bearing passages/evidence checks, so a correct ID with missing facts is
   not counted as retrieval success.
3. A semantic/hybrid candidate for paraphrases, measured against the same queries.
4. Paired rewrites of identical intents with consistent optional labels, plus an
   unseen holdout and eventually approved real failure examples.

Some label decisions are debatable: contextual neighbours or General response
preferences could reasonably be allowed more broadly. Those decisions affect
strict precision but do not explain the missing dining/password/restart facts or
the nine unrelated-question injections. Follow-up context is metadata only; the
current adapter does not consume the prior message. One synthetic follow-up happens
to retrieve its target and must not be treated as proof of reference resolution.

## Reproducibility and limitations

- [Author case sets and outputs](agents-summary.json) are linked by filename.
- [Label manifest](agents-label-lock.json) records SHA-256 hashes **before** retrieval.
  All three hashes were verified unchanged after evaluation.
- Direct and conversational agents accidentally saw the earlier baseline questions
  while reading the corpus, but saw no prior retrieval outputs. The varied agent
  read only the memory array. This is independently authored, **not fully blind**
  testing. Source files/reviews preserve these disclosures.
- The same small corpus is reused. There is no human-reviewed live memory snapshot,
  generated-answer evaluation, production latency test, or representative traffic
  sample. No algorithm was tuned against these examples.
- All 45 default adapter-wrapper checks match the evaluated core record IDs.

Re-run from the repository root:

```bash
python scripts/evaluate_prefetch_agents.py \
  --hermes-adapter ../glyphhold-hermes-memory/__init__.py
```

The runner checks labels and writes new result files; it creates/deletes only its
own temporary databases. Like the initial runner, completing an evaluation is not
a claim that its quality expectations passed.
