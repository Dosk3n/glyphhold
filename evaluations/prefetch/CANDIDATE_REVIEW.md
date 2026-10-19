# Recall candidate — implementation and results, 19 October 2026

**Historical retrieval-only decision.** The later
[workflow release review](WORKFLOW_RELEASE_REVIEW.md) adds actual agent answers,
documents the owner's clarification about explicit-search recovery, and supersedes
the deployment decision below. The coverage figures and experiment limits below
are retained unchanged.

The first three changes are implemented and tested locally: lexical ranking and
exclusions, fair context packing, and topical abstention. They dramatically reduce
unrelated injections, but **the lexical candidate loses some paraphrase coverage**.
The agreed coverage gate is therefore **not fully met**. Pepper remains on its
existing release; no GitHub push, release or image publication was performed.

## Implementation

- `app/v2/retrieval.py` handles automatic `/api/v2/recall`; explicit `/search`
  behaviour and tool signatures are unchanged.
- Conversational filler is removed before deduplicating/capping query terms. Literal
  whole-word FTS queries include conservative inflections and adjacent phrases.
  Application phrases such as Home Assistant retain their meaningful scope words.
- BM25 leads, with bounded entity/subject and priority boosts. Exact identifiers
  reject shared IP octets and hostname prefixes; IPv6 is compared canonically.
- Confirmed subject aliases contribute candidates as well as relevance. Category
  exclusion, `never`, lifecycle flags and grants are applied before candidate output.
- Multiword requests need coherent passage evidence or an explicit anchor, followed
  by a relative relevance cutoff. This is a heuristic, not calibrated probability.
- Exact duplicate title/body/subject/type records compete after priority scoring;
  they are not merged, rewritten or deleted. Different titles/entities remain distinct.
- General pins supply bounded background context. Task pins still require relevance.
  Global pins cannot displace the sole topical record in a small result budget.
- Selected records receive shares of the available budget before packing. Long
  bodies copy matching passages plus ending context, labelled `excerpted` and
  `truncated`. Full records remain accessible by ID. Serialized result characters,
  including identity/provenance metadata, remain bounded.
- The dashboard explains pin semantics. Hermes's system prompt and Hermes/MCP/Nexus
  prefetch descriptions explain selective recall and full-record lookup. These are
  local adapter changes only, not deployed releases. No tool parameters changed.

The runtime path has no new package/model dependency, external inference call,
configuration secret, schema migration or implicit cross-space expansion.

## Frozen comparisons

The evaluator reloaded the original core from the recorded Git commit, so baseline
and candidate ran against the same temporary corpora and labels in the same environment.
Original outputs/label files were retained. Each set ran in five configurations;
the table below uses the normal Hermes request: five results, 2,400 characters.

| Set | Cases | Baseline unrelated cases | Candidate unrelated cases | Baseline required records found | Candidate required records found |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original development questions | 31 | 30 | 7 | 21/25 | 17/25 |
| Direct-agent questions | 15 | 14 | 2 | 13/13 | 11/13 |
| Conversational-agent questions | 15 | 15 | 2 | 8/12 | 9/12 |
| Varied-agent questions | 15 | 13 | 1 | 15/16 | 12/16 |
| First locked set, now regression | 20 | 19 | 2 | 12/14 | 14/14 |
| Fresh confirmation questions | 12 | 12 | 1 | 5/8 | 5/8 |
| **Combined** | **108** | **103** | **15** | **74/88** | **68/88** |

All **25** cases requiring no topical memories were clean under the candidate,
versus none under the baseline. Exact strict passes rose from 3 to 76 of 108.
Removing pin injection alone is not the explanation: with pins changed to normal,
the baseline still has 93 noisy cases versus the candidate's 15.

Record-ID coverage is not answer accuracy. The confirmation and first locked sets
also label visible evidence. The first locked set's missing-evidence count falls
from three cases to zero. The confirmation set still has three missing-evidence
cases, all absent records requiring indirect/semantic associations.

The initial candidate scored 19/20 strict passes on the first locked set before
real replay. Real replay then exposed application-phrase and split-prefix failures.
After those corrections the same set is a **regression set**, with 18/20 strict
passes; it is not presented as an unseen final test. Twelve confirmation labels
were frozen before the corrections and final scoring. Parameters were not adjusted
after seeing their results. Earlier independent authors' optional-label policies
differ; none of these sets is representative traffic or independently human-adjudicated.

## Real Pepper replay

A fresh read-only snapshot contained 80 memories. The original implementation
reproduced **all nine recorded ordered result lists**, confirming the replay context.
The final candidate removed Framekeep from all selected example outputs. It also
returns no memories for both recorded prefetch-feature questions and the ambiguous
entity-workaround follow-up instead of the previous unrelated injections.

The curated related-context checks remain **4/6 found**, for both baseline and
candidate, with a changed composition: the lighting-schedule record is recovered
but another previously supplied integration record can fall outside the selected
results. These are related-context labels, not exhaustive final-answer gold labels.
Some real outputs still include loosely related records; this is **not** a claim
that every real failure is solved.

Only anonymized replay counts are retained in
[candidate-real-replay.json](candidate-real-replay.json). Raw snapshot and title/query
traces were kept outside the repository and deleted after inspection. No secret
tables, accounts or API-key tables were copied. Production services/configuration
were not changed or restarted.

## Optional local semantic comparison

A separate experiment used Qdrant FastEmbed with `BAAI/bge-small-en-v1.5`, local
CPU inference, minimum similarity 0.62 and minimum top-two margin 0.025. It only
attempts a fallback when lexical recall is empty. No API credits or subscription
allowance were used; only public model weights were downloaded.

On the 76 development questions it recovers required coverage to **57/66**, matching
the original baseline while reducing noisy cases from 72 to 12. On confirmation it
finds **7/8** required records versus lexical's 5/8, but increases noisy cases from
one to two. Its similarities and margins are not reliable confidence probabilities.
The experimental selection code is synthetic-only and is **not** a runtime provider.

This supports testing hybrid retrieval next, but not enabling this particular small
model automatically. No model service, cache of private embeddings or optional
model download path was added to the production application. Method references:
[FastEmbed retrieval](https://qdrant.github.io/fastembed/qdrant/Retrieval_with_FastEmbed/),
[supported models](https://qdrant.github.io/fastembed/examples/Supported_Models/).

## Runtime verification

- **184 backend tests passed**, including new relevance, identifier, phrase, priority,
  category, alias, provenance-budget and permission tests.
- Hermes **18**, MCP **17**, and Nexus **17** local adapter tests passed after the
  guidance changes: **236 total passing tests** including the backend suite. The
  Hermes suite included its optional contract test using Pepper's installed official
  `agent/memory_provider.py`; no tests remained skipped in the final adapter runs.
- The standard Dockerfile built the final image, including the dashboard's type/build
  checks, on Python 3.12.15. Image: `glyphhold-prefetch-candidate:local`.
- A separate read-only-root container used temporary `/data` and `/tmp`, no external
  network or published ports, and no production mounts. Authenticated HTTP checks
  passed for recall, topical abstention, global preference handling, exclusions,
  identifier-safe queries, excerpts, full-record lookup and restricted grants.
- Five authenticated synthetic HTTP calls in that single-CPU container took about
  **10.6–10.9 ms**. This is local test latency, not Pepper production latency or an
  end-to-end agent measurement. No inference model ran in that container.
- The image's retrieval-source hash matches the frozen candidate. The disposable
  container and its ephemeral credentials/data were removed after validation; the
  test image remains available locally.
- Final Pepper checks still report version **2.1.3**, database OK, **80 memories**,
  an active Hermes gateway and the original retrieval-core fingerprint. Nothing
  was installed or restarted there.

## Rollout decision and remaining work

The agreed precision/abstention/evidence/boundary goals improve substantially.
**Preserving overall required-record coverage does not pass for the lexical path**
(68/88 versus 74/88). The candidate is concrete and reviewable, but it should not
be silently deployed as an unqualified accuracy improvement.

The next improvement comparison should concentrate on semantic/hybrid selection,
confirmed entity associations, and bounded conversational query context. The client
guidance now encourages explicit search when automatic recall is insufficient.
Automatic scope fallback, inferred pronoun resolution and historical-context
replacement are not implemented by this phase. No final-answer/model behaviour
evaluation or claim of perfect current-fact resolution has been made.

## Reproduce

```bash
python scripts/compare_prefetch_candidate.py
python -m pytest -q
# Optional, separate evaluation dependency:
python scripts/compare_prefetch_semantic.py --include-agent-cases
```

[candidate-lock.json](candidate-lock.json) pins source and fixture hashes;
[candidate-comparison.json](candidate-comparison.json) holds per-set summaries;
[candidate-aggregate.json](candidate-aggregate.json) holds combined default counts.
Initial-candidate lock/summary/holdout files are retained separately. New fixture
files deliberately contain fictional examples and must never be imported as real
memories. Real replay requires a new private snapshot after cleanup.
