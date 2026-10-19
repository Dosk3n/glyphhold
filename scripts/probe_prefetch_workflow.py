"""Read-only synthetic workflow protocol for independent agent evaluation.

Accept one JSON request on stdin: initial, search, or get. Only initial includes
the question/context; expected-answer labels are never returned. Actions are
logged separately for reproducibility. Every call recreates the same fixture.
"""

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.v2 import core
from scripts.diagnose_prefetch import fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    bundle = json.loads(args.bundle.read_text())
    request = json.load(sys.stdin)
    case = next(c for c in bundle["cases"] if c["id"] == request["id"])
    with fixture(memories=bundle["memories"]) as (principal, _):
        action = request["action"]
        if action == "initial":
            function = core.search
            if bundle["policy"] == "baseline":
                source = subprocess.check_output([
                    "git", "show", bundle["baseline_commit"] + ":app/v2/core.py",
                ])
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "baseline.py"
                    path.write_bytes(source)
                    spec = importlib.util.spec_from_file_location("probe_baseline", path)
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[spec.name] = module
                    spec.loader.exec_module(module)
                    function = module.search
            with patch("app.v2.core.search", function):
                output = {
                    "question": case["query"], "history": case.get("history"),
                    "space": case.get("space_id", "space_personal"),
                    "prefetch": core.search(
                        principal, case["query"], recall=True, limit=5, max_chars=2400,
                        space_id=case.get("space_id", "space_personal"),
                    ),
                }
        elif action == "search":
            output = core.search(
                principal, request["query"], space_id=case.get("space_id", "space_personal"),
                broaden=request.get("broaden", False), limit=8, max_chars=16000,
            )
        elif action == "get":
            output = core.get_memory(principal, request["memory_id"])
        else:
            raise ValueError("Unknown action")
        with args.bundle.with_suffix(".actions.jsonl").open("a") as log:
            log.write(json.dumps({"request": request, "response": output}) + "\n")
        print(json.dumps(output))


if __name__ == "__main__":
    main()
