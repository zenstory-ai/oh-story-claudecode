#!/usr/bin/env bash
# check-claude-adapter.sh — Claude Code marketplace/plugin compatibility checks.
# Static by default; set CLAUDE_REAL_CHECK=1 to invoke the installed Claude CLI.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

fail() { echo "FAIL: $*" >&2; exit 1; }

echo "Claude Code adapter check"
echo "========================="
echo "Repo: $REPO_ROOT"
python3 "$SCRIPT_DIR/check-plugin-packaging.py" --root "$REPO_ROOT"

if [ "${CLAUDE_REAL_CHECK:-0}" = "1" ]; then
  command -v claude >/dev/null 2>&1 \
    || fail "CLAUDE_REAL_CHECK=1 but claude is not on PATH"
  TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ohstory-claude-check.XXXXXX")"
  trap 'rm -rf "$TMP_DIR"' EXIT
  mkdir -p "$TMP_DIR/home" "$TMP_DIR/config" "$TMP_DIR/plugin/.claude-plugin"
  export HOME="$TMP_DIR/home" USERPROFILE="$TMP_DIR/home" CLAUDE_CONFIG_DIR="$TMP_DIR/config"
  echo "  Claude: $(claude --version)"

  # A directory with both manifests is validated as a marketplace by Claude.
  # Validate the real plugin separately so its 13 default-discovered SKILL.md
  # files are parsed, rather than substituting a synthetic component manifest.
  cp "$REPO_ROOT/.claude-plugin/plugin.json" "$TMP_DIR/plugin/.claude-plugin/plugin.json"
  cp -R "$REPO_ROOT/skills" "$TMP_DIR/plugin/skills"
  claude plugin validate --strict "$TMP_DIR/plugin"
  claude plugin validate --strict "$REPO_ROOT/.claude-plugin/marketplace.json"
  echo "  OK Claude CLI strict component and marketplace validation"

  # All three scopes use separate homes/configs and temporary git workspaces.
  python3 "$SCRIPT_DIR/test-claude-plugin-lifecycle.py"
fi

echo "OK: Claude Code adapter checks passed"
