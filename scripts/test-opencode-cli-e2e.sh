#!/usr/bin/env bash
# test-opencode-cli-e2e.sh — real OpenCode 2.x CLI e2e for project-local story setup assets.
#
# 不只查「文件在不在」：插件是否真的被运行时加载（plugin.list 状态 active）、钩子是否真的生效，
# 都在真实 OpenCode 运行时上验证。钩子用 opencode-mock-llm.mjs 驱动——mock 模型发出脚本化的
# 工具调用，断言落盘结果与模型实际收到的工具返回内容。所有查询走后台服务，服务先在项目外的目录
# 拉起（服务进程 cwd != 项目），覆盖插件必须以 ctx.location 而非 process.cwd() 定位项目的回归。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT="$REPO_ROOT/skills/story-setup/references/opencode"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/ohstory-opencode-e2e.XXXXXX")"
TMP_ROOT="$(cd "$TMP_ROOT" && pwd -P)"
CLI_HOME="$TMP_ROOT/home"
PROJECT="$TMP_ROOT/project"
MOCK_LOG="$TMP_ROOT/mock-requests.jsonl"
MOCK_SCRIPT="$TMP_ROOT/mock-script.json"
MOCK_PID=""

fail() { echo "FAIL: $*" >&2; exit 1; }

if ! command -v opencode >/dev/null 2>&1; then
  fail "opencode CLI not found on PATH. Install OpenCode 2.x with: npm install -g @opencode/cli"
fi

run_opencode() {
  HOME="$CLI_HOME" \
    XDG_CONFIG_HOME="$CLI_HOME/.config" \
    XDG_DATA_HOME="$CLI_HOME/.local/share" \
    XDG_CACHE_HOME="$CLI_HOME/.cache" \
    XDG_STATE_HOME="$CLI_HOME/.local/state" \
    command opencode "$@"
}

cleanup() {
  run_opencode service stop >/dev/null 2>&1 || true
  if [ -n "$MOCK_PID" ]; then kill "$MOCK_PID" 2>/dev/null || true; wait "$MOCK_PID" 2>/dev/null || true; fi
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

mkdir -p "$CLI_HOME/.config/opencode"

VERSION="$(run_opencode --version 2>&1 | head -1)"
MAJOR="$(printf '%s\n' "$VERSION" | sed -nE 's/^[^0-9]*([0-9]+)\.[0-9]+\.[0-9]+.*/\1/p')"
[ -n "$MAJOR" ] && [ "$MAJOR" -ge 2 ] || fail "OpenCode 2.x required, got: $VERSION"

echo "OpenCode CLI E2E"
echo "================"
echo "Repo: $REPO_ROOT"
echo "OpenCode: $(command -v opencode) ($VERSION)"

# 后台服务默认监听固定端口；开发机上已有 OpenCode 服务占着它时，隔离 HOME 里的服务起不来、
# 请求会一直重试。先给隔离 HOME 钉一个空闲端口，再在项目外的目录拉起服务，之后所有请求都复用它。
SERVICE_PORT="$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
run_opencode service set port "$SERVICE_PORT" >/dev/null
(cd "$CLI_HOME" && run_opencode api GET /api/info >/dev/null)

# GET 一个 location 作用域的列表接口，等到 data 非空（location 插件异步就绪，首个请求可能为空）。
api_list() {
  local directory="$1" out="$2"; shift 2
  local attempt
  for attempt in $(seq 1 30); do
    if run_opencode api "$@" -H "x-opencode-directory:$directory" >"$out" 2>"$out.err" &&
      python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("data") else 1)' "$out" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  cat "$out" "$out.err" >&2 || true
  fail "OpenCode API returned no data: $*"
}

echo "  Checking repo-local skill discovery"
api_list "$REPO_ROOT" "$TMP_ROOT/repo-skills.json" GET /api/skill
python3 - "$TMP_ROOT/repo-skills.json" "$REPO_ROOT" <<'PY'
import json
import sys
from pathlib import Path

expected = {
    "browser-cdp",
    "story",
    "story-cover",
    "story-deslop",
    "story-import",
    "story-long-analyze",
    "story-long-scan",
    "story-long-write",
    "story-review",
    "story-setup",
    "story-short-analyze",
    "story-short-scan",
    "story-short-write",
}

data = json.loads(Path(sys.argv[1]).read_text())["data"]
repo_root = Path(sys.argv[2]).resolve()
items = {item.get("name") or item.get("id"): item for item in data if isinstance(item, dict)}
missing = sorted(expected - set(items))
if missing:
    raise SystemExit(f"missing OpenCode-discovered story skills: {missing}")
for name in expected:
    location = items[name].get("path")
    if not isinstance(location, str):
        raise SystemExit(f"{name}: OpenCode output omitted skill path")
    actual = Path(location).resolve()
    wanted = (repo_root / "skills" / name / "SKILL.md").resolve()
    if actual != wanted:
        raise SystemExit(f"{name}: expected location {wanted}, got {actual}")
print(f"    OK {len(expected)} story skills discovered")
PY

# 与 story-setup 部署清单一致：不写 opencode.json，插件靠 .opencode/plugins/ 自动发现。
mkdir -p \
  "$PROJECT/.opencode/agents" \
  "$PROJECT/.opencode/commands" \
  "$PROJECT/.opencode/plugins/lib" \
  "$PROJECT/skills/story-setup/references"
cp -R "$ROOT/agents/." "$PROJECT/.opencode/agents/"
cp -R "$ROOT/commands/." "$PROJECT/.opencode/commands/"
cp "$ROOT/plugin.ts" "$PROJECT/.opencode/plugins/story-hooks.ts"
cp "$ROOT/story_hook_core.js" "$PROJECT/.opencode/plugins/lib/story_hook_core.js"
cp "$ROOT/AGENTS.md.tmpl" "$PROJECT/AGENTS.md"
cp -R "$REPO_ROOT/skills/story-setup/references/agent-references" \
  "$PROJECT/skills/story-setup/references/agent-references"
git -C "$PROJECT" init -q

echo "  Checking deployed project plugin/commands/agents"
api_list "$PROJECT" "$TMP_ROOT/plugins.json" plugin.list
api_list "$PROJECT" "$TMP_ROOT/commands.json" GET /api/command
(cd "$PROJECT" && run_opencode debug agents >"$TMP_ROOT/agents.json")
python3 - "$TMP_ROOT" <<'PY'
import json
import sys
from pathlib import Path

tmp = Path(sys.argv[1])
plugins = json.loads((tmp / "plugins.json").read_text())["data"]
commands = json.loads((tmp / "commands.json").read_text())["data"]
agents = json.loads((tmp / "agents.json").read_text())

story = [item for item in plugins if item.get("id") == "oh-story.story-hooks"]
if not story:
    raise SystemExit("story-hooks plugin missing from plugin.list")
status = (story[0].get("state") or {}).get("status")
if status != "active":
    raise SystemExit(f"story-hooks plugin not active: {json.dumps(story[0], ensure_ascii=False)}")
if not str((story[0].get("source") or {}).get("path", "")).endswith("/.opencode/plugins/story-hooks.ts"):
    raise SystemExit(f"story-hooks loaded from unexpected source: {story[0].get('source')}")

expected_commands = {
    "browser-cdp",
    "story",
    "story-cover",
    "story-deslop",
    "story-import",
    "story-long-analyze",
    "story-long-scan",
    "story-long-write",
    "story-review",
    "story-setup",
    "story-short-analyze",
    "story-short-scan",
    "story-short-write",
}
expected_agents = {
    "chapter-extractor",
    "character-designer",
    "consistency-checker",
    "narrative-writer",
    "story-architect",
    "story-explorer",
    "story-researcher",
}
command_ids = {item.get("id") or item.get("name") for item in commands}
missing_commands = sorted(expected_commands - command_ids)
if missing_commands:
    raise SystemExit(f"missing OpenCode commands: {missing_commands}")
by_id = {item.get("id"): item for item in agents}
missing_agents = sorted(expected_agents - set(by_id))
if missing_agents:
    raise SystemExit(f"missing OpenCode agents: {missing_agents}")
for name in expected_agents:
    agent = by_id[name]
    if agent.get("mode") != "subagent":
        raise SystemExit(f"{name}: mode should be subagent, got {agent.get('mode')!r}")
    rules = agent.get("permissions") or []
    if {"action": "*", "resource": "*", "effect": "deny"} not in rules:
        raise SystemExit(f"{name}: native permissions did not load: {rules}")
if "只读" not in by_id["story-explorer"].get("description", ""):
    raise SystemExit("story-explorer description did not load story content")

print(f"    OK story-hooks active, {len(expected_commands)} commands, {len(expected_agents)} agents")
PY

echo "  Checking plugin hooks on the real runtime (mock model)"
MOCK_LOG="$MOCK_LOG" MOCK_SCRIPT="$MOCK_SCRIPT" node "$SCRIPT_DIR/opencode-mock-llm.mjs" >"$TMP_ROOT/mock-port" &
MOCK_PID=$!
MOCK_PORT=""
for _ in $(seq 1 100); do
  MOCK_PORT="$(tr -d '[:space:]' <"$TMP_ROOT/mock-port")"
  [ -n "$MOCK_PORT" ] && break
  sleep 0.1
done
[ -n "$MOCK_PORT" ] || fail "mock model did not start"
cat >"$CLI_HOME/.config/opencode/opencode.json" <<JSON
{
  "\$schema": "https://opencode.ai/config.json",
  "providers": {
    "mock": {
      "name": "Mock",
      "package": "@opencode/ai/providers/openai-compatible",
      "settings": { "baseURL": "http://127.0.0.1:$MOCK_PORT/v1", "apiKey": "fixture" },
      "models": { "probe": { "name": "probe" } }
    }
  }
}
JSON
# 全局配置变更让已运行的服务重新加载，避免沿用上面启动时的空 provider 列表。
run_opencode reload >/dev/null 2>&1 || true

mkdir -p "$PROJECT/book/正文" "$PROJECT/book/大纲" "$PROJECT/book/追踪"
printf '# 上下文\n当前位置\n' >"$PROJECT/book/追踪/上下文.md"
printf 'book\n' >"$PROJECT/.active-book"

# 让 mock 模型按剧本发出一轮工具调用，跑完一次 `opencode run`；日志只保留这一轮的请求。
run_case() {
  local label="$1" calls="$2" pid
  printf '%s\n' "$calls" >"$MOCK_SCRIPT"
  : >"$MOCK_LOG"
  (cd "$PROJECT" && run_opencode run --model mock/probe "$label" >"$TMP_ROOT/run.out" 2>"$TMP_ROOT/run.err") &
  pid=$!
  for _ in $(seq 1 120); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    fail "$label: opencode run timed out"
  fi
  wait "$pid" || { cat "$TMP_ROOT/run.err" >&2; fail "$label: opencode run failed"; }
}

# 断言模型拿到的最后一条工具返回内容匹配给定正则。
assert_tool_result() {
  python3 - "$MOCK_LOG" "$1" "$2" <<'PY'
import json
import re
import sys

log, label, pattern = sys.argv[1:]
rows = [json.loads(line) for line in open(log, encoding="utf-8") if line.strip()]
results = [m for row in rows for m in row["body"].get("messages", []) if m.get("role") == "tool"]
if not results:
    raise SystemExit(f"{label}: model never received a tool result ({len(rows)} requests)")
content = results[-1].get("content")
text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
if not re.search(pattern, text):
    raise SystemExit(f"{label}: tool result did not match {pattern!r}: {text[:600]}")
PY
}

run_case block-write '[{"name":"write","arguments":{"path":"book/正文/第001章_开局.md","content":"正文。"}}]'
[ ! -e "$PROJECT/book/正文/第001章_开局.md" ] || fail "write without outline reached disk"
assert_tool_result block-write '写正文被拦截：第 1 章缺少细纲'

run_case block-shell '[{"name":"shell","arguments":{"command":"printf x > book/正文/第002章_绕过.md","description":"fixture"}}]'
[ ! -e "$PROJECT/book/正文/第002章_绕过.md" ] || fail "shell redirect without outline reached disk"
assert_tool_result block-shell '写正文被拦截[\s\S]*已从 Shell 命令识别到正文写入目标'

run_case block-patch '[{"name":"patch","arguments":{"patchText":"*** Begin Patch\n*** Add File: book/正文/第003章_补丁.md\n+正文。\n*** End Patch\n"}}]'
[ ! -e "$PROJECT/book/正文/第003章_补丁.md" ] || fail "patch without outline reached disk"
assert_tool_result block-patch '写正文被拦截：第 3 章缺少细纲'

printf '# 细纲\n' >"$PROJECT/book/大纲/细纲_第1章.md"
printf '{"schema_version": 4, "state_revision": 0, "last_committed_chapter": 0}\n' >"$PROJECT/book/追踪/_tracking-state.json"
printf '> 状态修订：0\n' >"$PROJECT/book/追踪/上下文.md"
CALLS="$(python3 -c 'import json; print(json.dumps([{"name": "write", "arguments": {"path": "book/正文/第001章_开局.md", "content": "街灯一盏盏亮起。" * 30 + "\nTODO 此处待补"}}], ensure_ascii=False))')"
run_case after-write "$CALLS"
[ -s "$PROJECT/book/正文/第001章_开局.md" ] || fail "outlined write was blocked or not written"
assert_tool_result after-write '正文兜底检测（book/正文/第001章_开局\.md）[\s\S]*占位符'
echo "    OK write/shell/patch blocked without outline; outlined write passes with after-write findings"

SESSION_ID="$(cd "$PROJECT" && run_opencode session list --format json | python3 -c '
import json, sys
data = json.load(sys.stdin)
items = data.get("data", data) if isinstance(data, dict) else data
print(items[0]["id"])')"
: >"$MOCK_LOG"
run_opencode api session.compact --param "sessionID=$SESSION_ID" -d '{}' -H "x-opencode-directory:$PROJECT" >/dev/null
compacted=""
for _ in $(seq 1 60); do
  if grep -q 'Pre-Compact Summary' "$MOCK_LOG" 2>/dev/null; then compacted=1; break; fi
  sleep 1
done
[ -n "$compacted" ] || fail "compaction request never reached the model"
grep -q 'Writing context: book/追踪/上下文.md' "$MOCK_LOG" ||
  fail "compaction hook did not resolve the project from ctx.location"
echo "    OK compaction request carries the writing-context pointer"

echo ""
echo "OK: OpenCode CLI E2E passed"
