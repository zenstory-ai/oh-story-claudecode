#!/bin/bash
# check-story-setup-deployment.sh — story-setup deployment/runtime regression checks
# Covers hook lib deployment, reference bundle integrity, root-aware hooks,
# short-project non-mutation, commit-hook self-gating, and deployed-behavior anchors.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILL_DIR="$REPO_ROOT/skills/story-setup"
HOOKS_DIR="$SKILL_DIR/references/templates/hooks"
AGENT_REFS_DIR="$SKILL_DIR/references/agent-references"
SKILL_FILE="$SKILL_DIR/SKILL.md"
SETTINGS_FILE="$SKILL_DIR/references/templates/settings-hooks.json"
CLAUDE_MERGE="$SKILL_DIR/scripts/merge-claude-settings.py"
COPY_PATH_SAFETY="$SKILL_DIR/scripts/copy-path-safety.py"
TMP_DIR="$(mktemp -d)"
CURRENT_AGENTS_VERSION="$(node -e 'process.stdout.write(String(require(process.argv[1]).agents_version))' "$SCRIPT_DIR/current-contract.json")"
CURRENT_SETUP_VERSION="$(node -e 'process.stdout.write(String(require(process.argv[1]).setup_skill_version))' "$SCRIPT_DIR/current-contract.json")"
PREVIOUS_AGENTS_VERSION=$((CURRENT_AGENTS_VERSION - 1))
NEXT_AGENTS_VERSION=$((CURRENT_AGENTS_VERSION + 1))

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_file() {
  [ -f "$1" ] || fail "required file missing: $1"
}

assert_grep() {
  local pattern="$1"
  local file="$2"
  local message="$3"
  grep -Eq "$pattern" "$file" || fail "$message ($file)"
}

assert_no_grep() {
  local pattern="$1"
  local file="$2"
  local message="$3"
  if grep -Eq "$pattern" "$file"; then
    fail "$message ($file)"
  fi
}

copy_hooks() {
  local root="$1"
  mkdir -p "$root/.claude"
  cp -R "$HOOKS_DIR" "$root/.claude/hooks"
  chmod +x "$root/.claude/hooks"/*.sh
}

copy_agent_refs() {
  local root="$1"
  mkdir -p "$root/.claude/skills/story-setup/references"
  cp -R "$AGENT_REFS_DIR" "$root/.claude/skills/story-setup/references/agent-references"
}

write_sentinel() {
  local root="$1"
  cat > "$root/.story-deployed" <<SENTINEL
deployed_at: 2026-05-24T00:00:00Z
agents_version: $CURRENT_AGENTS_VERSION
setup_skill_version: $CURRENT_SETUP_VERSION
target_cli: claude-code
resolver_strategy: project-local-skill-reference
references_dir: .claude/skills/story-setup/references/agent-references
SENTINEL
}

run_from_nested() {
  local root="$1"
  local script="$2"
  local nested="$root/nested/a/b"
  mkdir -p "$nested"
  (cd "$nested" && CLAUDE_PROJECT_DIR="$root" bash "$root/.claude/hooks/$script")
}

run_from_nested_no_project_dir() {
  local root="$1"
  local script="$2"
  local nested="$root/nested/a/b"
  mkdir -p "$nested"
  (cd "$nested" && unset CLAUDE_PROJECT_DIR && bash "$root/.claude/hooks/$script")
}

setup_git_repo() {
  local root="$1"
  git -C "$root" init -q
  git -C "$root" config user.email story-setup@example.invalid
  git -C "$root" config user.name story-setup-test
}

run_commit_hook_command() {
  local root="$1"
  local command_text="$2"
  (cd "$root" && CLAUDE_PROJECT_DIR="$root" STORY_COMMIT_COMMAND="$command_text" bash .claude/hooks/validate-story-commit.sh 2>&1 || true)
}

assert_commit_warns() {
  local root="$1"
  local command_text="$2"
  local label="$3"
  local out
  out="$(run_commit_hook_command "$root" "$command_text")"
  echo "$out" | grep -q 'Story Commit Warnings' || fail "validate-story-commit did not warn for $label: $command_text"
  echo "$out" | grep -q '正文硬编码角色属性' || fail "validate-story-commit did not inspect staged markdown for $label"
}

echo "Story setup deployment check"
echo "============================"
echo "Repo: $REPO_ROOT"

# TS1 — Hook dependency completeness
assert_file "$HOOKS_DIR/lib/common.sh"
assert_file "$HOOKS_DIR/lib/sentinel.sh"
runtime_artifacts="$(find "$HOOKS_DIR" -maxdepth 4 \( -path '*/.omc*' -o -name '.DS_Store' -o -name '*.tmp' -o -name '*.log' \) -print 2>/dev/null || true)"
[ -z "$runtime_artifacts" ] || fail "hook templates contain runtime artifacts that would be recursively deployed: $runtime_artifacts"
while IFS= read -r src; do
  [ -n "$src" ] || continue
  case "$src" in
    '$(dirname "$0")/'*)
      rel="${src#'$(dirname "$0")/'}"
      assert_file "$HOOKS_DIR/$rel"
      ;;
    "\$(dirname \"\$0\")/"*)
      rel="${src#"\$(dirname \"\$0\")/"}"
      assert_file "$HOOKS_DIR/$rel"
      ;;
  esac
done < <(grep -RhoE '^source[[:space:]]+"[^"]+"' "$HOOKS_DIR"/*.sh | sed -E 's/^source[[:space:]]+"//;s/"$//' | sort -u)
# node 共享核 + CLI 桥：正文网/路径抽取/git commit 侦测/连续性的单一实现，被 bash hook 经
# `node "$(dirname "$0")/story_hook_cli.js"` 调用。大纲阻断判定与 staged markdown warnings 未归核，
# 仍是各端独立实现（Claude 纯 bash；codex↔core 由 test-prose-net-parity.sh Part C 锁 parity）。
# 这两条不是 source 依赖，上面的 grep 抓不到，显式断言存在 + 语法有效，否则 hook 静默退化
# （node 缺失时 hook 自身 exit 0、session-start.sh 会话起点提示一次，此处按开发机有 node 校验）。
assert_file "$HOOKS_DIR/story_hook_core.js"
assert_file "$HOOKS_DIR/story_hook_cli.js"
if command -v node >/dev/null 2>&1; then
  node --check "$HOOKS_DIR/story_hook_core.js" || fail "story_hook_core.js node syntax invalid"
  node --check "$HOOKS_DIR/story_hook_cli.js" || fail "story_hook_cli.js node syntax invalid"
fi
# 这是依赖方向的静态策略，不冒充行为测试：四个 bash hook 必须经 CLI 桥复用共享核，禁止
# 重新内嵌第五份 Python 实现。运行行为另由 test-prose-net-parity / hook 回归覆盖。
for hook in check-prose-after-write guard-outline-before-prose validate-story-commit detect-story-gaps; do
  if grep -q "<<'PY'" "$HOOKS_DIR/$hook.sh"; then
    fail "$hook.sh must not embed a duplicate Python implementation"
  fi
  assert_grep 'story_hook_cli\.js' "$HOOKS_DIR/$hook.sh" "$hook.sh must delegate to story_hook_cli.js"
done
assert_grep '递归复制完整目录树|recursive' "$SKILL_FILE" "SKILL.md must require recursive hook deployment"
assert_grep 'lib/common\.sh' "$SKILL_FILE" "SKILL.md must mention hooks/lib/common.sh"
assert_grep 'lib/sentinel\.sh' "$SKILL_FILE" "SKILL.md must mention hooks/lib/sentinel.sh"
echo "  OK TS1 hook dependency completeness"

# TS1b — SessionStart 部署自检名单必须覆盖所有 hook 脚本（防新增 hook 漏登记，#195 review）。
# *.js 一并枚举：story_hook_cli.js/story_hook_core.js 是承重共享核，被删时正文兜底/commit 侦测/
# 连续性检查全部静默退化，同样必须登记进自检名单。
selfcheck_line="$(grep -E 'for hook in .*; do' "$HOOKS_DIR/session-start.sh" | head -1)"
[ -n "$selfcheck_line" ] || fail "session-start.sh 缺少 hook 自检 for 循环"
# 名单里最后一个 hook 后面紧跟的是 `;` 而不是空格（grep 命中行按 pattern 必然以 `; do` 收尾），
# 直接拿原始行做 *" $base "* 会把「排在最后的、其实已登记」的 hook 误报成漏列。先把分号换成
# 空格并两端补空格，让首位/末位都能被同一条 case 命中，而不是要求名单保持某种排序。
selfcheck_tokens=" ${selfcheck_line//;/ } "
while IFS= read -r hookfile; do
  base="$(basename "$hookfile")"
  case "$selfcheck_tokens" in
    *" $base "*) : ;;
    # ${base} 必须加花括号：macOS bash 3.2 在 UTF-8 区域会把全角「（」的首字节并进变量名，
    # set -u 于是抛 base?: unbound variable，真正漏列时反而看不到是哪个 hook。
    *) fail "session-start.sh 部署自检名单漏列 hook：${base}（新增 hook 须同步加入该名单）" ;;
  esac
done < <(find "$HOOKS_DIR" -maxdepth 1 \( -name '*.sh' -o -name '*.js' \) -type f)
echo "  OK TS1b session-start self-check lists all hook scripts and node cores"

# TS2 — Deployment checklist/manifest parseability
for header in 'Source path' 'Target path' 'Owner class' 'Merge mode' 'Validation check'; do
  assert_grep "$header" "$SKILL_FILE" "deployment manifest missing column: $header"
done
for group in 'templates/hooks/' 'templates/rules' 'templates/agents' 'agent-references' 'settings-hooks\.json' 'CLAUDE\.md' '\.story-deployed'; do
  assert_grep "$group" "$SKILL_FILE" "deployment manifest missing asset group: $group"
done
assert_file "$SKILL_DIR/references/openclaw/AGENTS.md.tmpl"
assert_file "$SKILL_DIR/references/generic/AGENTS.md.tmpl"
assert_file "$SKILL_DIR/references/reasonix/AGENTS.md.tmpl"
assert_file "$SKILL_DIR/references/zcode/AGENTS.md.tmpl"
assert_file "$SKILL_DIR/references/zcode/config.json.patch"
assert_file "$SKILL_DIR/references/zcode/hooks/hooks.json"
assert_file "$SKILL_DIR/references/zcode/hooks/story_zcode_hook.js"
assert_file "$SKILL_DIR/references/zcode/hooks/story_hook_core.js"
assert_file "$SKILL_DIR/references/antigravity/rules/oh-story.md"
assert_file "$SKILL_DIR/references/antigravity/hooks/hooks.json"
assert_file "$SKILL_DIR/references/antigravity/hooks/story_antigravity_hook.js"
assert_file "$SKILL_DIR/references/antigravity/hooks/story_hook_core.js"
assert_file "$SKILL_DIR/scripts/generate-antigravity-agents.mjs"
assert_file "$SKILL_DIR/scripts/deploy-antigravity-skills.py"
assert_file "$SKILL_DIR/scripts/merge-antigravity-hooks.py"
# OpenCode shares the same prose-guard core (byte-identity guarded by check-opencode-adapter.sh);
# it deploys alongside plugin.ts as .opencode/plugins/lib/story_hook_core.js (lib/ subdir so it
# escapes OpenCode's single-level .opencode/plugins/*.js plugin auto-discovery).
assert_file "$SKILL_DIR/references/opencode/story_hook_core.js"
assert_grep 'opencode/story_hook_core\.js' "$SKILL_FILE" "deployment manifest missing OpenCode shared prose-guard core"
assert_grep 'references/openclaw/AGENTS\.md\.tmpl' "$SKILL_FILE" "deployment manifest missing OpenClaw AGENTS template"
assert_grep 'OpenClaw skills-only|target_cli 含 openclaw' "$SKILL_FILE" "story-setup must document OpenClaw skills-only deployment"
assert_grep 'references/generic/AGENTS\.md\.tmpl' "$SKILL_FILE" "deployment manifest missing generic AGENTS template"
assert_grep 'target_cli 含 generic|通用 Web AI / 其他 Agent' "$SKILL_FILE" "story-setup must document generic Web AI deployment"
assert_grep 'references/reasonix/AGENTS\.md\.tmpl' "$SKILL_FILE" "deployment manifest missing Reasonix AGENTS template"
assert_grep 'Reasonix skills-only|target_cli 含 reasonix' "$SKILL_FILE" "story-setup must document Reasonix skills-only deployment"
assert_grep 'references/zcode/AGENTS\.md\.tmpl' "$SKILL_FILE" "deployment manifest missing ZCode AGENTS template"
assert_grep 'target_cli 含 zcode|target_cli = zcode' "$SKILL_FILE" "story-setup must document ZCode deployment"
assert_grep '\.zcode/config\.json' "$SKILL_FILE" "story-setup must document ZCode config merge"
assert_grep '不部署.*\.zcode/agents|不创建.*\.zcode/agents' "$SKILL_FILE" "story-setup must document ZCode agent boundary"
assert_grep 'references_dir' "$SKILL_FILE" "sentinel references_dir must be documented"
assert_grep 'resolver_strategy' "$SKILL_FILE" "sentinel resolver_strategy must be documented"
assert_grep 'target_cli' "$SKILL_FILE" "sentinel target_cli must be documented"

# 部署清单的 Source 相对 skill 包、Target 相对项目根，两个基准目录在 skills-only 端会重合。
# 任何一行写成裸相同路径，执行方就会把目录复制进自身。
assert_grep 'copy-path-safety\.py' "$SKILL_FILE" "deployment must invoke the recursive-copy path safety helper"
assert_grep 'Path\.resolve.*realpath' "$SKILL_FILE" "deployment must canonicalize copy paths through symlinks"
assert_grep 'samefile' "$SKILL_FILE" "deployment must compare existing source/target filesystem identity"
assert_grep 'target-descendant|目标位于源目录内' "$SKILL_FILE" "deployment must reject recursive-copy targets inside their source"
assert_grep '清理自嵌套残留' "$SKILL_FILE" "story-setup must clean self-nested copies before deploying"
assert_file "$COPY_PATH_SAFETY"

# 执行真实 helper 验证 symlink alias、同目录、子目录和安全 sibling；不能只锁 SKILL.md 措辞。
path_fixture="$TMP_DIR/copy-path-safety"
mkdir -p "$path_fixture/project/skills/story-setup/references/agent-references" \
  "$path_fixture/project/.agents" "$path_fixture/source" "$path_fixture/sibling"

python3 - "$COPY_PATH_SAFETY" "$path_fixture" <<'PY' || fail "copy path safety helper behavior regressed"
import json
import importlib.util
import subprocess
import sys
from unittest import mock
from pathlib import Path

helper = sys.argv[1]
root = Path(sys.argv[2])


def run(source, target):
    proc = subprocess.run(
        [sys.executable, helper, str(source), str(target)],
        text=True,
        capture_output=True,
    )
    payload = json.loads(proc.stdout)
    return proc.returncode, payload


project = root / "project"
alias = project / ".agents/skills/story-setup/references/agent-references"
direct = project / "skills/story-setup/references/agent-references"
try:
    (project / ".agents/skills").symlink_to("../skills", target_is_directory=True)
except OSError as exc:
    # Windows runners without symlink privileges still exercise the other real helper paths.
    print("SKIP: symlink alias fixture unavailable: {}".format(exc))
else:
    code, payload = run(alias, direct)
    assert code == 0
    assert payload["status"] == "same"
    assert payload["copy_allowed"] is False
    assert payload["source_realpath"] == payload["target_realpath"]

source = root / "source"
code, payload = run(source, source / "nested/target")
assert code != 0
assert payload["status"] == "unsafe_target_within_source"
assert payload["copy_allowed"] is False
assert not (source / "nested").exists()

code, payload = run(source, root / "sibling/target")
assert code == 0
assert payload["status"] == "safe"
assert payload["copy_allowed"] is True
assert not (root / "sibling/target").exists()

code, payload = run(root / "missing", root / "sibling/target")
assert code != 0
assert payload["status"] == "source_missing"
assert payload["copy_allowed"] is False

spec = importlib.util.spec_from_file_location("copy_path_safety", helper)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with mock.patch.object(module.os.path, "samefile", side_effect=OSError("identity unavailable")):
    payload = module.classify_copy(source, root / "sibling")
assert payload["status"] == "filesystem_identity_error"
assert payload["copy_allowed"] is False
assert module.status_exit_code(payload["status"]) != 0
PY
# 探测器只写一份，先跑正负 fixture 自检，再扫真实 SKILL.md。
cat > "$TMP_DIR/detect-self-copy.py" <<'PY'
import re
import sys

path = sys.argv[1]
lines = open(path, encoding='utf-8').read().splitlines()
bad = []
in_manifest = False
# 「复制 A 到 B」里两个路径之间只隔几个字；隔得远的是叙述句，不是复制指令。
MAX_GAP = 16


def norm(cell):
    return cell.strip().strip('`').rstrip('/')


for idx, line in enumerate(lines, 1):
    stripped = line.strip()
    is_row = stripped.startswith('|') and stripped.endswith('|')
    if is_row and 'Source path' in stripped and 'Target path' in stripped:
        in_manifest = True
        continue
    if not is_row:
        in_manifest = False
    elif in_manifest:
        if set(stripped) <= set('|-: '):
            continue
        cells = [c.strip() for c in stripped.strip('|').split('|')]
        # 源写成 `repository ...` 时显式声明了它在仓库/skill 包一侧，与项目根一侧的
        # 目标不同名，自然不会相等；裸写成同一个字符串的才是复制进自身。
        if len(cells) >= 2 and norm(cells[0]) == norm(cells[1]):
            bad.append((idx, f'manifest row copies {cells[0]} onto itself'))
        continue
    if '复制' not in stripped and '拷贝' not in stripped:
        continue
    # 只看紧邻的一对反引号路径：中间只隔一个「到」而两侧同路径，就是复制进自身。
    # 两次出现之间夹着别的路径或大段叙述时不算——那是「从 A 复制到 B，A 是唯一来源」这类正常句子。
    spans = [(m.start(), m.end(), m.group(1)) for m in re.finditer(r'`([^`]+)`', stripped)]
    for (_, left_end, left), (right_start, _, right) in zip(spans, spans[1:]):
        gap = stripped[left_end:right_start]
        if '/' not in left or norm(left) != norm(right):
            continue
        if '到' in gap and len(gap) <= MAX_GAP:
            bad.append((idx, f'copy instruction names `{left}` as both source and target'))

for idx, msg in bad:
    print(f'{path}:{idx}: {msg}', file=sys.stderr)
sys.exit(1 if bad else 0)
PY

cat > "$TMP_DIR/self-copy-fixtures.md" <<'FIXTURE'
- 将 `references/opencode/agents/` 下所有文件复制到 `.opencode/agents/`；`references/opencode/agents/` 是唯一来源。
- 复制 `a/b/` 到 `a/b/`。
- 将 `a/b/` 同步复制到 `a/b/`。
- 复制 `x/y/` 到 `.codex/x/y/`。
- 复制 `a/b/` 到 `a/b`。
- 将 `skills/story-setup/references/agent-references/` 下所有 `.md` 复制到项目内 `.claude/skills/story-setup/references/agent-references/`。
- `a/b/` 与 `a/b/` 都要存在；提到复制但两者之间没有「到」。
- 拆文结果被复制进 `对标/`，用户看到的就是对标内容和自己设定一样；只有外部作品才进 `对标/`。
- 复制 `p/q/` 到 `r/s/`，`p/q/` 保留。
- 复制章节时 `第N章` 到 `第N章` 的编号不变。

| 角色 A | 角色 B | 关系类型 | 情感倾向 | 当前状态 | 起始章节 |
|--------|--------|---------|---------|---------|---------|
| {名} | {名} | {类型} | {倾向} | {描述} | 第{N}章 |

| Source path | Target path | Owner class | Merge mode | Validation check |
|-------------|-------------|-------------|------------|------------------|
| `a/b/` | `a/b` | story-setup managed | replace | resolves | 条件 |
| repository `a/b/` | `a/b/` | story-setup managed | replace | resolves | 条件 |
| `a/b/` | `.codex/a/b/` | story-setup managed | replace | resolves | 条件 |
FIXTURE

# 探测器有发现时退出码为 1；`|| true` 必须在管道内，否则 pipefail 会让赋值直接中止脚本，
# 连下面的 fail 消息都来不及打。
fixture_hits="$({ python3 "$TMP_DIR/detect-self-copy.py" "$TMP_DIR/self-copy-fixtures.md" 2>&1 >/dev/null || true; } | sed 's/.*fixtures\.md:\([0-9]*\):.*/\1/' | tr '\n' ',')"
[ "$fixture_hits" = "2,3,5,18," ] \
  || fail "self-copy detector fixtures regressed: expected lines 2,3,5,18 got [$fixture_hits]"

python3 "$TMP_DIR/detect-self-copy.py" "$SKILL_FILE" \
  || fail "story-setup declares a copy whose source and target are the same path"

# Claude Code 的 Bash 正文写入必须进入同一 pre-guard；只注册 Write/Edit 会让 cat>/tee/cp 绕过。
python3 - "$SKILL_DIR/references/templates/settings-hooks.json" <<'PY' || fail "Claude Bash prose pre-guard is not registered"
import json, sys
from pathlib import Path
hooks = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
assert any(
    "Bash" in block.get("matcher", "").split("|")
    and any("guard-outline-before-prose.sh" in hook.get("command", "") for hook in block.get("hooks", []))
    for block in hooks
)
PY
# v24 → v25 实际迁移：同 command 不能让旧 matcher 留存；混在旧 block 的用户 hook 要保留，且复跑幂等。
assert_file "$CLAUDE_MERGE"
cat > "$TMP_DIR/claude-v24.json" <<'JSON'
{
  "permissions": {"allow": ["Read"]},
  "customTop": "keep",
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          {"type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/guard-outline-before-prose.sh", "timeout": 7},
          {"type": "command", "command": "bash ./user-pre-hook.sh", "timeout": 99}
        ]
      }
    ],
    "PostToolUse": [
      {"matcher": "Bash", "hooks": [{"type": "command", "command": "bash \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/guard-outline-before-prose.sh", "timeout": 3}]}
    ]
  }
}
JSON
python3 "$CLAUDE_MERGE" --existing "$TMP_DIR/claude-v24.json" --template "$SETTINGS_FILE" --output "$TMP_DIR/claude-v25.json"
python3 - "$TMP_DIR/claude-v25.json" <<'PY' || fail "Claude v24→v25 hook migration failed"
import json, sys
doc=json.load(open(sys.argv[1],encoding="utf-8"))
assert doc["permissions"] == {"allow":["Read"]} and doc["customTop"] == "keep"
hits=[]; user=[]
for event, blocks in doc["hooks"].items():
    if not isinstance(blocks,list): continue
    for block in blocks:
        for hook in block.get("hooks",[]):
            cmd=hook.get("command","")
            if "guard-outline-before-prose.sh" in cmd: hits.append((event,block.get("matcher"),hook))
            if "user-pre-hook.sh" in cmd: user.append((event,block.get("matcher"),hook))
assert len(hits)==1, hits
assert hits[0][0]=="PreToolUse" and hits[0][1]=="Bash|Write|Edit|MultiEdit", hits
assert hits[0][2].get("timeout")==10, hits
assert len(user)==1 and user[0][0]=="PreToolUse" and user[0][1]=="Write|Edit|MultiEdit", user
PY
python3 "$CLAUDE_MERGE" --existing "$TMP_DIR/claude-v25.json" --template "$SETTINGS_FILE" --output "$TMP_DIR/claude-v25-again.json"
cmp -s "$TMP_DIR/claude-v25.json" "$TMP_DIR/claude-v25-again.json" \
  || fail "Claude settings merge is not idempotent"

# 重部署时 sentinel 的 target_cli 是权威：不认它就会每次重问，且 skills-only 三端根本无从探测。
assert_grep '已部署项目以 sentinel 里的值为准' "$SKILL_FILE" "story-setup must reuse the deployed target_cli on redeploy"
# metadata.openclaw 在 14 个 skill 上全都有，拿它判定会把 reasonix / generic 项目误认成 OpenClaw。
assert_no_grep '中的 `metadata\.openclaw`' "$SKILL_FILE" "story-setup must not detect OpenClaw from the skills bundle it deploys itself"
assert_grep '不作 OpenClaw 信号' "$SKILL_FILE" "story-setup must explain why metadata.openclaw is not a detection signal"
# skills-only 三端只能靠各自 AGENTS.md 的标题行区分；SKILL.md 引用的标记必须在模板里真的存在。
assert_grep '网文写作工具集（Reasonix）' "$SKILL_FILE" "story-setup must detect a deployed Reasonix project from AGENTS.md"
assert_grep '网文写作工具集（通用 Agent / Web AI）' "$SKILL_FILE" "story-setup must detect a deployed generic project from AGENTS.md"
assert_grep '网文写作工具集（Reasonix）' "$SKILL_DIR/references/reasonix/AGENTS.md.tmpl" "Reasonix AGENTS template must carry the marker story-setup detects"
assert_grep '网文写作工具集（通用 Agent / Web AI）' "$SKILL_DIR/references/generic/AGENTS.md.tmpl" "generic AGENTS template must carry the marker story-setup detects"
assert_grep '网文写作工具集（OpenClaw）' "$SKILL_DIR/references/openclaw/AGENTS.md.tmpl" "OpenClaw AGENTS template must carry the marker story-setup detects"
echo "  OK TS2 deployment manifest"

# TS3 — Agent reference bundle integrity
refs_tmp="$TMP_DIR/deployed-reference-bundle"
copy_agent_refs "$refs_tmp"
while IFS= read -r ref; do
  [ -n "$ref" ] || continue
  assert_file "$AGENT_REFS_DIR/$ref"
  assert_file "$refs_tmp/.claude/skills/story-setup/references/agent-references/$ref"
done < <(grep -RhoE 'story-setup/references/agent-references/[A-Za-z0-9_-]+\.md' \
  "$SKILL_DIR/references/templates/agents" "$AGENT_REFS_DIR" "$SKILL_DIR/references/templates/rules" 2>/dev/null \
  | sed 's|.*/||' | sort -u)
echo "  OK TS3 agent reference integrity"

# TS4 — Hook root resolution from nested cwd
root="$TMP_DIR/root-aware"
mkdir -p "$root/book/追踪" "$root/book/正文" "$root/book/设定" "$root/book/大纲" "$root/拆文库/sample"
setup_git_repo "$root"
copy_hooks "$root"
copy_agent_refs "$root"
write_sentinel "$root"
printf 'book\n' > "$root/.active-book"
cat > "$root/book/追踪/上下文.md" <<'CTX'
# 写作进度
## 当前位置
- 章: 第1章
CTX
touch "$root/拆文库/sample/_progress.md"
# 负向 fixture：已拆完的书不得再被报成「未完成」（裸数 _progress.md 会永久误报）。
mkdir -p "$root/拆文库/done"
printf '# 深度拆解进度：done\n\n- 最终状态：completed\n- schema_version: 3\n' > "$root/拆文库/done/_progress.md"

out_start="$(run_from_nested "$root" session-start.sh || true)"
echo "$out_start" | grep -q '当前位置' || fail "session-start did not resolve active book from project root"
echo "$out_start" | grep -q '未完成拆文' || fail "session-start did not resolve 拆文库 from project root"
echo "$out_start" | grep -q '有 1 个未完成拆文' || fail "session-start counted completed 拆文 as unfinished"
if echo "$out_start" | grep -q '参考资料包缺失'; then
  fail "session-start reported missing reference bundle after deployed refs were copied"
fi

out_pre="$(run_from_nested "$root" pre-compact.sh || true)"
echo "$out_pre" | grep -q 'Writing context: book/追踪/上下文.md' || fail "pre-compact did not resolve context from project root"

out_post="$(run_from_nested "$root" post-compact.sh || true)"
echo "$out_post" | grep -q 'Read book/追踪/上下文.md' || fail "post-compact did not resolve context from project root"

out_gaps="$(run_from_nested "$root" detect-story-gaps.sh || true)"
if [ -n "$out_gaps" ] && echo "$out_gaps" | grep -q "$root/nested"; then
  fail "detect-story-gaps leaked nested cwd paths"
fi
# 与 session-start 同口径：未完成的要报、已完成的不许报（两边各自读取 拆文库/，需各自钉死）。
echo "$out_gaps" | grep -q '拆文未完成：拆文库/sample/_progress.md' || fail "detect-story-gaps missed unfinished 拆文"
if echo "$out_gaps" | grep -q '拆文库/done/_progress.md'; then
  fail "detect-story-gaps counted completed 拆文 as unfinished"
fi

fallback_root="$TMP_DIR/git-fallback"
mkdir -p "$fallback_root/book/追踪" "$fallback_root/book/正文" "$fallback_root/book/大纲"
setup_git_repo "$fallback_root"
copy_hooks "$fallback_root"
copy_agent_refs "$fallback_root"
write_sentinel "$fallback_root"
printf 'book\n' > "$fallback_root/.active-book"
printf '# 写作进度\n' > "$fallback_root/book/追踪/上下文.md"
out_fallback="$(run_from_nested_no_project_dir "$fallback_root" pre-compact.sh || true)"
echo "$out_fallback" | grep -q 'Writing context: book/追踪/上下文.md' || fail "pre-compact did not resolve context via git root fallback without CLAUDE_PROJECT_DIR"

echo "  OK TS4 hook root resolution"

# TS5 — Sentinel / broken deployment diagnostics
broken_root="$TMP_DIR/broken-libs"
mkdir -p "$broken_root"
setup_git_repo "$broken_root"
copy_hooks "$broken_root"
write_sentinel "$broken_root"
rm -f "$broken_root/.claude/hooks/lib/sentinel.sh"
broken_out="$(run_from_nested "$broken_root" session-start.sh 2>&1 || true)"
echo "$broken_out" | grep -q 'hook 函数库缺失' || fail "session-start did not explain missing hook libraries before sourcing"

bad_sentinel_root="$TMP_DIR/bad-sentinel"
mkdir -p "$bad_sentinel_root"
setup_git_repo "$bad_sentinel_root"
copy_hooks "$bad_sentinel_root"
cat > "$bad_sentinel_root/.story-deployed" <<SENTINEL
deployed_at: 2026-05-24T00:00:00Z
agents_version: $CURRENT_AGENTS_VERSION
setup_skill_version: $CURRENT_SETUP_VERSION
resolver_strategy: project-local-skill-reference
references_dir: .claude/skills/story-setup/references/agent-references
SENTINEL
bad_sentinel_out="$(run_from_nested "$bad_sentinel_root" session-start.sh 2>&1 || true)"
echo "$bad_sentinel_out" | grep -q '缺少 target_cli' || fail "session-start did not warn for missing sentinel target_cli"
echo "$bad_sentinel_out" | grep -q '参考资料包缺失或为空' || fail "session-start did not warn for missing deployed reference bundle"

stale_previous_root="$TMP_DIR/stale-previous"
mkdir -p "$stale_previous_root/.claude/skills/story-setup/references/agent-references"
setup_git_repo "$stale_previous_root"
copy_hooks "$stale_previous_root"
cat > "$stale_previous_root/.story-deployed" <<SENTINEL
deployed_at: 2026-05-24T00:00:00Z
agents_version: $PREVIOUS_AGENTS_VERSION
setup_skill_version: $CURRENT_SETUP_VERSION
target_cli: claude-code
resolver_strategy: project-local-skill-reference
references_dir: .claude/skills/story-setup/references/agent-references
SENTINEL
stale_previous_out="$(run_from_nested "$stale_previous_root" session-start.sh 2>&1 || true)"
echo "$stale_previous_out" | grep -q "低于 v$CURRENT_AGENTS_VERSION" || fail "session-start did not warn for agents_version $PREVIOUS_AGENTS_VERSION stale v$CURRENT_AGENTS_VERSION deployment"

newer_project_root="$TMP_DIR/newer-project"
mkdir -p "$newer_project_root/.claude/skills/story-setup/references/agent-references"
setup_git_repo "$newer_project_root"
copy_hooks "$newer_project_root"
cat > "$newer_project_root/.story-deployed" <<SENTINEL
deployed_at: 2026-05-24T00:00:00Z
agents_version: $NEXT_AGENTS_VERSION
setup_skill_version: 1.3.0
target_cli: claude-code
resolver_strategy: project-local-skill-reference
references_dir: .claude/skills/story-setup/references/agent-references
SENTINEL
newer_project_out="$(run_from_nested "$newer_project_root" session-start.sh 2>&1 || true)"
echo "$newer_project_out" | grep -q "高于本 hook 支持的 v$CURRENT_AGENTS_VERSION" || fail "session-start did not reject agents_version $NEXT_AGENTS_VERSION downgrade"
echo "$newer_project_out" | grep -q '不要降级覆盖' || fail "session-start did not explain future-version safety"

mixed_version_root="$TMP_DIR/mixed-version"
mkdir -p "$mixed_version_root/.claude/skills/story-setup/references/agent-references"
setup_git_repo "$mixed_version_root"
copy_hooks "$mixed_version_root"
touch "$mixed_version_root/.claude/skills/story-setup/references/agent-references/dummy.md"
cat > "$mixed_version_root/.story-deployed" <<SENTINEL
deployed_at: 2026-05-24T00:00:00Z
agents_version: $CURRENT_AGENTS_VERSION
setup_skill_version: 1.2.6
target_cli: claude-code
resolver_strategy: project-local-skill-reference
references_dir: .claude/skills/story-setup/references/agent-references
SENTINEL
mixed_version_out="$(run_from_nested "$mixed_version_root" session-start.sh 2>&1 || true)"
# agents_version 是唯一运行时过期权威；setup_skill_version 落后不触发重部署（设计如此）
if echo "$mixed_version_out" | grep -q "低于 v$CURRENT_AGENTS_VERSION"; then
  fail "session-start incorrectly nagged '低于 v$CURRENT_AGENTS_VERSION' for current agents_version=$CURRENT_AGENTS_VERSION just because setup_skill_version lags"
fi
if echo "$mixed_version_out" | grep -q '高于本 hook'; then
  fail "session-start incorrectly nagged '高于本 hook' for current agents_version=$CURRENT_AGENTS_VERSION just because setup_skill_version lags"
fi

# 多端部署的 references_dir 是逗号分隔多条路径。整串当一条路径查会每次开会话都误报缺失，
# 且反过来漏掉真正缺的那一条——两个方向都要钉住。
multi_end_root="$TMP_DIR/multi-end-refs"
mkdir -p "$multi_end_root/.claude/skills/story-setup/references/agent-references"
mkdir -p "$multi_end_root/.codex/skills/story-setup/references/agent-references"
setup_git_repo "$multi_end_root"
copy_hooks "$multi_end_root"
touch "$multi_end_root/.claude/skills/story-setup/references/agent-references/dummy.md"
touch "$multi_end_root/.codex/skills/story-setup/references/agent-references/dummy.md"
cat > "$multi_end_root/.story-deployed" <<SENTINEL
deployed_at: 2026-05-24T00:00:00Z
agents_version: $CURRENT_AGENTS_VERSION
setup_skill_version: $CURRENT_SETUP_VERSION
target_cli: claude-code,codex
resolver_strategy: project-local-skill-reference
references_dir: .claude/skills/story-setup/references/agent-references,.codex/skills/story-setup/references/agent-references
SENTINEL
multi_end_out="$(run_from_nested "$multi_end_root" session-start.sh 2>&1 || true)"
if echo "$multi_end_out" | grep -q '参考资料包缺失或为空'; then
  fail "session-start falsely reported missing references for a complete multi-end deployment"
fi

rm -rf "$multi_end_root/.codex"
multi_end_partial_out="$(run_from_nested "$multi_end_root" session-start.sh 2>&1 || true)"
echo "$multi_end_partial_out" | grep -q '参考资料包缺失或为空' \
  || fail "session-start did not warn when one end of a multi-end references_dir is missing"
echo "$multi_end_partial_out" | grep -q '\.codex/skills/story-setup/references/agent-references' \
  || fail "session-start did not name the missing end in a multi-end references_dir"
if echo "$multi_end_partial_out" | grep -q '\.claude/skills/story-setup/references/agent-references,'; then
  fail "session-start reported the whole comma-joined references_dir instead of only the missing end"
fi

echo "  OK TS5 sentinel diagnostics"

# TS6 — Short project non-mutation
short_root="$TMP_DIR/short-project"
mkdir -p "$short_root/story"
setup_git_repo "$short_root"
copy_hooks "$short_root"
write_sentinel "$short_root"
printf 'story\n' > "$short_root/.active-book"
cat > "$short_root/story/正文.md" <<'TXT'
正文
TXT
run_from_nested "$short_root" session-end.sh >"$TMP_DIR/story-session-end.out" 2>&1 || true
[ ! -d "$short_root/story/追踪" ] || fail "session-end created 追踪/ for short project without opt-in"
(cd "$short_root/nested/a/b" && CLAUDE_PROJECT_DIR="$short_root" STORY_SESSION_LOG=1 bash "$short_root/.claude/hooks/session-end.sh") >"$TMP_DIR/story-session-end-opt.out" 2>&1 || true
[ ! -d "$short_root/story/追踪" ] || fail "session-end created 追踪/ for short project even with STORY_SESSION_LOG=1"
echo "  OK TS6 short project non-mutation"

# TS7 — Commit hook self-gating
commit_root="$TMP_DIR/commit-hook"
mkdir -p "$commit_root/book/正文" "$commit_root/book/设定" "$commit_root/short"
setup_git_repo "$commit_root"
copy_hooks "$commit_root"
cat > "$commit_root/book/正文/第1章.md" <<'TXT'
年龄 ：18
TXT
cat > "$commit_root/short/正文.md" <<'TXT'
身高: 180
TXT
cat > "$commit_root/book/设定/角色.md" <<'TXT'
角色设定
TXT
git -C "$commit_root" add "book/正文/第1章.md" "short/正文.md" "book/设定/角色.md"
for cmd in \
  'git commit -m test' \
  'git -c user.name=x commit -m test' \
  "git -C $commit_root commit -m test" \
  'command git commit -m test' \
  'env X=1 git commit -m test' \
  'git add .; git commit -m test' \
  $'git add .\ngit commit -m test' \
  '(git commit -m test)' \
  'if true; then git commit -m test; fi' \
  'noglob git commit -m test'; do
  assert_commit_warns "$commit_root" "$cmd" "$cmd"
done
for cmd in 'echo git commit docs' 'grep "git commit" file'; do
  non_commit_out="$(run_commit_hook_command "$commit_root" "$cmd")"
  [ -z "$non_commit_out" ] || fail "validate-story-commit warned for non-commit command '$cmd': $non_commit_out"
done
stdin_out="$(cd "$commit_root" && unset STORY_COMMIT_COMMAND CLAUDE_TOOL_INPUT && printf '%s' '{"tool_name":"Bash","tool_input":{"command":"git commit -m test"}}' | CLAUDE_PROJECT_DIR="$commit_root" bash .claude/hooks/validate-story-commit.sh 2>&1 || true)"
echo "$stdin_out" | grep -q 'Story Commit Warnings' || fail "validate-story-commit did not read stdin hook payload"
echo "$stdin_out" | grep -q 'short/正文.md' || fail "validate-story-commit did not inspect short-story 正文.md"
echo "$stdin_out" | grep -q 'book/设定/角色.md' || fail "validate-story-commit did not inspect staged setting markdown"

mono_root="$TMP_DIR/mono-root"
project_root="$mono_root/story-project"
mkdir -p "$project_root/book/正文"
setup_git_repo "$mono_root"
copy_hooks "$project_root"
cat > "$project_root/book/正文/第1章.md" <<'TXT'
身高:181
TXT
git -C "$mono_root" add "story-project/book/正文/第1章.md"
mono_out="$(cd "$project_root" && CLAUDE_PROJECT_DIR="$project_root" STORY_COMMIT_COMMAND='git commit -m test' bash .claude/hooks/validate-story-commit.sh 2>&1 || true)"
echo "$mono_out" | grep -q '正文硬编码角色属性' || fail "validate-story-commit missed staged files when CLAUDE_PROJECT_DIR differs from git root"
echo "  OK TS7 commit hook self-gating"

# TS8 — detect-story-gaps multi-book traversal
multi_root="$TMP_DIR/multi-book"
mkdir -p "$multi_root/long/追踪" "$multi_root/long/正文" "$multi_root/short"
setup_git_repo "$multi_root"
copy_hooks "$multi_root"
printf 'long\n' > "$multi_root/.active-book"
printf '长篇正文\n' > "$multi_root/long/正文/第1章.md"
printf '短篇正文\n' > "$multi_root/short/正文.md"
multi_out="$(run_from_nested "$multi_root" detect-story-gaps.sh || true)"
echo "$multi_out" | grep -q '^检查：long$' || fail "detect-story-gaps did not inspect long project when .active-book is set"
echo "$multi_out" | grep -q '^检查：short$' || fail "detect-story-gaps did not inspect short project alongside long project"
long_count="$(printf '%s\n' "$multi_out" | grep -c '^检查：long$' || true)"
[ "$long_count" -eq 1 ] || fail "detect-story-gaps reported long project $long_count times; expected exactly once"
echo "  OK TS8 multi-book gap detection"

# TS9 — Settings JSON remains valid
python3 -m json.tool "$SETTINGS_FILE" >/dev/null
echo "  OK TS9 settings JSON"

# TS10 — Version threshold + deployed-behavior anchors
# 只锚定「跑起来会坏」的东西：agents_version 阈值要跨文件对齐，部署到用户手里的
# agent 模板要带住关键行为规则。原先还夹着一批「UPGRADING.md/README 必须写到某句话」
# 的文档完整性断言——那种改一个词就红、测的是措辞不是行为，已随 check-story-long-write-contract.sh
# 一并去掉，发版是否补 UPGRADING 由发版清单和人把关，不靠 CI 钉死措辞。
assert_grep "AGENTS_VERSION.*-lt $CURRENT_AGENTS_VERSION|AGENTS_VERSION\" -lt $CURRENT_AGENTS_VERSION" "$HOOKS_DIR/session-start.sh" "session-start must warn for agents_version $PREVIOUS_AGENTS_VERSION under v$CURRENT_AGENTS_VERSION deployment"
assert_grep "AGENTS_VERSION.*-gt $CURRENT_AGENTS_VERSION|AGENTS_VERSION\" -gt $CURRENT_AGENTS_VERSION" "$HOOKS_DIR/session-start.sh" "session-start must reject agents_version $NEXT_AGENTS_VERSION downgrade"
assert_grep "agents_version.*小于 \`$CURRENT_AGENTS_VERSION\`|版本 < $CURRENT_AGENTS_VERSION" "$SKILL_DIR/SKILL.md" "story-setup redeploy branch must treat agents_version $PREVIOUS_AGENTS_VERSION as stale"
assert_grep "agents_version.*大于 \`$CURRENT_AGENTS_VERSION\`" "$SKILL_DIR/SKILL.md" "story-setup must stop before downgrading a newer deployment"
assert_grep 'Notice: agents bundle 版本不匹配' "$REPO_ROOT/skills/story-review/SKILL.md" "story-review must surface an agents_version mismatch"
assert_grep "大于 $CURRENT_AGENTS_VERSION 时额外提示先更新 oh-story-claudecode" "$REPO_ROOT/skills/story-review/SKILL.md" "story-review must tell newer deployments to update the package first"
assert_grep "^version:[[:space:]]*$CURRENT_SETUP_VERSION$" "$SKILL_FILE" "story-setup frontmatter must match the deployed setup version"

# Phase 1 自检的目录名单是硬编码的，必须与实际 references/ 子目录集合一致。
# 漏写一个 → 半装的包检不出；名单里多出已删除的目录 → 完好的包被判残缺，fail-closed 卡死所有部署。
selfcheck_line="$(grep -n '先自检参考目录' "$SKILL_FILE" | head -1 | cut -d: -f1)"
[ -n "$selfcheck_line" ] || fail "story-setup Phase 1 reference self-check paragraph not found"
selfcheck_text="$(sed -n "${selfcheck_line}p" "$SKILL_FILE")"
for ref_dir in "$SKILL_DIR"/references/*/; do
  ref_name="$(basename "$ref_dir")"
  case "$selfcheck_text" in
    *"\`$ref_name\`"*) ;;
    *) fail "story-setup Phase 1 self-check list is missing reference dir: $ref_name" ;;
  esac
done
ref_dir_count="$(find "$SKILL_DIR/references" -maxdepth 1 -mindepth 1 -type d | wc -l | tr -d ' ')"
[ "$ref_dir_count" -eq 9 ] || fail "story-setup references/ now has $ref_dir_count subdirs (expected 9); update the Phase 1 self-check list and this assertion"
assert_grep '全局分析/爆款机制\.md' "$SKILL_DIR/references/templates/agents/story-explorer.md" "story-explorer must require the current hit-mechanism artifact"
assert_grep '全局分析/六维拆书\.md.*三维节奏|三维节奏.*全局分析/六维拆书\.md' "$SKILL_DIR/references/templates/agents/story-explorer.md" "story-explorer must require the three-axis rhythm section in the current six-dimension artifact"
assert_grep 'chapter_index_missing.*missing_primary_contract|missing_primary_contract.*chapter_index_missing' "$SKILL_DIR/references/templates/agents/story-explorer.md" "story-explorer must fail closed on a missing chapter index"
assert_no_grep 'legacy_deconstruction|contract_version.*legacy|pre-v12' "$SKILL_DIR/references/templates/agents/story-explorer.md" "story-explorer must not keep legacy benchmark branches"
assert_grep 'missing_primary_contract: true|missing_primary_contract": true' "$SKILL_DIR/references/templates/agents/story-explorer.md" "story-explorer must emit missing_primary_contract for broken canonical artifacts"
assert_grep 'repair_action.*Stage 3|Stage 3.*repair_action|重跑 /story-long-analyze Stage 3' "$SKILL_DIR/references/templates/agents/story-explorer.md" "story-explorer must provide a repair action instead of silent fallback"
assert_grep 'missing_primary_contract' "$REPO_ROOT/skills/story-long-write/SKILL.md" "story-long-write must not silently fallback for missing primary artifacts"
assert_grep '内容概括（五段式）|情节安排（多线）|人物关系和出场顺序|结尾设定和钩子' "$SKILL_DIR/references/templates/agents/story-architect.md" "story-architect must output v13 chapter blueprint fields"
assert_grep '逻辑线|人物关系变化|行动成本（可无）/收益归属|结尾设定' "$SKILL_DIR/references/templates/agents/consistency-checker.md" "consistency-checker must consume current outline blueprint fields"
assert_grep '语气标点谱系' "$SKILL_DIR/references/templates/agents/narrative-writer.md" "narrative-writer must enforce v13 tone punctuation"
assert_grep '不用.*……|不使用.*……|不保留.*……|不残留.*……' "$SKILL_DIR/references/templates/agents/narrative-writer.md" "narrative-writer must reject ellipsis pause punctuation"
assert_grep '不用.*——|不使用.*——|不保留.*——|不残留.*——' "$SKILL_DIR/references/templates/agents/narrative-writer.md" "narrative-writer must reject dialogue dash exception"
assert_grep '语气标点谱系' "$AGENT_REFS_DIR/format-and-structure.md" "agent references must include v13 tone punctuation format rules"
assert_grep '不用.*……|不使用.*……|不保留.*……|不残留.*……' "$AGENT_REFS_DIR/format-and-structure.md" "agent references must forbid ellipsis pause punctuation"
assert_grep '不用.*——|不使用.*——|不保留.*——|不残留.*——|正文和对话都禁止.*——' "$AGENT_REFS_DIR/format-and-structure.md" "agent references must forbid dialogue dash exception"
assert_grep '禁止高置信否定铺垫后再肯定翻转|禁止高置信否定翻转句式' "$SKILL_DIR/references/templates/agents/narrative-writer.md" "narrative-writer must hard-ban high-confidence not-then-is flips"
assert_grep '跨段.*不是A / 也不是B / 只是C.*(只作语义复核|advisory)' "$SKILL_DIR/references/templates/agents/narrative-writer.md" "narrative-writer must treat cross-paragraph negation as advisory"
assert_grep '承担辩解、悬念排除或情绪递进时可保留|承担辩解、悬念排除、情绪递进等功能时可保留' "$SKILL_DIR/references/templates/agents/narrative-writer.md" "narrative-writer must preserve functional cross-paragraph negation"
assert_grep '至于X不X，怎么X' "$SKILL_DIR/references/templates/agents/narrative-writer.md" "narrative-writer must review formulaic dialogue too"
assert_grep 'check-ai-patterns\.js --check' "$SKILL_DIR/references/templates/agents/narrative-writer.md" "narrative-writer must require detector rescan handoff"
assert_grep '裸调用.*不得自动进入正文写作|不得自动进入正文写作.*裸调用' "$REPO_ROOT/skills/story-long-write/SKILL.md" "story-long-write bare invocation must not auto-write prose"
assert_grep '不得把已有项目默认为日更 3 章|默认为日更 3 章' "$REPO_ROOT/skills/story-long-write/SKILL.md" "story-long-write must not default existing projects to daily 3 chapters on bare invocation"
assert_grep '默认停在细纲交付|默认停靠.*Phase 1→3' "$REPO_ROOT/skills/story-long-write/SKILL.md" "story-long-write opening flow must stop after outline by default"
assert_grep '本轮 K（最多 3 章）后必须进入 Step 3/4 收尾并停止|最多 3 章.*收尾并停止' "$REPO_ROOT/skills/story-long-write/references/workflow-daily.md" "daily workflow must stop after bounded batch"
assert_grep '细纲边界|不得自造剧情' "$SKILL_DIR/references/templates/agents/narrative-writer.md" "narrative-writer must enforce the outline boundary"
assert_grep '`under` 不补.*`over`.*`compress-once`' "$SKILL_DIR/references/opencode/agents/narrative-writer.md" "opencode narrative-writer must keep asymmetric wordcount handling"
assert_grep 'over 单次压缩.*净删.*不增语义' "$SKILL_DIR/references/opencode/agents/narrative-writer.md" "opencode narrative-writer must keep one-pass semantic-preserving compression"
assert_grep '`under` 不补.*`over`.*`compress-once`' "$SKILL_DIR/references/codex/agents/narrative-writer.toml" "codex narrative-writer must keep asymmetric wordcount handling"
assert_grep 'over 单次压缩.*净删.*不增语义' "$SKILL_DIR/references/codex/agents/narrative-writer.toml" "codex narrative-writer must keep one-pass semantic-preserving compression"
assert_grep '导入续写入口顺序|推荐顺序.*story-setup' "$REPO_ROOT/skills/story-import/SKILL.md" "story-import must answer setup-vs-import order before asking for source"
echo "  OK TS10 version + behavior anchors"

# TS11 — Outline-before-prose write guard (BLOCKING PreToolUse hook)
guard_root="$TMP_DIR/outline-guard"
mkdir -p "$guard_root/book/正文" "$guard_root/book/大纲" "$guard_root/book/设定" \
         "$guard_root/short" "$guard_root/docs" \
         "$guard_root/impbook/正文" "$guard_root/拆文库/impbook" \
         "$guard_root/impshort" "$guard_root/拆文库/impshort"
setup_git_repo "$guard_root"
copy_hooks "$guard_root"
assert_file "$guard_root/.claude/hooks/guard-outline-before-prose.sh"

run_guard() {
  # $1 = file_path ; prints the hook exit code (0 allow, 2 block)
  local fp="$1" ec=0
  printf '{"tool_name":"Write","tool_input":{"file_path":"%s","content":"x"}}' "$fp" \
    | CLAUDE_PROJECT_DIR="$guard_root" bash "$guard_root/.claude/hooks/guard-outline-before-prose.sh" >/dev/null 2>&1 || ec=$?
  printf '%s' "$ec"
}

run_bash_guard() {
  # $1 = Bash command ; prints the hook exit code (0 allow, 2 block)
  local command_text="$1" ec=0 payload
  payload="$(python3 - "$command_text" <<'PY'
import json, sys
print(json.dumps({"tool_name": "Bash", "tool_input": {"command": sys.argv[1]}}, ensure_ascii=False))
PY
)"
  printf '%s' "$payload" \
    | CLAUDE_PROJECT_DIR="$guard_root" bash "$guard_root/.claude/hooks/guard-outline-before-prose.sh" >/dev/null 2>&1 || ec=$?
  printf '%s' "$ec"
}

# 长篇授权流：缺细纲拦截 / 有细纲放行 / 章号补零容忍
[ "$(run_guard 'book/正文/第1章_开端.md')" = "2" ] || fail "guard did not BLOCK long prose when 细纲 missing"
: > "$guard_root/book/大纲/细纲_第1章.md"
# 细纲齐了还要过追踪检查点（issue #305 起 Claude 侧也有这道门，与另三端同序）。
# 本节测的是细纲门与路径分类，不是追踪门，所以先落一份有效 state 把追踪这一维固定住。
# last_committed 取一个大于本节所有用例章号的值：章号已在追踪范围内即跳过顺序校验，
# 于是 第1/7/123/124 章都只被细纲门判定。顺序校验本身由 test-prose-net-parity.sh Part D
# 的场景矩阵覆盖，不在这里重复。
mkdir -p "$guard_root/book/追踪"
printf '{"schema_version":4,"state_revision":0,"last_committed_chapter":200}\n' > "$guard_root/book/追踪/_tracking-state.json"
printf '> 状态修订：0。\n' > "$guard_root/book/追踪/上下文.md"
[ "$(run_guard 'book/正文/第1章_开端.md')" = "0" ] || fail "guard wrongly blocked long prose when 细纲 present"
# 追踪门本身：state 移走即拦（Claude 端此前静默放行，写出无追踪正文）
mv "$guard_root/book/追踪/_tracking-state.json" "$guard_root/book/追踪/_state.bak"
[ "$(run_guard 'book/正文/第1章_开端.md')" = "2" ] || fail "guard did not BLOCK long prose when tracking state missing"
mv "$guard_root/book/追踪/_state.bak" "$guard_root/book/追踪/_tracking-state.json"
[ "$(run_guard 'book/正文/第001章_开端.md')" = "0" ] || fail "guard did not tolerate chapter-number zero padding (第001章 vs 细纲_第1章)"
: > "$guard_root/book/大纲/细纲_第7章_惊变.md"
[ "$(run_guard 'book/正文/第7章_x.md')" = "0" ] || fail "guard did not tolerate title-suffixed 细纲 (细纲_第7章_惊变.md)"
# 短篇授权流：有 设定.md 信号 + 缺小节大纲 -> 拦截；补小节大纲 -> 放行
: > "$guard_root/short/设定.md"
[ "$(run_guard 'short/正文.md')" = "2" ] || fail "guard did not BLOCK short prose when 小节大纲.md missing"
: > "$guard_root/short/小节大纲.md"
[ "$(run_guard 'short/正文.md')" = "0" ] || fail "guard wrongly blocked short prose when 小节大纲.md present"
# 非作品文件 / 无短篇工程信号 -> 放行（宁可漏拦不可误伤）
[ "$(run_guard 'book/设定/角色.md')" = "0" ] || fail "guard wrongly blocked a non-prose file"
[ "$(run_guard 'docs/正文.md')" = "0" ] || fail "guard wrongly blocked a non-story 正文.md (no 设定.md signal)"
# 已存在正文 -> 放行（续写/改稿/去AI味）
: > "$guard_root/book/正文/第9章_x.md"
[ "$(run_guard 'book/正文/第9章_x.md')" = "0" ] || fail "guard wrongly blocked rewrite of an existing prose file"
# story-import 迁移流：存在 拆文库/{书名}/ 源 -> 正文先于大纲/小节大纲迁移，放行
[ "$(run_guard 'impbook/正文/第1章_x.md')" = "0" ] || fail "guard wrongly blocked story-import LONG prose migration (拆文库 source present)"
: > "$guard_root/impshort/设定.md"
[ "$(run_guard 'impshort/正文.md')" = "0" ] || fail "guard wrongly blocked story-import SHORT prose migration (拆文库 source present)"
# Bash 命令面：真正写正文才拦；只提及正文路径不得误伤。第8章无细纲，故写入应阻断。
if command -v node >/dev/null 2>&1; then
  [ "$(run_bash_guard 'cat draft.md > book/正文/第8章_x.md')" = "2" ] \
    || fail "Claude Bash write bypassed prose pre-guard"
  [ "$(run_bash_guard 'grep -n book/正文/第8章_x.md notes.md')" = "0" ] \
    || fail "Claude Bash read-only mention was wrongly blocked"

  # 相对 Bash 目标必须按 hook cwd 解，不得总按项目根；根 book 有第8章细纲，nested/book 没有。
  : > "$guard_root/book/大纲/细纲_第8章.md"
  mkdir -p "$guard_root/nested/book/正文"
  cwd_payload="$(python3 - "$guard_root/nested" <<'PY'
import json, sys
print(json.dumps({"cwd": sys.argv[1], "tool_name": "Bash", "tool_input": {"command": "cat > book/正文/第8章_x.md"}}, ensure_ascii=False))
PY
)"
  cwd_ec=0
  printf '%s' "$cwd_payload" \
    | CLAUDE_PROJECT_DIR="$guard_root" bash "$guard_root/.claude/hooks/guard-outline-before-prose.sh" >/dev/null 2>&1 || cwd_ec=$?
  [ "$cwd_ec" = "2" ] || fail "Claude Bash relative target ignored hook cwd"

  # 共享核损坏时保持 fail-open，但必须显式告警，不能把运行时错误伪装成“无写入目标”。
  cp "$guard_root/.claude/hooks/story_hook_core.js" "$guard_root/.claude/hooks/story_hook_core.js.bak"
  printf '%s\n' 'throw new Error("broken core fixture")' > "$guard_root/.claude/hooks/story_hook_core.js"
  broken_payload="$(python3 - <<'PY'
import json
print(json.dumps({"tool_name": "Bash", "tool_input": {"command": "cat > book/正文/第8章_x.md"}}, ensure_ascii=False))
PY
)"
  broken_ec=0
  broken_err="$(printf '%s' "$broken_payload" \
    | CLAUDE_PROJECT_DIR="$guard_root" bash "$guard_root/.claude/hooks/guard-outline-before-prose.sh" 2>&1 >/dev/null)" || broken_ec=$?
  mv "$guard_root/.claude/hooks/story_hook_core.js.bak" "$guard_root/.claude/hooks/story_hook_core.js"
  [ "$broken_ec" = "0" ] || fail "broken Bash guard core must preserve documented fail-open behavior"
  printf '%s' "$broken_err" | grep -q '守卫解析失败' \
    || fail "broken Bash guard core was silently ignored: $broken_err"
fi
echo "  OK TS11 outline-before-prose guard"

# TS11b — 阻断守卫在无 node 时必须回落纯 bash 抽取、仍然 exit 2（不得 fail-open）。
# 官方现推荐原生二进制装 Claude Code（不带 Node），只有 npm 装法才有 node；原实现只探测 node、
# 探不到就放行，会让"缺细纲写正文"被静默放过（#243 回归）。用一个恒退非零的假 node 垫片模拟
# "node 不可用"，其余工具(sed/grep/bash)仍在 PATH。垫片若未能遮蔽真 node（个别 Windows 主机）
# 则跳过，避免环境导致假失败。
nonode_shim="$TMP_DIR/nonode-shim"
mkdir -p "$nonode_shim"
printf '#!/bin/sh\nexit 1\n' > "$nonode_shim/node"
chmod +x "$nonode_shim/node"
run_guard_nonode() {
  local fp="$1" ec=0
  printf '{"tool_name":"Write","tool_input":{"file_path":"%s","content":"x"}}' "$fp" \
    | CLAUDE_PROJECT_DIR="$guard_root" PATH="$nonode_shim:$PATH" \
      bash "$guard_root/.claude/hooks/guard-outline-before-prose.sh" >/dev/null 2>&1 || ec=$?
  printf '%s' "$ec"
}
if ! PATH="$nonode_shim:$PATH" node -e "" >/dev/null 2>&1; then
  # 缺细纲 -> 仍须拦截（bash 兜底解析出目标路径，照常 exit 2）
  [ "$(run_guard_nonode 'book/正文/第123章_无纲.md')" = "2" ] \
    || fail "guard fail-OPEN without node (regression #243): 缺细纲写正文必须仍拦截（bash 兜底）"
  : > "$guard_root/book/大纲/细纲_第123章.md"
  # 有细纲 -> 放行（bash 兜底不误伤）
  [ "$(run_guard_nonode 'book/正文/第123章_无纲.md')" = "0" ] \
    || fail "guard(no-node) wrongly blocked long prose when 细纲 present (bash 兜底)"
  # 非正文目标 -> 放行
  [ "$(run_guard_nonode 'book/设定/角色.md')" = "0" ] \
    || fail "guard(no-node) wrongly blocked a non-prose file (bash 兜底)"
  echo "  OK TS11b outline guard fail-closed without node"
else
  echo "  SKIP TS11b (假 node 垫片未能遮蔽真 node，跳过 no-node 回归)"
fi

# TS11c — node 在场但抽取失败（旧 node 不识 node: 前缀 / 部署核损坏时探测通过、跑脚本抛错）时，
# 阻断守卫必须回落纯 bash、仍 exit 2。原实现用 if/else：node 探测一过就只走 node 分支，抽空即放行，
# 正是 #243 复盘发现的第二个 fail-open 面。垫片「node -e '' 退 0、跑真实脚本退非零」模拟坏 node；
# 只有确认解析到的 node 就是垫片时才跑（否则真 node 会让断言因错误原因通过）。
brokennode_shim="$TMP_DIR/brokennode-shim"
mkdir -p "$brokennode_shim"
printf '#!/bin/sh\n[ "$1" = "-e" ] && exit 0\nexit 1\n' > "$brokennode_shim/node"
chmod +x "$brokennode_shim/node"
run_guard_brokennode() {
  local fp="$1" ec=0
  printf '{"tool_name":"Write","tool_input":{"file_path":"%s","content":"x"}}' "$fp" \
    | CLAUDE_PROJECT_DIR="$guard_root" PATH="$brokennode_shim:$PATH" \
      bash "$guard_root/.claude/hooks/guard-outline-before-prose.sh" >/dev/null 2>&1 || ec=$?
  printf '%s' "$ec"
}
resolved_node="$(PATH="$brokennode_shim:$PATH" bash -c 'command -v node' 2>/dev/null || true)"
if [ "$resolved_node" = "$brokennode_shim/node" ]; then
  # node 探测通过但 CLI 抽取抛错 -> 缺细纲仍须拦截（bash 兜底解析目标路径）
  [ "$(run_guard_brokennode 'book/正文/第124章_坏node.md')" = "2" ] \
    || fail "guard fail-OPEN with broken node (regression #243): node 在但抽取失败时必须回落 bash 仍拦截"
  : > "$guard_root/book/大纲/细纲_第124章.md"
  # 有细纲 -> 放行（bash 兜底不误伤）
  [ "$(run_guard_brokennode 'book/正文/第124章_坏node.md')" = "0" ] \
    || fail "guard(broken-node) wrongly blocked long prose when 细纲 present (bash 兜底)"
  echo "  OK TS11c outline guard fail-closed when node present-but-broken"
else
  echo "  SKIP TS11c (假 node 垫片未能遮蔽真 node，跳过 broken-node 回归)"
fi

# TS12 — Agents-pending-restart one-shot confirmation
restart_root="$TMP_DIR/restart-flag"
mkdir -p "$restart_root/.claude"
setup_git_repo "$restart_root"
copy_hooks "$restart_root"
copy_agent_refs "$restart_root"
write_sentinel "$restart_root"
touch "$restart_root/.claude/.agents-pending-restart"
restart_out="$(run_from_nested "$restart_root" session-start.sh || true)"
echo "$restart_out" | grep -q '现已注册可用' || fail "session-start did not confirm agents registered after restart flag"
[ ! -f "$restart_root/.claude/.agents-pending-restart" ] || fail "session-start did not clear the one-shot .agents-pending-restart flag"
echo "  OK TS12 restart-flag confirmation"

echo ""
echo "OK: story-setup deployment checks passed"
