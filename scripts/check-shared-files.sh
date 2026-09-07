#!/bin/bash
# check-shared-files.sh — validate explicit cross-skill runtime/reference manifests.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$REPO_ROOT" ]; then
  echo "Error: not in a git repository" >&2
  exit 1
fi

PYTHON_BIN=""
for candidate in python3 python py; do
  if "$candidate" -c "" >/dev/null 2>&1; then
    PYTHON_BIN="$candidate"
    break
  fi
done
if [ -z "$PYTHON_BIN" ]; then
  echo "FAIL: Python 3 is required (tried python3, python, and py)" >&2
  exit 1
fi

echo "Shared File Governance Check"
echo "============================"
"$PYTHON_BIN" "$REPO_ROOT/scripts/sync-shared-assets.py" check
"$PYTHON_BIN" "$REPO_ROOT/scripts/shared-references.py" check \
  --runtime-manifest "$REPO_ROOT/scripts/shared-assets.json"
"$PYTHON_BIN" "$REPO_ROOT/scripts/check-reference-similarity.py" --root "$REPO_ROOT"
"$PYTHON_BIN" "$REPO_ROOT/scripts/check-agent-reference-consumers.py" --root "$REPO_ROOT"
"$PYTHON_BIN" "$REPO_ROOT/scripts/check-short-analysis-scope.py" --root "$REPO_ROOT"
echo "All declared shared files are consistent; no unmanaged exact or near-identical reference copies found."
