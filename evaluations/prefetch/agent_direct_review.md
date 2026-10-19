# Direct-case review

Original labels remain unchanged. Both `hermes_defaults` and `pins_disabled` retrieve every required memory: required recall is 1.0, with no missing visible evidence. Only 1/15 cases strictly passes in either variant; 14 contain records outside the original acceptable sets. Micro precision improves only slightly from 0.3115 to 0.322 with pins disabled. Pin injection therefore does not explain most excess retrieval.

The visible bodies actually support the requested answers across the 12 topical cases: hosting services and IP, both resolver facts, SSH keys and restart permission, backup time and restore verification, person facts, media/database ports, and hostname-based password lookup. This is stronger than matching record IDs alone. The two explicit work cases stay within Work plus General in the reviewed variants; the weekday backup case is the sole clean strict pass.

Two concrete examples:

- `agent-direct-01`, “List services hosted on 192.168.1.190.”: defaults includes the full host body naming Hermes and Glyph Hold, so the answer is available. It also returns the new resolver, garden checklist, old resolver, and backup instructions. With pins disabled, SSH replaces backup while the other distractions remain.
- `agent-direct-13`, “Convert 4096 bytes to KiB.”: defaults returns SSH, resolver migration, and backup records, none needed for the answer (4 KiB). Pins disabled removes backup but still returns SSH and resolver migration. All three abstention cases fail in both variants, including the arithmetic-only request.

Some original acceptable sets are arguably strict about contextual neighbours: `host` in the Pepper upgrade case, `backup` in the Pepper restart case, and historical `dns` beside the current resolver could reasonably be tolerated as background. The labels intentionally score relevance to the requested answer; relaxing these would improve individual precision but would not excuse garden checklists, peppermill shipments, unrelated person records, or the abstention failures. Global response style was already allowed for natural requests, so that preference does not explain the poor precision.

Limitations: 15 synthetic queries over 22 synthetic memories, with only two work-scoped cases and no follow-ups; this does not measure live infrastructure or generated-answer accuracy. Initial corpus inspection accidentally exposed existing cases before authoring, as recorded in label provenance, so this is independently authored rather than fully blind testing. Visible evidence was inspected, but there are no case-specific evidence substrings in these original labels; the automated zero-missing-evidence metric alone would be insufficient. Timings are local retrieval measurements, not end-to-end assistant latency.
