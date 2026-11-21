#!/usr/bin/env bash
# Project-local Claude Code hook launcher (pure ASCII for GBK/non-UTF-8 locale safety).
# Routes all 8 Claude Code hook events to story_hook_cli.js (backed by story_hook_core.js).
set -euo pipefail

EVENT="${1:-}"
case "$EVENT" in
  session-start|detect-story-gaps|session-end|pre-compact|post-compact|pre-tool-prose-guard|pre-tool-commit-advisory|post-tool-prose-check) ;;
  *) exit 2 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLI="$SCRIPT_DIR/story_hook_cli.js"

if ! node -e "" >/dev/null 2>&1; then
  if [ "$EVENT" = "session-start" ]; then
    printf '%s\n' "[WARN] Node.js 18+ not found on PATH: oh-story hooks are disabled. Install Node.js 18+ (https://nodejs.org) and open a new session."
  elif [ "$EVENT" = "pre-tool-prose-guard" ]; then
    printf '%s\n' "[WARN] Node.js 18+ not found on PATH: prose guard failed open; install Node.js 18+ and open a new session." >&2
  fi
  exit 0
fi

if [ ! -f "$CLI" ] || [ ! -f "$SCRIPT_DIR/story_hook_core.js" ]; then
  if [ "$EVENT" = "session-start" ]; then
    printf '%s\n' "[WARN] oh-story hook runtime missing (story_hook_cli.js / story_hook_core.js). Re-run /story-setup to restore .claude/hooks/."
  fi
  exit 0
fi

exec node "$CLI" "$EVENT"
