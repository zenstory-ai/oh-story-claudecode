#!/bin/sh
# Project-local Codex hook launcher. hooks.json locates this file; this script owns
# runtime probing and event dispatch so six hook registrations do not duplicate it.
set -eu

EVENT="${1:-}"
case "$EVENT" in
  session-start|pre-tool-prose-guard|pre-tool-commit-advisory|pre-compact|post-compact|stop) ;;
  *) exit 2 ;;
esac

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
HOOK="$SCRIPT_DIR/story_codex_hook.js"
[ -f "$HOOK" ] || exit 0
command -v node >/dev/null 2>&1 || exit 0

CODEX_PROJECT_DIR="$PROJECT_ROOT"; export CODEX_PROJECT_DIR
exec node "$HOOK" "$EVENT"
