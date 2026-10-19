"""Evaluate independently authored question sets against the same synthetic corpus."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.evaluate_prefetch import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-adapter", type=Path)
    parser.add_argument("--directory", type=Path, default=Path("evaluations/prefetch"))
    args = parser.parse_args()
    base = json.loads((args.directory / "corpus.json").read_text())
    keys = {memory["key"] for memory in base["memories"]}
    sources = sorted(args.directory.glob("agent_*_cases.json"))
    if len(sources) != 3:
        raise ValueError("Expected exactly three independently authored case sets")
    locked = []
    for source in sources:
        raw = source.read_bytes()
        data = json.loads(raw)
        if len(data["cases"]) != 15:
            raise ValueError(f"Expected 15 cases in {source}")
        identifiers = set()
        for case in data["cases"]:
            if case["id"] in identifiers:
                raise ValueError("Duplicate case ID")
            identifiers.add(case["id"])
            if not set(case["required"] + case.get("acceptable", [])) <= keys:
                raise ValueError("Unknown memory label")
            if not case["query"].strip():
                raise ValueError("Empty queries belong in separate raw API probes")
        locked.append((source, hashlib.sha256(raw).hexdigest(), data))
    # Persist all labels and their hashes before any retrievals run.
    manifest = {
        "synthetic_only": True,
        "corpus_sha256": hashlib.sha256((args.directory / "corpus.json").read_bytes()).hexdigest(),
        "labels": [{"file": p.name, "sha256": sha} for p, sha, _ in locked],
    }
    (args.directory / "agents-label-lock.json").write_text(json.dumps(manifest, indent=2) + "\n")
    summaries = []
    for source, sha, data in locked:
        report = evaluate(
            {"memories": base["memories"], "cases": data["cases"]}, args.hermes_adapter
        )
        report["author"] = data["author"]
        report["style"] = data["style"]
        report["labels_sha256"] = sha
        report["label_provenance"] = data.get("label_provenance", "See source case set")
        destination = source.with_name(source.name.replace("_cases.json", "_results.json"))
        destination.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        summaries.append(
            {
                "author": data["author"],
                "style": data["style"],
                "source": source.name,
                "results": destination.name,
                "summary": report["summary"],
            }
        )
    for source, sha, _ in locked:
        if hashlib.sha256(source.read_bytes()).hexdigest() != sha:
            raise RuntimeError("Labels changed during evaluation")
    (args.directory / "agents-summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
