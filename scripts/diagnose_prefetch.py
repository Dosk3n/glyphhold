"""Causal probes of unchanged recall, using disposable databases and read-only tracing.

Optional private input is a MEMORY-ONLY snapshot, never a production SQLite file.
Outputs contain query/ranking metadata, not memory bodies or credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.core.auth import create_api_key
from app.storage.db import connection
from app.storage.migrations import apply_migrations
from app.v2 import core


@contextmanager
def fixture(memories=None, snapshot=None):
    original = settings.db_path
    counter = itertools.count()
    try:
        with (
            tempfile.TemporaryDirectory(prefix="gh-recall-diagnostic-") as directory,
            patch("app.v2.core.new_id", side_effect=lambda p: f"{p}_{next(counter):022d}"),
        ):
            object.__setattr__(settings, "db_path", Path(directory) / "isolated.sqlite")
            apply_migrations()
            core.ensure_schema()
            kid, _ = create_api_key(
                name="offline probe", actor="probe", description=None, scopes=["memories:read"]
            )
            core.set_connection(
                core.ADMIN,
                kid,
                {
                    "default_space_id": "space_personal",
                    "grants": [
                        {"space_id": "space_" + s, "can_read": True, "can_write": True}
                        for s in ["personal", "work", "general"]
                    ],
                },
            )
            ids = {}
            if snapshot is not None:
                with connection() as c:
                    for table in ["memory_categories", "memories"]:
                        columns = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
                        for record in snapshot[table]:
                            row = {k: v for k, v in record.items() if k in columns}
                            names = list(row)
                            # Table/column identifiers come from these fixed local schemas.
                            c.execute(
                                f"INSERT OR REPLACE INTO {table} ({','.join(names)}) "
                                f"VALUES ({','.join('?' for _ in names)})",
                                list(row.values()),
                            )
                ids = {r["id"]: r["id"] for r in snapshot["memories"]}
            else:
                for index, record in enumerate(memories or []):
                    data = {k: v for k, v in record.items() if k not in {"key", "repeat", "tail"}}
                    data["body"] = data["body"] * record.get("repeat", 1) + record.get("tail", "")
                    row = core.create_memory(core.ADMIN, data, "probe-" + record["key"])
                    ids[record["key"]] = row["id"]
                    timestamp = (
                        datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index)
                    ).isoformat()
                    with connection() as c:
                        c.execute(
                            "UPDATE memories SET updated_at=? WHERE id=?", (timestamp, row["id"])
                        )
            yield core.Principal(kid, "probe", {"memories:read"}), ids
    finally:
        object.__setattr__(settings, "db_path", original)


def trace_recall(principal, ids, query, required=(), evidence=None, **options):
    """Observe actual search locals and actual packing; do not reimplement ranking."""
    from app.v2 import retrieval

    reverse = {value: key for key, value in ids.items()}
    captured = {}
    packing = []
    modern = "retrieve" in core.search.__code__.co_varnames
    bounded = retrieval.pack if modern else core._bounded_result

    def pack(record, *args):
        budget = args[-1]
        result = bounded(record, *args)
        packing.append(
            {
                "key": reverse.get(record["id"], record["id"]),
                "remaining_budget": budget,
                "included": result is not None,
                "truncated": bool(result and result.get("truncated")),
                "visible_body_chars": len((result or {}).get("body", "")),
            }
        )
        return result

    def observe(frame, event, arg):
        if (
            frame.f_code in {core.search.__code__, retrieval.recall.__code__}
            and event == "return"
            and "rows" in frame.f_locals
        ):
            captured.update(frame.f_locals)

    previous = sys.getprofile()
    try:
        sys.setprofile(observe)
        with patch(
            "app.v2.retrieval.pack" if modern else "app.v2.core._bounded_result", side_effect=pack
        ):
            result = core.search(
                principal,
                query,
                recall=True,
                limit=options.pop("limit", 5),
                max_chars=options.pop("max_chars", 2400),
                **options,
            )
    finally:
        sys.setprofile(previous)
    terms = captured["terms"]
    matched_ids = captured.get("matched_ids", {r["id"] for r in captured["rows"]})
    lexical = [r for r in captured["rows"] if r["id"] in matched_ids]
    candidate_positions = {r["id"]: i + 1 for i, r in enumerate(lexical)}
    ranked = []
    scored = captured.get(
        "scored",
        [
            (score, row, row["auto_prefetch_level"] == "pinned")
            for score, row in captured.get("scores", [])
        ],
    )
    for index, (score, row, pinned) in enumerate(scored):
        text = " ".join(
            [row["title"], row["summary"] or "", row["body"], " ".join(row["tags"])]
        ).lower()
        ranked.append(
            {
                "key": reverse.get(row["id"], row["id"]),
                "title": row["title"],
                "rank": index + 1,
                "lexical_rank": candidate_positions.get(row["id"]),
                "score": score,
                "bm25": row.get("fts_rank"),
                "pinned": pinned,
                "matched_terms": [
                    term for term in terms if term in (retrieval.words(text) if modern else text)
                ],
                "contribution_rule": "whole_word" if modern else "substring",
                "title_contributions": [term for term in terms if term in row["title"].lower()],
            }
        )
    returned = [reverse[r["id"]] for r in result["results"]]
    targets = []
    for key in required:
        rank = next((r for r in ranked if r["key"] == key), None)
        packed = next((r for r in result["results"] if reverse[r["id"]] == key), None)
        needle = (evidence or {}).get(key)
        visible = (
            " ".join(str(packed.get(k, "")) for k in ["title", "summary", "body"]) if packed else ""
        )
        targets.append(
            {
                "key": key,
                "lexical_candidate": ids.get(key) in matched_ids,
                "lexical_rank": rank["lexical_rank"] if rank else None,
                "reranked_position": rank["rank"] if rank else None,
                "returned": key in returned,
                "evidence_visible": needle.casefold() in visible.casefold() if needle else None,
            }
        )
    return {
        "query": query,
        "terms": terms,
        "candidate_limit": captured["candidate_limit"],
        "lexical_candidates": len(lexical),
        "ranked_candidates": len(ranked),
        "returned": returned,
        "targets": targets,
        "packing": packing,
        "top_ranked": ranked[:12],
        "context": result["context"],
        "character_count": result["character_count"],
    }


def memory(key, title, body, **fields):
    return {"key": key, "title": title, "body": body, "space_id": "space_personal", **fields}


def run(snapshot_path=None, hermes_adapter=None):
    corpus = json.loads(Path("evaluations/prefetch/corpus.json").read_text())
    experiments = []
    adapter_sequence = []

    def save(group, label, principal, ids, query, required=(), evidence=None, **options):
        row = trace_recall(principal, ids, query, required, evidence, **options)
        row.update(group=group, label=label)
        experiments.append(row)
        return row

    with fixture(corpus["memories"]) as (p, ids):
        for query in [
            "Jess food preferences",
            "What does Jess like eating?",
            "I want to take Jess out for a meal this weekend. What sort of place would suit her, and is there anything to steer clear of?",
            "Jess food preferences please",
            "I was wondering about Jess food preferences",
            "Jess food preferences " + "please " * 12,
            "Jess food preferences and my server",
            "Jess food preferences and not my server",
            "Jess food preferences to",
            "Jess food preferences " + "to " * 12,
        ]:
            save("wording", "dining", p, ids, query, ["jess-food"], {"jess-food": "peanuts"})
        # Remove one actual token at a time, rather than guessing which filler matters.
        import re

        long_query = "I want to take Jess out for a meal this weekend. What sort of place would suit her, and is there anything to steer clear of?"
        tokens = re.findall(r"\w+", long_query)
        for index, token in enumerate(tokens):
            query = " ".join(tokens[:index] + tokens[index + 1 :])
            save(
                "word_removal",
                f"remove_{index}_{token}",
                p,
                ids,
                query,
                ["jess-food"],
                {"jess-food": "peanuts"},
            )
        for query in [
            "192.168.1.190",
            "Pepper",
            "Peper",
            "quasars",
            "Calculate 19 times 23.",
            "Tell me about quasars please",
            "word " * 64 + "Jess",
            "Jess " + "word " * 64,
        ]:
            save(
                "tokens",
                "identifiers_and_limits",
                p,
                ids,
                query,
                ["host"]
                if query in {"192.168.1.190", "Pepper", "Peper"}
                else ["jess"]
                if "Jess" in query
                else [],
            )
        sequence = [
            "Jess food preferences",
            "And what should she avoid?",
            "Now leave Jess aside. Which box runs Hermes?",
            "And its address?",
            "Jess food preferences",
            "Which box runs Hermes?",
            "Jess food preferences",
        ]
        for query in sequence:
            save("conversation", "latest_message_only_sequence", p, ids, query)
        if hermes_adapter:
            spec = importlib.util.spec_from_file_location("diagnostic_adapter", hermes_adapter)
            adapter = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(adapter)
            provider = adapter.GlyphHoldMemoryProvider()

            class LocalClient:
                def recall(self, **payload):
                    return core.search(p, recall=True, **payload)

            provider.client = LocalClient()
            provider.space_id = "space_personal"
            reverse = {v: k for k, v in ids.items()}
            for query in sequence:
                block = provider.prefetch(query, session_id="diagnostic-sequence")
                recalled = (
                    json.loads(block.split("\n", 1)[1].rsplit("\n", 1)[0])["memories"]
                    if block
                    else []
                )
                adapter_sequence.append(
                    {"query": query, "returned": [reverse[r["id"]] for r in recalled]}
                )
        for query in ["Atlas", "Atlas office database port", "Atlas home media port"]:
            for broaden in [False, True]:
                save(
                    "scope",
                    "explicit_broaden" if broaden else "default",
                    p,
                    ids,
                    query,
                    ["atlas-work"] if "office" in query else ["atlas-home"],
                    broaden=broaden,
                )

    dining = next(m for m in corpus["memories"] if m["key"] == "jess-food")
    long = next(m for m in corpus["memories"] if m["key"] == "long")
    checklist = next(m for m in corpus["memories"] if m["key"] == "checklist")
    dinner_query = "I want to take Jess out for a meal this weekend. What sort of place would suit her, and is there anything to steer clear of?"
    for label, memories in [
        ("target_only", [dining]),
        ("plus_checklist", [dining, checklist]),
        ("plus_runbook", [dining, long]),
        ("both_distractors", [dining, checklist, long]),
    ]:
        with fixture(memories) as (p, ids):
            save(
                "distractors", label, p, ids, dinner_query, ["jess-food"], {"jess-food": "peanuts"}
            )

    needle = "RESTORE-VERIFY-OMEGA"
    filler = "Storage preparation inventory. " * 250
    for position in ["start", "middle", "end", "summary"]:
        body = {
            "start": needle + filler,
            "middle": filler[: len(filler) // 2] + needle + filler[len(filler) // 2 :],
            "end": filler + needle,
            "summary": filler,
        }[position]
        data = memory(
            "runbook",
            "Storage recovery runbook",
            body,
            summary=needle if position == "summary" else None,
        )
        with fixture([data]) as (p, ids):
            for budget in [800, 2400, 12000]:
                save(
                    "budget",
                    f"{position}_{budget}",
                    p,
                    ids,
                    "Storage recovery runbook",
                    ["runbook"],
                    {"runbook": needle},
                    max_chars=budget,
                )

    for count in [0, 10, 64, 100, 1000]:
        for kind in ["unrelated", "overlap"]:
            target = memory("target", "Approved fact", "Needlemarker approved answer is ORCHID.")
            distractors = [
                memory(
                    f"d{i}",
                    "Needlemarker " * 8 if kind == "overlap" else f"Zebradata {i}",
                    "Needlemarker status pending." if kind == "overlap" else "Unrelated metric.",
                )
                for i in range(count)
            ]
            with fixture([target, *distractors]) as (p, ids):
                save(
                    "scale",
                    f"{kind}_{count}",
                    p,
                    ids,
                    "Needlemarker",
                    ["target"],
                    {"target": "ORCHID"},
                )

    for status in ["both_active", "superseded", "archived", "stale_fact"]:
        with fixture(
            [
                memory("old", "Current DNS resolver", "Home resolver is OLD-ADDRESS."),
                memory("new", "Resolver migration", "Home resolver is NEW-ADDRESS."),
            ]
        ) as (p, ids):
            with connection() as c:
                if status == "superseded":
                    c.execute(
                        "UPDATE memories SET superseded_by=? WHERE id=?", (ids["new"], ids["old"])
                    )
                elif status == "archived":
                    c.execute("UPDATE memories SET archived=1 WHERE id=?", (ids["old"],))
                elif status == "stale_fact":
                    c.execute("UPDATE memories SET stale=1 WHERE id=?", (ids["old"],))
            save(
                "freshness",
                status,
                p,
                ids,
                "Current home DNS resolver",
                ["new"],
                {"new": "NEW-ADDRESS"},
            )

    with fixture(
        [
            memory("jess", "Jess relationship", "Jess is the fiancée."),
            memory("jessica", "Jessica colleague", "Jessica is a colleague."),
        ]
    ) as (p, ids):
        for query in ["Jess", "Jessica", "my fiancée"]:
            save("identity", query, p, ids, query, ["jessica"] if query == "Jessica" else ["jess"])

    live = []
    if snapshot_path:
        snapshot = json.loads(snapshot_path.read_text())
        related_titles = {
            19922: [
                "Loki log query method for home lab",
                "Hermes native Home Assistant integration",
            ],
            19952: [
                "Hermes native Home Assistant integration",
                "Front of house LED evening and morning schedule",
            ],
            19962: ["Hermes native Home Assistant integration"],
            19981: ["UniFi gateway dBox-Network"],
        }
        with fixture(snapshot=snapshot) as (p, ids):
            for event in snapshot["history"]:
                related_ids = [
                    m["id"]
                    for m in snapshot["memories"]
                    if m["title"] in related_titles.get(event["message_id"], [])
                ]
                row = trace_recall(p, ids, event["query"], related_ids)
                original_ids = [m["id"] for m in event["logged_context"]["memories"]]
                row.update(
                    message_id=event["message_id"],
                    original_returned=original_ids,
                    same_ids_as_recorded=row["returned"] == original_ids,
                    logged_truncated=[
                        m["id"] for m in event["logged_context"]["memories"] if m.get("truncated")
                    ],
                )
                live.append(row)
        live_meta = {
            "memory_count": len(snapshot["memories"]),
            "history_examples": len(live),
            "same_ids_as_recorded": sum(r["same_ids_as_recorded"] for r in live),
            "active_record_count": sum(
                not (m["archived"] or m["superseded_by"] or m["merged_into"])
                for m in snapshot["memories"]
            ),
            "active_pinned_count": sum(
                m["auto_prefetch_level"] == "pinned" and not m["archived"]
                for m in snapshot["memories"]
            ),
            "active_bodies_over_budget": sum(
                len(m["body"]) > 2400 and not m["archived"] for m in snapshot["memories"]
            ),
        }
    else:
        live_meta = None
    return {
        "version": settings.version,
        "search_source_sha256": hashlib.sha256(Path("app/v2/core.py").read_bytes()).hexdigest(),
        "synthetic_experiments": experiments,
        "native_adapter_sequence": adapter_sequence,
        "recorded_replays": live,
        "recorded_replay_summary": live_meta,
        "warning": "Read-only traces of unchanged code; metadata-only output. Not generated-answer evaluation.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-snapshot", type=Path)
    parser.add_argument("--hermes-adapter", type=Path)
    parser.add_argument(
        "--private-replay-output",
        type=Path,
        help="Optional mode-0600 output for raw question/title traces; keep outside source control",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("evaluations/prefetch/diagnostics.json")
    )
    args = parser.parse_args()
    result = run(args.memory_snapshot, args.hermes_adapter)
    raw_replays = result.pop("recorded_replays")
    if args.private_replay_output:
        fd = os.open(args.private_replay_output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(raw_replays, output, indent=2)
    # Publish stage measurements without copying real chat text, memory titles or IDs.
    result["recorded_replays"] = [
        {
            "example": index + 1,
            "same_ids_as_recorded": row["same_ids_as_recorded"],
            "lexical_candidates": row["lexical_candidates"],
            "candidate_limit": row["candidate_limit"],
            "returned_count": len(row["returned"]),
            "top_lexical_rank": row["top_ranked"][0]["lexical_rank"] if row["top_ranked"] else None,
            "top_custom_score": row["top_ranked"][0]["score"] if row["top_ranked"] else None,
            "related_targets": [
                {k: v for k, v in target.items() if k != "key"} for target in row["targets"]
            ],
        }
        for index, row in enumerate(raw_replays)
    ]
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "synthetic_probes": len(result["synthetic_experiments"]),
                "recorded_replays": result["recorded_replay_summary"],
            }
        )
    )


if __name__ == "__main__":
    main()
