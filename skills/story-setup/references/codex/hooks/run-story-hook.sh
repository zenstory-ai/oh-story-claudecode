#!/bin/sh
# Project-local Codex hook launcher. hooks.json locates this file; this script owns
# runtime probing and event dispatch so six hook registrations do not duplicate it.
set -eu

EVENT="${1:-}"
case "$EVENT" in
  session-start|pre-tool-prose-guard|pre-tool-commit-advisory|pre-compact|post-compact|stop) ;;
  *) exit 2 ;;
esac

fail_open() {
  if [ "$EVENT" = "stop" ]; then
    printf '%s' '{"continue":true}'
  fi
  exit 0
}

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
HOOK="$SCRIPT_DIR/story_codex_hook.js"
CORE="$SCRIPT_DIR/story_hook_core.js"
[ -f "$HOOK" ] && [ -f "$CORE" ] || fail_open
command -v node >/dev/null 2>&1 || fail_open

CODEX_PROJECT_DIR="$PROJECT_ROOT"; export CODEX_PROJECT_DIR
exec node "$HOOK" "$EVENT"
