"""Compare a frozen recall candidate against Git's original core, without deployment."""

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.evaluate_prefetch import evaluate


def main():
    directory = Path("evaluations/prefetch")
    lock = json.loads((directory / "candidate-lock.json").read_text())
    assert (
        hashlib.sha256(Path("app/v2/retrieval.py").read_bytes()).hexdigest()
        == lock["retrieval_source_sha256"]
    )
    assert (
        hashlib.sha256((directory / "holdout.json").read_bytes()).hexdigest()
        == lock["holdout_sha256"]
    )
    assert (
        hashlib.sha256((directory / "confirmation.json").read_bytes()).hexdigest()
        == lock["confirmation_sha256"]
    )
    original = json.loads((directory / "corpus.json").read_text())
    sets = {"original": original}
    for name in ["direct", "conversational", "varied"]:
        sets[name] = {
            "memories": original["memories"],
            "cases": json.loads((directory / f"agent_{name}_cases.json").read_text())["cases"],
        }
    sets["holdout"] = json.loads((directory / "holdout.json").read_text())
    sets["confirmation"] = json.loads((directory / "confirmation.json").read_text())
    source = subprocess.check_output(["git", "show", lock["baseline_commit"] + ":app/v2/core.py"])
    assert hashlib.sha256(source).hexdigest() == lock["baseline_core_sha256"]
    summary = {}
    with tempfile.TemporaryDirectory(prefix="gh-original-recall-") as temporary:
        path = Path(temporary) / "core.py"
        path.write_bytes(source)
        spec = importlib.util.spec_from_file_location("gh_original_core", path)
        baseline = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = baseline
        spec.loader.exec_module(baseline)
        try:
            for name, corpus in sets.items():
                with patch("app.v2.core.search", baseline.search):
                    before = evaluate(corpus, Path("../glyphhold-hermes-memory/__init__.py"))
                after = evaluate(corpus, Path("../glyphhold-hermes-memory/__init__.py"))
                for label, report in [("baseline", before), ("candidate", after)]:
                    (directory / f"{label}-{name}.json").write_text(
                        json.dumps(report, indent=2, ensure_ascii=False) + "\n"
                    )
                summary[name] = {
                    "baseline": before["summary"]["hermes_defaults"],
                    "candidate": after["summary"]["hermes_defaults"],
                }
                print(name, json.dumps(summary[name]))
        finally:
            del sys.modules[spec.name]
    (directory / "candidate-comparison.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
