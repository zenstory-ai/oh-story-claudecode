#!/bin/sh
### story-hooks: BEGIN ###
# story project commit validation (advisory only, never blocks)
# Managed by story-setup -- do not edit this block manually
(
set -eu
command -v node >/dev/null 2>&1 || exit 0
ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
CORE="$ROOT/.opencode/plugins/lib/story_hook_core.js"
[ -f "$CORE" ] || exit 0
node -e 'const w = require(process.argv[1]).stagedMarkdownWarnings(process.argv[2]); if (w) process.stdout.write(w + "\n");' "$CORE" "$ROOT"
) || true
### story-hooks: END ###
