# Prefetch diagnosis — 19 October 2026

**The failures are reproducible in the current retrieval pipeline. They are not
explained by an outdated Hermes adapter or a stale search result.** Ranking and
greedy context packing compound each other; query preparation and context handling
are separate contributors. No fix has been implemented or deployed.

## Evidence collected

- **90 synthetic diagnostic probes**, covering wording, individual word removal,
  identifiers, sequences, scope, distractors, budget, corpus growth, freshness and identity.
- **Nine recorded Pepper examples**, replayed against an isolated memory-only snapshot.
  **All nine returned exactly the same ordered memory IDs as Hermes's saved injected
  context**, including both useful recalls and reported irrelevant recalls.
- **Seven additional native-adapter sequence calls**, with HTTP replaced by the local
  core. Repeated identical questions returned identical memories after topic changes.
- Isolated execution of **three installed Hermes helper functions**, with manager,
  text-flattening and trivial-prompt dependencies stubbed. This checks query forwarding
  and sidecar substitution, not a model or full gateway conversation.
- **30 verification tests passed** across the diagnostic/evaluation harnesses, v2 core
  and integration contract; lint checks passed.

The deployed retrieval source and adapter SHA-256 hashes matched their local copies.
Installed Hermes revision: `0e427d788d253630d38a3a51cd76849e73cd6925`.
Pepper's snapshot held 80 memory records, 79 active; one active record was pinned and
two active bodies exceeded the 2,400-character default budget. This is not a corpus
in which most records are long, or most records pinned.

Private capture used read-only SQLite connections. Only memory/category rows and
selected recorded user-query/injected-memory data were captured, not the secrets,
accounts or API-key tables. No live search calls or service changes were necessary.
The source snapshot and raw replay traces were kept outside the repository and
deleted after verification. Repository artifacts retain synthetic traces and
anonymized real replay stage measurements, not real memory bodies or raw chat text.

## 1. Where the wrong memories enter

The tracer observes the unchanged function's actual candidate and ranked lists,
then wraps its existing packing function to record inclusion and remaining budget.
It does not substitute another search implementation.

For a recorded Home Assistant/Ring follow-up:

| Record | Initial lexical position | Position after custom scoring | Included |
| --- | ---: | ---: | --- |
| Framekeep project | 14 | 1 | Yes; truncated |
| Home Assistant integration | 15 | 6 | No |

For another recorded porch-light question, the lighting-schedule memory was first
in lexical retrieval, then fourth after custom scoring. The first integration
record plus the second-ranked Framekeep record consumed the context; the lighting
record was not included. These are related-context probes, not claims that those
memories alone contain the final operational answer.

The custom score leads the final ordering; BM25 only breaks ties. Its substring
matches count each query token occurrence, including common and repeated words,
with title bonuses. Some real failures already have weak initial lexical ordering;
the problem is **not exclusively** the custom reranker.

All nine recorded queries filled the 64-candidate lexical shortlist. That demonstrates
broad candidate matching, but does not prove a particular missing fact was excluded
from that shortlist in every real example.

## 2. Controlled distractors prove budget starvation

Use the same dinner question and the same Jess food memory throughout:

| Corpus | Food memory lexical rank | Custom rank | Visible food evidence |
| --- | ---: | ---: | --- |
| Food memory only | 1 | 1 | Yes |
| Add garden checklist | 1 | 2 | Yes |
| Add long storage runbook | 1 | 2 | **No** |
| Add both distractors | 2 | 3 | **No** |

With only the food memory and runbook, the runbook moves ahead of the initially
first-ranked food memory. Packing truncates the runbook to use all **2,400 characters**.
The food memory is then offered **zero remaining characters**, so it is omitted even
though it is second and the result limit is five. This directly isolates a packing
failure as well as a ranking failure.

## 3. Wording, repetition and identifiers

- `Jess food preferences` and `What does Jess like eating?` retrieve the food evidence
  first. The longer natural dinner request moves it to lexical rank six and custom
  rank seven, followed by omission during packing.
- Removing one token at a time from that 26-token dinner request changes the food
  memory's custom rank between four and fourteen. **No single deletion restores its
  inclusion** under defaults. This is a compound failure, not one magic bad word.
- Adding `please` alone did not hurt that short successful query. A blanket claim
  that every polite word causes failure would be unsupported.
- Repeating `to` twelve times boosts unrelated records to score twelve while the
  food memory remains at six. Query token occurrences are not deduplicated. The
  paired queries differing only by `not my server` return the same IDs: lexical
  matching does not interpret that negation as an exclusion.
- `Jess` returns Jessica as well, ranking Jessica first in the small two-person test.
  `Jessica` returns only Jessica. Prefix matching can create asymmetric identity noise.
- `Peper` does not retrieve Pepper in the controlled spelling test. An exact IP
  lookup also matches other addresses through their shared numeric fragments.
- The first **64 query tokens** are retained. Putting `Jess` after 64 filler tokens
  removes it from retrieval; moving it to the start restores its candidate match.
  This contrived positional probe establishes the cap, not its prevalence in real use.

## 4. The answer's position matters

A runbook was held constant except for placing its answer at the start, middle,
end or in its summary. At 800 and 2,400 characters, the answer at the start or in
the summary survived. The middle/end answers were absent even though the correct
record ID was returned. At 12,000 characters, all four survived.

This confirms prefix-oriented truncation rather than answer-aware extraction.
Increasing budgets can recover evidence but does not establish relevance or prevent
another long record from monopolizing the available context.

## 5. Growth alone versus overlapping records

The same exact lookup was tested with 0, 10, 64, 100 and 1,000 distractors:

- With genuinely unrelated distractors, the target remains first and visible at
  every tested size.
- With ten strongly overlapping near-duplicate distractors, it drops to eleventh
  and is not returned.
- With 64 or more overlapping distractors, it is absent from the 64-candidate
  shortlist entirely. Later reranking cannot recover it.

These are deliberately adversarial title/body placements, not a forecast of failure
at 64 real memories. They distinguish **overlap/duplication and shortlist pressure**
from database size itself.

## 6. Freshness, lifecycle and scope

When an old DNS fact has a highly matching title, it precedes the newer migration
fact if both remain active. Marking the old record archived or superseded excludes
it as expected. A stale **fact** remains eligible and still ranks first in this
probe; that reflects the existing stale-fact policy, not a failed stale-profile filter.
Retrieval cannot reliably decide which contradictory active fact is true from word
overlap alone.

The scope pairs confirm that default retrieval searches the active space plus
General, while explicit broader retrieval searches permitted spaces. Broadening
finds office records from a personal default but also introduces the home Atlas
record into competition. Same-named hosts need more than unconstrained broadening.
The previous restricted-grant test still passes; no access-boundary defect was found.

## 7. Conversation and Hermes behaviour

The installed Hermes helpers forward the **current message text only**. The test
sequence sends `And its address?` exactly, without adding the prior server question.
The native adapter's repeated direct question gives identical results before and
after topic changes, so no stale result cache was demonstrated in this sequence.
Some follow-ups happen to retrieve a useful record through overlapping words;
that is not proof of reference resolution.

The installed sidecar helper preserves earlier injected context when substituting
saved `api_content`, and source inspection confirms historical sidecars are replayed
in API message construction. Therefore earlier wrong context can remain in the
conversation history even when the latest recall changes. This is separate from a
fresh wrong recall. We verified that contract in isolation, not its effect on a
particular final model answer or its lifetime across all compaction paths.

The actual recorded bad injections, plus nine exact offline replays, establish that
the model really was supplied irrelevant memories. They do **not** establish how
much each injection influenced the generated answer. No model/subscription/API
usage was consumed for these diagnostics.

## Areas justified for the next improvement comparison

1. **Query representation and entity matching:** conversational filler, repeated
   words, exact identifiers, name boundaries, query truncation and follow-up referents.
2. **Candidate selection and ranking:** preserve genuinely useful candidates, handle
   duplicate competition, and assess custom scoring against the lexical baseline.
3. **Context packing and evidence selection:** prevent one distractor consuming the
   budget; evaluate visible answer facts, not IDs alone.
4. **Relevance/abstention and context lifecycle:** distinguish global preferences from
   topical memories and examine how past injected context survives topic changes.
5. **Fact lifecycle:** distinguish active corrections from outdated active facts;
   preserve the working archive/supersession and permission boundaries.

Category exclusion and high/low priority inconsistencies identified in the initial
evaluation remain separate known issues. No stopword policy, embedding model,
reranker, budget, or consolidation change has been chosen by these tests.

## Artifacts and limits

- [Diagnostic traces and anonymized real-stage measurements](diagnostics.json)
- [Installed Hermes contract check and source fingerprint](hermes-contract.json)
- Runner: `scripts/diagnose_prefetch.py`; helper: `scripts/probe_hermes_prefetch_contract.py`

Synthetic re-run from repository root:

```bash
python scripts/diagnose_prefetch.py \
  --hermes-adapter ../glyphhold-hermes-memory/__init__.py \
  --output /tmp/prefetch-synthetic-diagnostics.json
python -m pytest -q tests/test_prefetch_diagnostics.py tests/test_prefetch_evaluation.py
```

Real replay additionally needs a fresh private memory-only JSON snapshot. Its input
contains `memories`, `memory_categories`, and selected `history` entries with `query`
and `logged_context`; it is not a full database export. The previous private capture
was deleted, so replaying those same historical cases requires re-capture. Default
outputs omit real chat text, memory titles, bodies and IDs. Optional raw metadata
traces must be written outside source control and removed after inspection.

This is causal diagnosis of selected failures and synthetic boundaries, not a new
unseen accuracy benchmark. Earlier independent-agent labels informed the synthetic
targets; the real related-context targets were inspected during diagnosis and are
not independently adjudicated human gold labels. A representative, held-out,
human-reviewed answer/evidence evaluation and model-level conversation test remain
necessary before claiming a production accuracy improvement.
