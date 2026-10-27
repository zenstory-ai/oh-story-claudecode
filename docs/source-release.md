# Source release

This repository publishes a tracked-source archive through the reviewed shared
ZenStory source-release controls. The procedure binds a stable tag to reviewed
source, successful CI and public release assets.

## Contract

- `.release/policy.json` is source-bound and names every version authority, the
  dated changelog, exact installable files, exclusions, and exact main CI jobs.
- Required dashboard checks are `api (ubuntu-latest)`, `api (macos-latest)`,
  `api (windows-latest)` and `e2e (ubuntu)`. The dashboard workflow runs on every
  push to `main`, including documentation-only commits, so every releasable SHA
  has its own results. Pull requests retain path filtering.
- Pull requests run a read-only contract/archive validation.
- `workflow_dispatch` is allowed only on `main` and never publishes. It also
  proves the exact main commit's configured CI runs.
- Only a stable `vX.Y.Z` tag push whose version and dated changelog agree can
  publish. The tag commit must be on protected `main` with successful exact-SHA
  CI. Assets are append-only; a same-name byte mismatch fails rather than
  overwriting.
- After GitHub source assets pass anonymous byte verification, a separate job
  dispatches the existing ClawHub workflow with the exact tag and 40-character
  source SHA. `CLAWHUB_QUEUED` means dispatch accepted, not published or
  scan-clean.

## Release procedure

1. Update all version authorities together and add a dated changelog heading.
2. Merge through the existing product and ClawHub inventory checks.
3. Run **Source release** manually on `main` as a nonpublishing dry-run.
4. Create the reviewed stable tag from that exact green main commit and push it.
5. Inspect the source-release manifest, anonymous asset verification, and the
   ClawHub audit separately. Never infer ClawHub success from the dispatch job.

## Safe reruns and failures

Rerun the same workflow attempt only after diagnosing the failing channel. An
already uploaded asset is accepted only when its public bytes match the same
candidate; no workflow deletes, replaces, or `--clobber`s release assets. A
GitHub API/auth/network error is a failure, not proof that an asset is absent. A
ClawHub handoff can be re-dispatched for the same exact tag/source, while its
existing ownership, rights, version/hash, scan and anonymous-audit gates remain
authoritative.

The caller currently pins shared source controls to `d098c09a27f8fe58ccf3a13a894ecc3804747b7c`.
When upgrading controls, change all four references together and pass the
source-bound pin contract before merging. The separate ClawHub writer pin is
unchanged and remains independently reviewed.
