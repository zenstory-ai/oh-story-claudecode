#!/bin/bash
# graph-update-check.sh — PostToolUse 正文落盘后检测知识图谱更新
# 设计: 薄壳，业务逻辑在 story_graph_core.js::checkGraphUpdate()
set -euo pipefail
export LC_ALL=C

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"

node -e "" >/dev/null 2>&1 || exit 0
CLI="$HOOK_DIR/story_graph_cli.js"
[ -f "$CLI" ] || exit 0

# 从 hook input 提取目标文件路径
TARGET=""
HOOK_INPUT="${CLAUDE_TOOL_INPUT:-}"
if [ -z "$HOOK_INPUT" ] && [ ! -t 0 ]; then
  HOOK_INPUT="$(cat)"
fi

if [ -n "$HOOK_INPUT" ]; then
  TARGET=$(printf '%s' "$HOOK_INPUT" | grep -o '"file_path"[[:space:]]*:[[:space:]]*"[^"]*"' 2>/dev/null | head -1 | sed 's/.*"\([^"]*\)"$/\1/' || true)
  [ -z "$TARGET" ] && TARGET=$(printf '%s' "$HOOK_INPUT" | grep -o '"filePath"[[:space:]]*:[[:space:]]*"[^"]*"' 2>/dev/null | head -1 | sed 's/.*"\([^"]*\)"$/\1/' || true)
fi

[ -z "$TARGET" ] && exit 0

node "$CLI" prose-check _ "$TARGET" "$ROOT" 2>/dev/null || true
