# GH2 software supply chain review — 18 October 2026

Scope: Python, browser dependencies, bundled Codex/Bitwarden CLIs, Docker build and
GitHub workflows. The dashboard is intended to sit behind Authelia; API endpoints
are public and still require application authentication.

## Verified findings and changes

- The previous final image copied the Node image's entire global module directory,
  including an unused npm installation. OSV found nine affected package versions in
  that unused tree. The final image now copies only a dedicated integrity-locked
  CLI dependency tree, without npm.
- Official Codex CLI remains 0.163.0 and official Bitwarden CLI remains 2026.10.0.
  `cli-tools/package-lock.json` locks transitive artifacts and npm verifies their
  integrity with `npm ci --omit=dev --ignore-scripts`.
- Python's 26 application dependencies are pinned in `requirements.lock` with
  hashes for published non-yanked artifacts. These are the versions from the
  previously tested Python 3.12 image; package functionality was not deliberately
  upgraded. Build dependencies have a separate hashed lock. Docker verifies hashes,
  installs the local application without dependency re-resolution/build isolation,
  checks dependency consistency, and removes pip/setuptools/wheel/packaging afterward.
- Node 22 and Python 3.12 base images are pinned to reviewed multiarchitecture
  manifest digests. Workflow actions are pinned to the commits their official
  version tags referenced during this review. Dependabot checks action, image,
  browser and CLI dependency updates weekly; changes still need review and tests.
- Publication requires the same reusable verification workflow as CI. Publish token
  permissions are limited to the publishing job. Builds produce SBOM/provenance.
- CI now audits packages inventoried from the exact final image, not merely the
  host environment/frontend lock, and smoke-tests both bundled CLI entrypoints.
  New advisory findings, expired exceptions, missing CLI inventory, package
  installers in the runtime, and incomplete/unavailable OSV responses fail the gate.

## Remaining upstream Bitwarden dependency advisories

These are present in the latest official CLI and are not claimed fixed:

| Dependency | Advisory | Exposure assessment |
| --- | --- | --- |
| tmp 0.0.33 | GHSA-52f5-9888-hmc6; GHSA-ph9p-34f9-6g65 | Local temporary-file/helper risks. GH2 uses noninteractive commands rather than an interactive external editor. |
| multer 2.3.0 | GHSA-3pph-fpjx-jg34 | Aborted HTTP-upload disk exhaustion. GH2 never starts `bw serve` or exposes multer's upload handler. |
| node-forge 1.4.0 | GHSA-86w9-cpqp-85rv | RSA signature verification weakness. No fixed upstream version was published at review time; the vulnerable path has not been established in GH2's CLI flows. |

These findings are version/advisory-specific exceptions in
`scripts/supply_chain_exceptions.json`, expiring **18 November 2026**. This is a
qualified, temporary upstream risk record, not proof that every affected code path
is unreachable. No manually modified cryptographic library or forced incompatible
Bitwarden dependency override was introduced. Revisit upstream releases before
production exposure, and whenever the CLI or its usage changes.

The API does not gain a public multer endpoint merely because the CLI includes
multer. Conversely, dashboard protection by Authelia does not resolve a CLI's
supply-chain risk or replace independent API authentication.

## Validation and maintenance

Completed before the combined image rebuild:

- Frontend `npm audit`: zero known vulnerabilities.
- Previously installed Python application libraries: zero known vulnerabilities.
  The old image's pip 25.0.1 had installer advisories; it is removed from runtime.
- Python 3.12 downloaded all 29 runtime/build packages using the hashed locks.
- Build lock advisory audit: zero known vulnerabilities.
- Locked CLI install with lifecycle scripts disabled succeeds; both version
  entrypoints report the expected official versions.
- Ruff passes for `scripts/gh2_supply_chain_audit.py`.

After building the combined image, run:

```sh
python3 scripts/gh2_supply_chain_audit.py glyphhold:gh2-local-test --report /tmp/gh2-security-final-supply-chain.json
docker run --rm --entrypoint codex glyphhold:gh2-local-test --version
docker run --rm -e BITWARDENCLI_APPDATA_DIR=/tmp/bw --entrypoint bw glyphhold:gh2-local-test --version
```

The final image audit inventories Python metadata and installed npm package
manifests in a disposable container with networking disabled; only the host sends
public package identifiers/version numbers to OSV. It does not mount the GH2 data
volume or inspect application credentials.

Dependency locks are build inputs. When changing Python requirements, regenerate
all exact transitive pins and hashes using Python 3.12, review the resulting
artifacts against PyPI, audit them, and test the image; do not simply loosen a pin
or bypass hash checking. The local package install's `pip check` prevents a changed
project requirement silently disagreeing with the lock. Both supported CPU
architectures require release validation; this local review exercises amd64.

This review does not claim an operating-system vulnerability scan was completed.
The package gate covers Python/npm advisories; base-image Debian packages and
native CLI binaries need image/OS scanning as a separate release check.
