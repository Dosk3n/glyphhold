"""Optional synthetic-only semantic fallback experiment; NOT a runtime provider.

Install fastembed separately to run. Downloads a public model on first use; all
corpus/query inference is local. No production data, API credits or settings used.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.v2 import core, retrieval
from scripts.diagnose_prefetch import fixture


def main():
    import numpy as np
    from fastembed import TextEmbedding

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("evaluations/prefetch/corpus.json"))
    parser.add_argument(
        "--output", type=Path, default=Path("evaluations/prefetch/semantic-comparison.json")
    )
    parser.add_argument("--include-agent-cases", action="store_true")
    args = parser.parse_args()
    corpus = json.loads(args.corpus.read_text())
    cases = list(corpus["cases"])
    if args.include_agent_cases:
        for path in sorted(args.corpus.parent.glob("agent_*_cases.json")):
            cases += json.loads(path.read_text())["cases"]
    memories = corpus["memories"]
    documents = [m["title"] + "\n" + (m.get("summary") or "") + "\n" + m["body"] for m in memories]
    started = time.perf_counter()
    model = TextEmbedding(
        "BAAI/bge-small-en-v1.5", cache_dir="/tmp/gh-prefetch-embedding-model", threads=2
    )
    vectors = np.array(list(model.passage_embed(documents)))
    queries = list(model.query_embed([c["query"] for c in cases]))
    elapsed = time.perf_counter() - started
    measurements = []
    with fixture(memories) as (p, ids):
        reverse = {v: k for k, v in ids.items()}
        for case, vector in zip(cases, queries):
            space = case.get("space_id", "space_personal")
            lexical = core.search(
                p, case["query"], space_id=space, recall=True, limit=5, max_chars=2400
            )
            rows = lexical["results"]
            attempted = not rows
            accepted = False
            scores = vectors @ vector
            eligible = [
                i
                for i, m in enumerate(memories)
                if m.get("space_id") in {space, "space_general"}
                and not m.get("archived")
                and not m.get("superseded_by")
                and not m.get("merged_into")
                and m.get("auto_prefetch_level") != "never"
            ]
            ordered = sorted(eligible, key=lambda i: -float(scores[i]))
            top = ordered[0] if ordered else None
            score = float(scores[top]) if top is not None else 0
            margin = score - float(scores[ordered[1]]) if len(ordered) > 1 else score
            # Fixed before holdout. Similarity alone must not force a result.
            if attempted and score >= 0.62 and margin >= 0.025:
                record = core.get_memory(p, ids[memories[top]["key"]])
                packed = retrieval.pack(record, retrieval.prepare(case["query"])[0], 2400)
                rows = [packed] if packed else []
                accepted = bool(rows)
            returned = [reverse[r["id"]] for r in rows]
            required = set(case["required"])
            acceptable = required | set(case.get("acceptable", []))
            missing = sorted(required - set(returned))
            irrelevant = sorted(set(returned) - acceptable)
            evidence_missing = []
            for key, evidence in case.get("evidence", {}).items():
                row = next((r for r in rows if reverse[r["id"]] == key), {})
                if (
                    evidence.casefold()
                    not in " ".join(
                        str(row.get(k, "")) for k in ["title", "summary", "body"]
                    ).casefold()
                ):
                    evidence_missing.append(key)
            measurements.append(
                {
                    "case": case["id"],
                    "query": case["query"],
                    "lexical_returned": [reverse[r["id"]] for r in lexical["results"]],
                    "returned": returned,
                    "required": sorted(required),
                    "missing": missing,
                    "irrelevant": irrelevant,
                    "missing_visible_evidence": evidence_missing,
                    "semantic_attempted": attempted,
                    "semantic_accepted": accepted,
                    "similarity": round(score, 4),
                    "margin": round(margin, 4),
                    "pass": not (missing or irrelevant or evidence_missing),
                }
            )
    summary = {
        "cases": len(cases),
        "semantic_accepted": sum(r["semantic_accepted"] for r in measurements),
        "strict_passes": sum(r["pass"] for r in measurements),
        "cases_with_missing": sum(bool(r["missing"]) for r in measurements),
        "cases_with_irrelevant": sum(bool(r["irrelevant"]) for r in measurements),
        "required_found": sum(len(r["required"]) - len(r["missing"]) for r in measurements),
        "required_total": sum(len(r["required"]) for r in measurements),
        "local_model_and_batch_seconds": round(elapsed, 3),
    }
    args.output.write_text(
        json.dumps(
            {
                "model": "BAAI/bge-small-en-v1.5",
                "retrieval_source_sha256": hashlib.sha256(
                    Path("app/v2/retrieval.py").read_bytes()
                ).hexdigest(),
                "runtime_integration": False,
                "threshold": 0.62,
                "margin_threshold": 0.025,
                "summary": summary,
                "measurements": measurements,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
