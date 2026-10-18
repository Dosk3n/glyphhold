"""Audit exact Python/npm packages in a disposable final image against OSV.

Run: python scripts/gh2_supply_chain_audit.py glyphhold:gh2-local-test
No credentials or application data are read. New findings fail closed; upstream
exceptions match exact package versions and advisory IDs and expire explicitly.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import urllib.request
from pathlib import Path

INVENTORY = r'''
import importlib.metadata as metadata,json,pathlib
packages=[{"ecosystem":"PyPI","name":d.metadata["Name"],"version":d.version} for d in metadata.distributions() if d.metadata["Name"].lower() != "glyphhold"]
for path in pathlib.Path("/opt/glyphhold-tools/node_modules").rglob("package.json"):
    try:
        data=json.loads(path.read_text())
    except (ValueError,OSError):
        continue
    if data.get("name") and data.get("version"):
        packages.append({"ecosystem":"npm","name":data["name"],"version":data["version"]})
print(json.dumps(packages))
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    packages = json.loads(subprocess.check_output(
        ["docker", "run", "--rm", "--network=none", "--entrypoint", "python",
         args.image, "-c", INVENTORY], text=True, timeout=90,
    ))
    packages = list({(p["ecosystem"], p["name"], p["version"]): p for p in packages}.values())
    installed = {(p["ecosystem"], p["name"]) for p in packages}
    if not {("npm", "@openai/codex"), ("npm", "@bitwarden/cli")}.issubset(installed):
        raise RuntimeError("Final image is missing the expected bundled CLI inventory")
    if ("npm", "npm") in installed or ("PyPI", "pip") in installed:
        raise RuntimeError("Final image unnecessarily includes a package installer")
    exceptions = json.loads((Path(__file__).parent / "supply_chain_exceptions.json").read_text())
    today = dt.datetime.now(dt.UTC).date()
    findings = []
    for offset in range(0, len(packages), 200):
        batch = packages[offset:offset + 200]
        queries = [{"package": {"ecosystem": p["ecosystem"], "name": p["name"]},
                    "version": p["version"]} for p in batch]
        request = urllib.request.Request(
            "https://api.osv.dev/v1/querybatch", data=json.dumps({"queries": queries}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            results = json.load(response)["results"]
        if len(results) != len(batch):
            raise RuntimeError("OSV returned an incomplete result set")
        for package, result in zip(batch, results, strict=True):
            for vulnerability in result.get("vulns", []):
                advisory = vulnerability["id"]
                exception = next((e for e in exceptions if
                    all(e[k] == package[k] for k in ("ecosystem", "name", "version"))
                    and advisory in e["advisories"]
                    and dt.date.fromisoformat(e["expires"]) >= today), None)
                findings.append({**package, "advisory": advisory,
                                 "exception": exception["reason"] if exception else None})
    report = {"packages": len(packages), "findings": findings,
              "unaccepted": sum(f["exception"] is None for f in findings)}
    print(json.dumps(report, indent=2))
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    return int(bool(report["unaccepted"]))


if __name__ == "__main__":
    raise SystemExit(main())
