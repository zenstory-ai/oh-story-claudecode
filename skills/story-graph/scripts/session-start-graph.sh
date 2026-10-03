#!/bin/bash
# session-start-graph.sh — 会话启动时显示知识图谱状态
# 设计: 薄壳，业务逻辑在 story_graph_core.js::sessionStatus()
set -euo pipefail

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# node 不可用时静默退出
node -e "" >/dev/null 2>&1 || exit 0

CLI="$HOOK_DIR/story_graph_cli.js"
[ -f "$CLI" ] || exit 0

node "$CLI" session-status _ "$ROOT" 2>/dev/null || true
