# Prefetch evaluation — 19 October 2026

The current retrieval implementation reproduces irrelevant injections, weak
ranking, and loss of useful evidence under the Hermes character budget. Increasing
the number of results is not an adequate fix: it improves coverage while adding
more unrelated material. No runtime application code or deployed settings changed.

## Scope and method

- Glyph Hold 2.1.3, with the sibling Hermes 2.1.3 adapter's **actual prefetch method**.
- 22 synthetic memories, 31 labelled messages, five configurations: **155 retrievals**.
- Separate probes cover priority, disabled categories, empty input and denied spaces.
- Labels were authored before the first baseline run. This is a small, deliberately
  difficult development set, **not** a representative or independent benchmark.
- No production database, real memory export, secrets, API credits, Codex calls,
  SSH access, network retrieval or production modifications were used by the runner.
- The evaluator creates a temporary SQLite database, uses the unchanged core search,
  then deletes that database and restores the original database setting.
- Hermes transport alone is substituted with local core calls. All 31 nonempty
  default queries also pass through the actual adapter and produce the same IDs.
  This is not a full Hermes conversation/model test or a test of Pepper's deployed
  configuration. Adapter defaults may differ from user-configured live values.
- References to Pepper, Jess and other names in fixtures are **synthetic test data**;
  the corpus must never be imported or saved as real user memories.

Each case labels required memories and optional acceptable memories. Returned
records outside that union count as irrelevant; absence of a required record counts
as a miss. One long-memory case additionally requires a fact to remain visible in
the injected text. A strict pass requires all three checks to succeed. This is a
retrieval evaluation, not a measure of generated-answer accuracy.

## Results

| Configuration | Cases with unrelated results | Cases missing required records | Cases losing required visible evidence | Strict passes |
| --- | ---: | ---: | ---: | ---: |
| Hermes defaults: 5 records / 2,400 characters | 30/31 | 4/31 | 1/31 | 0/31 |
| 5 records / 12,000 characters | 31/31 | 4/31 | 0/31 | 0/31 |
| 10 records / 12,000 characters | 31/31 | 2/31 | 0/31 | 0/31 |
| Explicitly search all granted spaces, 5 / 2,400 | 30/31 | 3/31 | 1/31 | 0/31 |
| Pinned fixture changed to normal, 5 / 2,400 | 23/31 | 4/31 | 1/31 | 7/31 |

The corpus deliberately includes one task-specific pinned backup record. Many
strict failures therefore include that record even when the required answer was
found. **Zero strict passes does not mean zero correct memories**, and 30/31 does
not estimate the user's real-world failure rate. Default retrieval found 21 of 25
required record occurrences (84%); only 27.6% of returned records were labelled
required or acceptable. Removing pin injection alone still leaves 23 noisy cases.

Reported local retrieval medians in the saved run are about 2–4 ms. They exclude HTTP, network,
Hermes scheduling and LLM latency, and must not be presented as Pepper timings.

## Concrete reproductions

| Input | Default retrieval behaviour |
| --- | --- |
| `Who is Jess?` | Jess relationship and food records, plus unrelated garden planning, DNS and home server records. |
| `192.168.1.190` | Correct host plus other DNS addresses and the pinned backup record. |
| `Vaultwarden default folder` | Correct setup record plus unrelated pinned backup instructions. |
| `pepper` | Backup, host, **peppermill delivery**, SSH: a prefix collision. |
| `Where do I watch my films?` | Misses the Jellyfin/home media memory; returns backup, host, planning and diagnostic records. |
| `quasars` | Injects the pinned backup record despite no lexical match. |
| `Storage recovery runbook` | Finds the right record, but loses its critical tail detail at 2,400 characters; 12,000 preserves it. |
| Explicit office Atlas question from personal default | Does not retrieve the work record without an explicit broader search. |

Full ranked output, serialized visible contents and per-case labels are recorded in
[baseline.json](baseline.json). Examples describe these fixtures, not live results.

## Findings in the implementation

1. **Conversational noise.** Every token, including short common words, enters an
   OR/prefix FTS query. The subsequent score counts substring occurrences of query
   terms and adds title bonuses. Common words can outweigh the actual entity or
   intent. BM25 is a secondary ordering factor after that custom score.
2. **Identifiers lose structure.** IP addresses and hostnames are split into word
   fragments. Prefix retrieval treats `pepper` as matching `peppermill`. Exact entity
   and identifier matching need different treatment from conversational wording.
3. **No relevance gate.** Weak lexical matches can be injected without a minimum
   relevance criterion. Unmatched pins have a bounded count, but can still inject.
4. **Priority mismatch.** An identical low-priority fixture ranks ahead of the older
   high-priority fixture. Code inspection confirms high/normal/low are not used in
   this v2 scoring expression; this is not evidence that low is explicitly preferred.
5. **Category exclusion mismatch.** A record in a category with
   `allow_auto_prefetch=False` is returned by v2 recall. It joins categories without
   filtering that field. The per-record `never` exclusion and archived filtering work
   in the tested cases; this category probe is distinct from those exclusions.
6. **Scope and fallback.** Default-space-plus-General retrieval works as designed.
   Explicit broadening can find permitted cross-space records, but indiscriminate
   broadening also increases noise. A restricted work-only connection still returns
   only work records under `broaden=True`; no access-boundary failure was observed.
7. **Useful evidence can be truncated.** Retrieval of a record ID is not enough if
   the answer-bearing passage is absent. More characters fixed the long runbook
   case but consumed more context and did not improve precision.
8. **Follow-ups need a separate input strategy.** The local adapter forwards the
   supplied query and does not infer a referent from prior messages. The upstream
   Hermes source checked on the evaluation date passes the current user-message
   text into prefetch. Some follow-up cases coincidentally retrieve the right memory
   through overlapping words; that does not demonstrate reference resolution.
9. **Limited diagnostics.** Recall returns IDs and context/scope, but not the ranking
   explanation, confidence, or matched fields needed to explain a wrong injection.

Sources inspected: [core retrieval](../../app/v2/core.py), sibling Hermes adapter
`../glyphhold-hermes-memory/__init__.py`, and current upstream
[Hermes turn context](https://github.com/NousResearch/hermes-agent/blob/main/agent/turn_context.py).
Upstream main can change; this evaluation did not verify Pepper's installed Hermes
revision or reproduce yesterday's actual messages.

## Recommended next experiment

Keep this baseline and compare candidates in isolation before deploying anything:

1. Correct category exclusion, define priority behaviour, and separate always-useful
   preferences from task-specific pinned context. Decide what "pinned" promises
   before changing that behaviour.
2. Compare query cleaning and exact entity/IP/hostname matching with a stronger
   BM25 baseline. Preserve names, negation and identifiers; avoid a blind stopword
   list or hand-written rules for particular people.
3. Add a calibrated relevance/abstention decision and ranking diagnostics. Returning
   no topical memories should be an expected outcome for unrelated questions.
4. Test relevant-passage extraction and a bounded fallback search across granted
   spaces when the default-space evidence is weak. Never expand grants or alter the
   write destination because a query mentions another scope.
5. Compare an optional local semantic/hybrid candidate if lexical improvements still
   miss paraphrases. Do not assume embeddings or a larger context fix relevance.
6. Evaluate conversation-aware queries separately, using a bounded amount of prior
   user context and explicit topic changes. Do not mix recalled text or generated
   answers back into the query as independent evidence.

Before selecting a production candidate, add the user's actual failed messages and
an approved memory-only snapshot with independently reviewed expected results.
Include normal successful conversations and an unseen holdout, not only failures.
Compare per-group precision/coverage, abstention, context size and latency. Check
that improvements do not come at the cost of scope boundaries or excluded memories.

No implementation candidate has been tuned, selected, pushed or deployed by this
evaluation. No claim of semantic accuracy on live user memories is warranted yet.

## Reproduce

From the repository root in an environment with the project's dependencies:

```bash
python scripts/evaluate_prefetch.py \
  --hermes-adapter ../glyphhold-hermes-memory/__init__.py
python -m pytest -q tests/test_prefetch_evaluation.py
```

Without the optional adapter argument, the runner evaluates core retrieval alone.
It exits successfully when measurements complete, even when quality labels fail;
quality scores are research results, not claims that the current algorithm passes.
The two harness tests check isolation, cleanup on failure and repeatability.
