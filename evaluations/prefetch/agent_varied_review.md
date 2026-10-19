# Independent varied-case review

Provenance: I authored all 15 labels after reading only the `memories` array of `corpus.json`. I had not read previous cases, baseline outputs, or retrieval results. Labels were fixed before this review. No labels, fixtures, results, source metadata, application code, or production data were changed during review. The later instruction to leave hashed metadata unchanged superseded the pending request to add provenance to the source JSON.

Default Hermes retrieval achieved 15/16 required record hits (93.75%) and 29.69% micro precision, with 2/15 strict passes and irrelevant records in 13/15 cases. This is good coverage with weak selectivity. The only missing required record was `ssh` in the misspelled Pepper upgrade question. All three self-contained requests needing no topical memory returned irrelevant topical records.

The larger budget kept required recall at 93.75% and reduced precision to 27.54%; more results reached 100% required recall but only 18.33% precision. Explicit broadening reduced required recall to 81.25% with 23.88% precision. Disabling pins retained 93.75% recall and only slightly improved precision to 30.65%, so pins alone do not explain the noise.

Two concrete examples:

1. `varied-07`, the explicit work-space office Atlas/backup question, passed under Hermes defaults: exactly `atlas-work`, `work-backup`, and acceptable `style` were returned. Both requested facts are visible and personal Atlas did not leak into this result.
2. `varied-02`, the SSH/upgrade question with “Peper”, returned `checklist`, `backup`, `jess-food`, `host`, and `jay`. It recovered upgrade verification but omitted SSH-key access instructions. Three records were unrelated despite the query naming SSH explicitly.

## Separate visible-evidence finding

`varied-10` is a record-ID pass under Hermes defaults, but it cannot answer the question from the supplied text: `long` is truncated to a 2,099-character body and `RESTORE-VERIFY-OMEGA` is absent. The same failure occurs for explicit broadening and pins disabled. Larger budget and more results expose the full 7,519-character body with the command present, while adding irrelevant records. This original case has no evidence requirement, so the headline `cases_missing_visible_evidence: 0` does not detect the failure. Counting the default result as an answerable success would be misleading; no labels have been altered to correct this after seeing results.

## Label caveats

- General concise UK-English style was deliberately acceptable in every case, including the three requests with no topical memory requirement.
- Pinned `backup` is scored irrelevant when the user does not need Pepper backup information. That measures topical relevance rather than whether pin inclusion follows current policy; poor precision persists with pins disabled.
- `varied-12` requires the supplied previous user message to resolve “before starting”. Its backup hit alone does not establish conversational inference, especially because backup is pinned. This follow-up should not be presented as proof of context handling without confirmation that the harness passed that message.
- `varied-09` allows old DNS details as migration context, but requires the current Unbound record. A hit metric cannot establish that an eventual answer chooses the current resolver.
- These are synthetic, small-sample retrieval results. They measure supplied record relevance and coverage, not end-to-end answer correctness, and the missing long-runbook evidence field limits the automated score.
