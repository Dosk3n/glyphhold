"""Offline retrieval evaluation. Creates/deletes its own synthetic SQLite database.

No HTTP requests, production database access, secrets, or algorithm changes.
Run from the repository root; optional --hermes-adapter exercises its real prefetch wrapper.
Quality failures are measurements, not an exit-code failure.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.core.auth import create_api_key
from app.storage.db import connection
from app.storage.migrations import apply_migrations
from app.v2 import core


def evaluate(corpus: dict, adapter_path: Path | None = None) -> dict:
    original = settings.db_path
    sequence = itertools.count()
    try:
        with (
            tempfile.TemporaryDirectory(prefix="glyphhold-prefetch-eval-") as directory,
            patch(
                "app.v2.core.new_id", side_effect=lambda prefix: f"{prefix}_{next(sequence):022d}"
            ),
        ):
            object.__setattr__(settings, "db_path", Path(directory) / "synthetic.sqlite")
            apply_migrations()
            core.ensure_schema()
            key_id, _ = create_api_key(
                name="offline evaluation",
                actor="evaluation",
                description=None,
                scopes=["memories:read", "memories:write"],
            )
            core.set_connection(
                core.ADMIN,
                key_id,
                {
                    "default_space_id": "space_personal",
                    "grants": [
                        {"space_id": s, "can_read": True, "can_write": True}
                        for s in ["space_personal", "space_work", "space_general"]
                    ],
                },
            )
            principal = core.Principal(key_id, "evaluation", {"memories:read"})
            ids = {}
            for index, memory in enumerate(corpus["memories"]):
                fields = {k: v for k, v in memory.items() if k not in {"key", "repeat", "tail"}}
                fields["body"] = fields["body"] * memory.get("repeat", 1) + memory.get("tail", "")
                row = core.create_memory(core.ADMIN, fields, "eval-" + memory["key"])
                ids[memory["key"]] = row["id"]
                # Stable timestamps/IDs remove wall-clock and random-ID tie breaking.
                with connection() as c:
                    c.execute(
                        "UPDATE memories SET updated_at=? WHERE id=?",
                        (f"2026-01-01T00:00:{index:02d}+00:00", row["id"]),
                    )
            reverse = {value: key for key, value in ids.items()}
            # Read-only recall probes, apart from isolated fixture setup below.
            from app.storage.repositories.categories import create_category

            disabled = create_category(name="Explicitly disabled", allow_auto_prefetch=False)
            disabled_row = core.create_memory(
                core.ADMIN,
                {
                    "title": "Categoryguard marker",
                    "body": "Categoryguard diagnostic.",
                    "space_id": "space_personal",
                    "category_id": disabled["id"],
                },
                "diagnostic-category",
            )
            priority_rows = core.search(principal, "Identical priority probe", recall=True)[
                "results"
            ]
            priority_order = [
                reverse[r["id"]]
                for r in priority_rows
                if r["id"] in {ids["priority-high"], ids["priority-low"]}
            ]
            category_rows = core.search(principal, "Categoryguard", recall=True)["results"]
            # Remove the diagnostic row so it cannot influence labelled measurements.
            with connection() as c:
                c.execute("UPDATE memories SET archived=1 WHERE id=?", (disabled_row["id"],))
            restricted_id, _ = create_api_key(
                name="scope guard", actor="guard", description=None, scopes=["memories:read"]
            )
            core.set_connection(
                core.ADMIN,
                restricted_id,
                {
                    "default_space_id": "space_work",
                    "grants": [{"space_id": "space_work", "can_read": True, "can_write": True}],
                },
            )
            restricted = core.Principal(restricted_id, "guard", {"memories:read"})
            restricted_result = core.search(
                restricted, "Jess Pepper Atlas", recall=True, broaden=True
            )
            diagnostics = {
                "empty_raw_recall_count": len(core.search(principal, "", recall=True)["results"]),
                "priority_high_low_order": priority_order,
                "disabled_category_recalled": any(
                    r["id"] == disabled_row["id"] for r in category_rows
                ),
                "restricted_broaden_returned_spaces": sorted(
                    {r["space_id"] for r in restricted_result["results"]}
                ),
                "restricted_broaden_respects_grants": all(
                    r["space_id"] == "space_work" for r in restricted_result["results"]
                ),
            }
            provider = None
            if adapter_path:
                spec = importlib.util.spec_from_file_location("prefetch_eval_hermes", adapter_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                provider = module.GlyphHoldMemoryProvider()
                diagnostics["empty_hermes_prefetch_returns_blank"] = provider.prefetch("") == ""

            variants = {
                "hermes_defaults": {"limit": 5, "max_chars": 2400},
                "larger_budget": {"limit": 5, "max_chars": 12000},
                "more_results": {"limit": 10, "max_chars": 12000},
                "explicit_broaden": {"limit": 5, "max_chars": 2400, "broaden": True},
                "pins_disabled": {"limit": 5, "max_chars": 2400},
            }
            measurements = []
            for variant, options in variants.items():
                with connection() as c:
                    c.execute(
                        "UPDATE memories SET auto_prefetch_level='normal' "
                        "WHERE auto_prefetch_level='pinned'"
                    )
                    if variant != "pins_disabled":
                        for memory in corpus["memories"]:
                            if memory.get("auto_prefetch_level") == "pinned":
                                c.execute(
                                    "UPDATE memories SET auto_prefetch_level='pinned' WHERE id=?",
                                    (ids[memory["key"]],),
                                )
                for case in corpus["cases"]:
                    args = dict(
                        options,
                        query=case["query"],
                        recall=True,
                        space_id=case.get("space_id", "space_personal"),
                    )
                    if "subject_keys" in case:
                        raise ValueError("Subject labels require explicit fixture support")
                    started = time.perf_counter()
                    result = core.search(principal, **args)
                    duration = (time.perf_counter() - started) * 1000
                    rows = result["results"]
                    returned = [reverse[row["id"]] for row in rows]
                    required = set(case["required"])
                    acceptable = required | set(case.get("acceptable", []))
                    missing = sorted(required - set(returned))
                    irrelevant = [key for key in returned if key not in acceptable]
                    evidence_missing = []
                    for key, text in case.get("evidence", {}).items():
                        row = next((r for r in rows if reverse[r["id"]] == key), {})
                        visible = " ".join(
                            str(row.get(k, "")) for k in ["title", "summary", "body"]
                        )
                        if text.casefold() not in visible.casefold():
                            evidence_missing.append(key)
                    # Exercise the unchanged adapter, substituting only its HTTP transport.
                    wrapper_ok = None
                    wrapper_chars = None
                    if provider and variant == "hermes_defaults" and case["query"].strip():

                        class LocalClient:
                            def recall(self, **payload):
                                return core.search(principal, recall=True, **payload)

                        provider.client = LocalClient()
                        provider.space_id = args["space_id"]
                        block = provider.prefetch(case["query"], session_id="offline-eval")
                        wrapper_chars = len(block)
                        if block:
                            parsed = json.loads(block.split("\n", 1)[1].rsplit("\n", 1)[0])
                            wrapper_ok = [r["id"] for r in parsed["memories"]] == [
                                r["id"] for r in rows
                            ]
                        else:
                            wrapper_ok = not rows
                        if not wrapper_ok:
                            raise AssertionError("Hermes wrapper differs from evaluated recall")
                    measurements.append(
                        {
                            "variant": variant,
                            "case": case["id"],
                            "group": case["group"],
                            "query": case["query"],
                            "required": sorted(required),
                            "acceptable": sorted(acceptable),
                            "returned": returned,
                            "missing": missing,
                            "irrelevant": irrelevant,
                            "missing_visible_evidence": evidence_missing,
                            "precision": (len(returned) - len(irrelevant)) / len(returned)
                            if returned
                            else None,
                            "required_recall": (len(required) - len(missing)) / len(required)
                            if required
                            else None,
                            "pass": not (missing or irrelevant or evidence_missing),
                            "retrieval_ms": round(duration, 3),
                            "result_chars": result["character_count"],
                            "wrapper_chars": wrapper_chars,
                            "wrapper_matches": wrapper_ok,
                            "context": result["context"],
                            "visible_results": [dict(r, id=reverse[r["id"]]) for r in rows],
                        }
                    )
            summaries = {}
            for variant in variants:
                rows = [r for r in measurements if r["variant"] == variant]
                summaries[variant] = {
                    "cases": len(rows),
                    "strict_passes": sum(r["pass"] for r in rows),
                    "cases_with_irrelevant": sum(bool(r["irrelevant"]) for r in rows),
                    "cases_with_missing": sum(bool(r["missing"]) for r in rows),
                    "cases_missing_visible_evidence": sum(
                        bool(r["missing_visible_evidence"]) for r in rows
                    ),
                    "micro_precision": round(
                        sum(len(r["returned"]) - len(r["irrelevant"]) for r in rows)
                        / max(1, sum(len(r["returned"]) for r in rows)),
                        4,
                    ),
                    "micro_required_recall": round(
                        sum(len(r["required"]) - len(r["missing"]) for r in rows)
                        / max(1, sum(len(r["required"]) for r in rows)),
                        4,
                    ),
                    "median_local_retrieval_ms": round(
                        statistics.median(r["retrieval_ms"] for r in rows), 3
                    ),
                }
            return {
                "schema_version": 1,
                "glyphhold_version": settings.version,
                "corpus_sha256": hashlib.sha256(
                    json.dumps(corpus, sort_keys=True).encode()
                ).hexdigest(),
                "synthetic_only": True,
                "memory_count": len(ids),
                "hermes_wrapper_exercised": provider is not None,
                "diagnostics": diagnostics,
                "summary": summaries,
                "measurements": measurements,
            }
    finally:
        object.__setattr__(settings, "db_path", original)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("evaluations/prefetch/corpus.json"))
    parser.add_argument("--output", type=Path, default=Path("evaluations/prefetch/baseline.json"))
    parser.add_argument("--hermes-adapter", type=Path)
    args = parser.parse_args()
    corpus = json.loads(args.corpus.read_text())
    report = evaluate(corpus, args.hermes_adapter)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
