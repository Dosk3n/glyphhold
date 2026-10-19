# Selective recall 2.2.0 — release evaluation

## Decision

Release the existing lexical candidate as a precision/abstention improvement with
explicit search fallback. The owner clarified that prefetch is one stage of an
agent's memory workflow, and authorised complete workflow testing and deployment.
No new semantic model, runtime dependency, schema migration or API parameter is
introduced. The frozen retrieval source remains unchanged from the earlier review.

Automatic required-record coverage remains **68/88 versus 74/88**, while unrelated
injections fall from **103/108 to 15/108**. Do not present this as an unconditional
recall or answer-accuracy gain. A weak or empty prefetch may require another search.

## Frozen workflow comparison

Sixteen answer-labelled questions were frozen before execution in
`workflow-cases.json`. Two independent workers received unnamed policies A/B and
the same read-only synthetic protocol backed by actual Glyph Hold search/get.
Each worker ran its cases as a batch, instructed to treat every case independently
and never inspect fixtures, labels or the other worker's answers. Neither received
the expected answer terms. A third reviewer checked each answer against its own
case's actual tool trace and the frozen labels.

| Metric | Existing recall | Selective recall |
| --- | ---: | ---: |
| Correct answers, frozen terms plus manual review | 16/16 | 16/16 |
| Search calls | 9 | 11 |
| Full-record reads | 1 | 1 |
| Prefetched result characters | 27,701 | 6,152 |
| Complete prefetch JSON characters | 31,488 | 11,316 |

The candidate reduces result characters 77.8%, or 64.1% including the complete
JSON envelope. Both correctly search for paraphrased personal facts, deliberately
broaden from Work to find home Atlas port 8096, resolve the supplied Garden
Assistant conversation history, and decline to invent an unknown birthday.
The candidate also follows fiancée → Jess → peanut preference using two searches.
Every final personal claim has supporting evidence in that case's own trace.

The old prefetch omitted the recovery command from a long runbook; a full-record
read recovered it. The new excerpt already retained the command and the worker
also fetched the full record. This does not demonstrate that the candidate needed
that read to recover omitted evidence.

Evidence is retained in `workflow-agent-results.json` and the two fictional-data
`workflow-*-trace.jsonl` files. No production memories or secrets were used.

## Limits

This is one worker per policy, not 32 isolated turns or a statistical multi-model
study. Shared batch context may influence a worker despite the independence
instruction; same-case evidence verifies supported answers, not private reasoning.
The questions reuse the synthetic confirmation corpus and are not representative
real traffic. No end-to-end latency, actual model-token comparison, or Hermes model
accuracy was measured. The earlier retrieval-only results remain separate evidence.

Subscription CLI probes were attempted first, using the official non-interactive
CLI and read-only synthetic MCP tools. The default model returned 429 errors; the
locally configured model was rejected as unsupported for that client/account, and
other bounded probes timed out. They produced no scored answers and are execution
failures, not accuracy failures. No API key or API credits were used. The successful
comparison used the independent agents available in this Codex chat instead.

## Integration and rollout

Hermes, MCP and Nexus now explain that even nonempty recall may concern the wrong
entity/space, that missing personal facts merit explicit search, and that shorter
terms/synonyms or a full-record lookup may be needed. Broader discovery remains
explicit and does not change write destination. No tool parameters changed.

Backend and adapter tests, the actual installed Hermes base-provider contract,
the final Docker build and disposable authenticated HTTP smoke checks must pass
before cutover. Pepper receives a private verified backup of data/configuration
and installed adapters; retain the old image and use an explicit immutable release
digest. Production checks must preserve memory contents, provider settings, grants,
secrets and Codex authentication state, and verify Hermes and MCP read-only calls.
The exact deployment outcome is recorded separately after cutover.

Optional local embeddings remain an experiment. Their extra recall benefit and
runtime complexity are not required for this release.
