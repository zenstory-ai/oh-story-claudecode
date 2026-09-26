#!/usr/bin/env bash
# Synthetic tests for the ZCode 3.3.4 strict hook contract.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
# 细纲须写了内容（不计 # 号和空白 ≥30 字）写正文守卫才放行；空文件会被当成空细纲拦下。
write_outline() { printf '%s\n' '# 细纲' '江晨在雨夜推开旧书店的门，发现柜台后坐着失踪三年的师父，两人对视良久。' > "$1"; }

SOURCE="$REPO_ROOT/skills/story-setup/references/zcode/hooks/story_zcode_hook.js"
SOURCE_CORE="$REPO_ROOT/skills/story-setup/references/zcode/hooks/story_hook_core.js"
ROOT="$TMP_DIR/project"
HOOK="$ROOT/.zcode/hooks/story_zcode_hook.js"
mkdir -p "$ROOT/.zcode/hooks"
cp "$SOURCE" "$HOOK"
cp "$SOURCE_CORE" "$ROOT/.zcode/hooks/story_hook_core.js"

run_hook() {
  local event="$1" payload="$2"
  (cd "$ROOT" && printf '%s' "$payload" | ZCODE_PROJECT_DIR="$ROOT" node "$HOOK" "$event")
}

assert_empty() {
  [ -z "$1" ] || fail "$2 expected empty stdout, got: $1"
}

assert_contract() {
  local output="$1" event="$2" label="$3"
  printf '%s' "$output" | python3 -c '
import json, sys
obj = json.loads(sys.stdin.buffer.read().decode("utf-8"))
assert set(obj) == {"hookSpecificOutput"}, obj
specific = obj["hookSpecificOutput"]
allowed = {"hookEventName", "additionalContext"}
if sys.argv[1] == "PreToolUse":
    allowed |= {"permissionDecision", "permissionDecisionReason", "updatedInput"}
assert set(specific) <= allowed, specific
assert specific["hookEventName"] == sys.argv[1], specific
' "$event" || fail "$label violates strict ZCode output contract: $output"
}

assert_denied() {
  assert_contract "$1" PreToolUse "$2"
  printf '%s' "$1" | python3 -c 'import json,sys; x=json.load(sys.stdin)["hookSpecificOutput"]; assert x["permissionDecision"]=="deny" and x["permissionDecisionReason"]' \
    || fail "$2 did not deny"
}

write_clean_state() {
  mkdir -p "$1/追踪"
  printf '{"schema_version":4,"state_revision":0,"last_committed_chapter":%s}\n' "${2:-0}" > "$1/追踪/_tracking-state.json"
  printf '%s\n' '> 状态修订：0' > "$1/追踪/上下文.md"
}

echo "ZCode hook synthetic tests"
echo "=========================="
echo "Fixture: $ROOT"

mkdir -p "$ROOT/book/正文" "$ROOT/book/大纲" "$ROOT/book/设定"
out="$(run_hook pre-tool-prose-guard '{"hook_event_name":"PreToolUse","tool_name":"Write","tool_input":{"file_path":"book/正文/第001章_开端.md"}}')"
assert_denied "$out" "long prose without outline"
write_outline "$ROOT/book/大纲/细纲_第1章.md"
out="$(run_hook pre-tool-prose-guard '{"tool_name":"Write","tool_input":{"file_path":"book/正文/第001章_开端.md"}}')"
assert_denied "$out" "long prose without tracking metadata"
printf '%s' "$out" | grep -q '_tracking-state.json 缺失' || fail "missing tracking denial did not explain re-import/init: $out"
write_clean_state "$ROOT/book"
# 细纲文件在但是空的（只有标题）：照拦，并说清是细纲空了、该补什么。
printf '%s\n' '# 第1章 细纲' '## 目标情绪' > "$ROOT/book/大纲/细纲_第1章.md"
out="$(run_hook pre-tool-prose-guard '{"tool_name":"Write","tool_input":{"file_path":"book/正文/第001章_开端.md"}}')"
assert_denied "$out" "long prose with an empty outline"
printf '%s' "$out" | grep -q '细纲（book/大纲/细纲_第1章.md）是空的' || fail "empty-outline denial must say the outline is empty: $out"
write_outline "$ROOT/book/大纲/细纲_第1章.md"
out="$(run_hook pre-tool-prose-guard '{"tool_name":"Write","tool_input":{"file_path":"book/正文/第001章_开端.md"}}')"
assert_empty "$out" "long prose with outline"

# 新书还没有大纲/追踪/设定脚手架时也必须 fail closed；相对目标按 hook cwd 解析，
# 不能为了掩盖错误的项目根拼接而把核心守卫削成 fail open。
mkdir -p "$ROOT/bare/正文" "$ROOT/cwd-book/正文" "$ROOT/cwd-book/大纲"
out="$(run_hook pre-tool-prose-guard '{"tool_name":"Write","tool_input":{"file_path":"bare/正文/第1章_首章.md"}}')"
assert_denied "$out" "bare long project without scaffolding"
relative_payload="$(node -e '
const path = require("path")
process.stdout.write(JSON.stringify({
  cwd: path.resolve(process.argv[1]),
  tool_name: "Write",
  tool_input: { file_path: "正文/第8章_相对.md" },
}))
' "$ROOT/cwd-book")"
out="$(run_hook pre-tool-prose-guard "$relative_payload")"
assert_denied "$out" "relative prose target from hook cwd"
printf '%s' "$out" | grep -q 'cwd-book/大纲' || fail "relative target was not resolved from hook cwd: $out"
write_outline "$ROOT/cwd-book/大纲/细纲_第8章.md"
out="$(run_hook pre-tool-prose-guard "$relative_payload")"
assert_denied "$out" "relative prose target without tracking metadata"
write_clean_state "$ROOT/cwd-book" 7
out="$(run_hook pre-tool-prose-guard "$relative_payload")"
assert_empty "$out" "relative prose target with cwd-local outline"

: > "$ROOT/book/正文/第009章_已存在.md"
printf '%s\n' '{"schema_version":4,"state_revision":1,"last_committed_chapter":0}' > "$ROOT/book/追踪/_tracking-state.json"
out="$(run_hook pre-tool-prose-guard '{"tool_name":"Write","tool_input":{"file_path":"book/正文/第009章_已存在.md"}}')"
assert_denied "$out" "existing prose rewrite with mismatched derived state"
printf '%s' "$out" | grep -q 'mode=revision 事务重建派生视图' || fail "state mismatch denial missed retry action: $out"
write_clean_state "$ROOT/book"

# containment 判据必须按 Windows 路径语义覆盖：path.relative 跨盘会返回绝对路径，
# 目录名恰好以 `..` 开头则仍在项目内。只用 startsWith("..") 会把两者同时判反。
node - "$SOURCE" <<'JS' || fail "ZCode cwd containment is not cross-volume safe"
const path = require("path")
const { isPathInside } = require(process.argv[2])
if (isPathInside("C:\\repo", "D:\\elsewhere", path.win32)) {
  throw new Error("different Windows volume must be outside the project")
}
if (!isPathInside("C:\\repo", "C:\\repo\\..draft", path.win32)) {
  throw new Error("an in-project directory named ..draft must remain inside")
}
if (!isPathInside("C:\\repo", "C:\\repo\\sub", path.win32)) {
  throw new Error("ordinary in-project directory must remain inside")
}
JS

out="$(run_hook pre-tool-prose-guard '{"tool_name":"ApplyPatch","tool_input":{"patch":"*** Begin Patch\n*** Add File: book/正文/第002章_新局.md\n+正文\n*** End Patch"}}')"
assert_denied "$out" "ApplyPatch prose without outline"
out="$(run_hook pre-tool-prose-guard '{"tool_name":"Bash","tool_input":{"command":"echo x | tee book/正文/第003章_命令.md"}}')"
assert_denied "$out" "Bash prose write without outline"
out="$(run_hook pre-tool-prose-guard '{"tool_name":"Bash","tool_input":{"command":"grep -n book/正文/第003章_命令.md notes.md"}}')"
assert_empty "$out" "Bash mention without write"

mkdir -p "$ROOT/short"
: > "$ROOT/short/设定.md"
out="$(run_hook pre-tool-prose-guard '{"tool_name":"Write","tool_input":{"file_path":"short/正文.md"}}')"
assert_denied "$out" "short prose without outline"
: > "$ROOT/short/小节大纲.md"
out="$(run_hook pre-tool-prose-guard '{"tool_name":"Write","tool_input":{"file_path":"short/正文.md"}}')"
assert_empty "$out" "short prose with outline"

mkdir -p "$ROOT/impbook/正文" "$ROOT/拆文库/impbook"
out="$(run_hook pre-tool-prose-guard '{"tool_name":"Write","tool_input":{"file_path":"impbook/正文/第1章_导入.md"}}')"
assert_empty "$out" "story-import long migration"
mkdir -p "$ROOT/impbook/大纲" "$ROOT/impbook/追踪"
write_outline "$ROOT/impbook/大纲/细纲_第2章.md"
printf '%s\n' '{"schema_version":4,"state_revision":1,"last_committed_chapter":1}' > "$ROOT/impbook/追踪/_tracking-state.json"
printf '%s\n' '> 状态修订：0' > "$ROOT/impbook/追踪/上下文.md"
out="$(run_hook pre-tool-prose-guard '{"tool_name":"Write","tool_input":{"file_path":"impbook/正文/第2章_导入后续.md"}}')"
assert_denied "$out" "imported project must not permanently bypass invalid tracking guard"
echo "  OK outline-before-prose guard"

printf '这是正文里的 TODO，而且最后一句被截断' > "$ROOT/short/正文.md"
out="$(run_hook post-tool-prose-check '{"hook_event_name":"PostToolUse","tool_name":"Write","tool_input":{"file_path":"short/正文.md"}}')"
assert_contract "$out" PostToolUse "post-write prose check"
printf '%s' "$out" | grep -q '占位符' || fail "post-write check missed TODO"
printf '%s' "$out" | grep -q '疑似截断' || fail "post-write check missed truncation"
echo "  OK post-write strict JSON + UTF-8 findings"

printf '命令写入的正文 TODO。' > "$ROOT/short/正文.md"
out="$(run_hook post-tool-prose-check '{"hook_event_name":"PostToolUse","tool_name":"Bash","tool_input":{"command":"cat input.txt > short/正文.md"}}')"
assert_contract "$out" PostToolUse "post-bash prose check"
printf '%s' "$out" | grep -q '占位符' || fail "post-Bash check missed prose target"
echo "  OK Bash write post-check"

cat > "$ROOT/.story-deployed" <<'EOF'
agents_version: 19
setup_skill_version: 1.2.9
target_cli: zcode
resolver_strategy: project-local-skill-reference
references_dir: .zcode/skills/story-setup/references/agent-references
EOF
printf 'book\n' > "$ROOT/.active-book"
mkdir -p "$ROOT/book/追踪"
printf '# 上下文\n' > "$ROOT/book/追踪/上下文.md"
out="$(run_hook session-start '{"hook_event_name":"SessionStart","source":"compact"}')"
assert_contract "$out" SessionStart "session start"
printf '%s' "$out" | grep -q '当前书目' || fail "session start missed active book"
printf '%s\n' '{"schema_version":4,"state_revision":1,"last_committed_chapter":0}' > "$ROOT/book/追踪/_tracking-state.json"
out="$(run_hook session-start '{"hook_event_name":"SessionStart","source":"resume"}')"
assert_contract "$out" SessionStart "session tracking mismatch warning"
printf '%s' "$out" | grep -q '状态修订' || fail "session start missed tracking revision mismatch"
write_clean_state "$ROOT/book"
echo "  OK session-start context"

printf '# 旧上下文\n' > "$ROOT/book/追踪/上下文.md"
sleep 2
printf '# 第1章\n正文。\n' > "$ROOT/book/正文/第001章_撞名.md"
printf '# 第2章\n正文。\n' > "$ROOT/book/正文/第002章_撞名.md"
out="$(run_hook session-start '{"hook_event_name":"SessionStart","source":"resume"}')"
assert_contract "$out" SessionStart "session continuity"
printf '%s' "$out" | grep -q '续写状态卡更早' || fail "session start missed stale tracking context"
printf '%s' "$out" | grep -q '标题重复' || fail "session start missed duplicate chapter title"
echo "  OK session-start continuity guard"

git -C "$ROOT" init -q
git -C "$ROOT" config user.email zcode-hook@example.invalid
git -C "$ROOT" config user.name zcode-hook-test
printf '年龄：18\n' > "$ROOT/book/正文/第010章_属性.md"
git -C "$ROOT" add "$ROOT/book/正文/第010章_属性.md"
out="$(run_hook pre-tool-commit-advisory '{"tool_name":"Bash","tool_input":{"command":"git -C . commit -m test"}}')"
assert_contract "$out" PreToolUse "commit advisory"
printf '%s' "$out" | grep -q '硬编码角色属性' || fail "commit advisory missed staged prose"
out="$(run_hook pre-tool-commit-advisory '{"tool_name":"Bash","tool_input":{"command":"echo git commit docs"}}')"
assert_empty "$out" "non-commit command"
echo "  OK commit advisory"

out="$(printf 'not-json' | ZCODE_PROJECT_DIR="$ROOT" node "$HOOK" pre-tool-prose-guard)"
assert_empty "$out" "malformed input fail-open"

write_outline "$ROOT/book/大纲/细纲_第8章.md"
write_clean_state "$ROOT/book" 7
out="$(cd "$TMP_DIR" && printf '%s' '{"tool_name":"Write","tool_input":{"file_path":"book/正文/第8章_自定位.md"}}' | env -u ZCODE_PROJECT_DIR -u CLAUDE_PROJECT_DIR node "$HOOK" pre-tool-prose-guard)"
assert_empty "$out" "deployed __dirname self-location"
echo "  OK malformed input + workspace self-location"

echo ""
echo "OK: ZCode hook synthetic tests passed"
