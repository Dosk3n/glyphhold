"""Private snapshot replay; publish only anonymized counts, never bodies/chat text."""

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.v2 import core
from scripts.diagnose_prefetch import fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-snapshot", type=Path, required=True)
    parser.add_argument(
        "--private-output",
        type=Path,
        help="Optional raw question/title metadata; keep outside the repository",
    )
    args = parser.parse_args()
    snapshot_path = args.memory_snapshot
    snapshot = json.loads(snapshot_path.read_text())
    lock = json.loads(Path("evaluations/prefetch/candidate-lock.json").read_text())
    source = subprocess.check_output(["git", "show", lock["baseline_commit"] + ":app/v2/core.py"])
    assert hashlib.sha256(source).hexdigest() == lock["baseline_core_sha256"]
    with tempfile.TemporaryDirectory(prefix="gh-replay-source-") as directory:
        path = Path(directory) / "core.py"
        path.write_bytes(source)
        spec = importlib.util.spec_from_file_location("gh_replay_original", path)
        baseline = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = baseline
        spec.loader.exec_module(baseline)
    related_titles = {
        19922: ["Loki log query method for home lab", "Hermes native Home Assistant integration"],
        19952: [
            "Hermes native Home Assistant integration",
            "Front of house LED evening and morning schedule",
        ],
        19962: ["Hermes native Home Assistant integration"],
        19981: ["UniFi gateway dBox-Network"],
    }
    outcomes = []
    private_outcomes = []
    with fixture(snapshot=snapshot) as (p, _):
        for index, event in enumerate(snapshot["history"]):
            targets = {
                m["id"]
                for m in snapshot["memories"]
                if m["title"] in related_titles.get(event["message_id"], [])
            }
            with patch("app.v2.core.search", baseline.search):
                started = time.perf_counter()
                old = core.search(p, event["query"], recall=True, limit=5, max_chars=2400)
                old_ms = (time.perf_counter() - started) * 1000
            started = time.perf_counter()
            new = core.search(p, event["query"], recall=True, limit=5, max_chars=2400)
            new_ms = (time.perf_counter() - started) * 1000
            original_ids = [m["id"] for m in event["logged_context"]["memories"]]
            old_ids = [m["id"] for m in old["results"]]
            new_ids = [m["id"] for m in new["results"]]
            framekeep = {m["id"] for m in snapshot["memories"] if "Framekeep" in m["title"]}
            outcomes.append(
                {
                    "example": index + 1,
                    "baseline_matches_recorded": old_ids == original_ids,
                    "baseline_count": len(old_ids),
                    "candidate_count": len(new_ids),
                    "baseline_framekeep": bool(set(old_ids) & framekeep),
                    "candidate_framekeep": bool(set(new_ids) & framekeep),
                    "related_targets": len(targets),
                    "baseline_related_found": len(targets & set(old_ids)),
                    "candidate_related_found": len(targets & set(new_ids)),
                    "baseline_local_ms": round(old_ms, 3),
                    "candidate_local_ms": round(new_ms, 3),
                }
            )
            private_outcomes.append(
                {
                    "query": event["query"],
                    "baseline": [
                        {"title": m["title"], "truncated": m.get("truncated", False)}
                        for m in old["results"]
                    ],
                    "candidate": [
                        {"title": m["title"], "truncated": m.get("truncated", False)}
                        for m in new["results"]
                    ],
                }
            )
    output = {
        "memory_count": len(snapshot["memories"]),
        "cases": len(outcomes),
        "baseline_matches_recorded": sum(r["baseline_matches_recorded"] for r in outcomes),
        "baseline_related_found": sum(r["baseline_related_found"] for r in outcomes),
        "candidate_related_found": sum(r["candidate_related_found"] for r in outcomes),
        "related_total": sum(r["related_targets"] for r in outcomes),
        "retrieval_source_sha256": hashlib.sha256(
            Path("app/v2/retrieval.py").read_bytes()
        ).hexdigest(),
        "scope": "Selected known-related contexts, not independently adjudicated answer accuracy.",
        "measurements": outcomes,
    }
    Path("evaluations/prefetch/candidate-real-replay.json").write_text(
        json.dumps(output, indent=2) + "\n"
    )
    if args.private_output:
        if args.private_output.resolve().is_relative_to(Path.cwd().resolve()):
            raise ValueError("Raw replay metadata must remain outside the repository")
        fd = os.open(args.private_output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as output_file:
            json.dump(private_outcomes, output_file, indent=2)
    del sys.modules[spec.name]
    print(json.dumps({k: v for k, v in output.items() if k != "measurements"}))


if __name__ == "__main__":
    main()
