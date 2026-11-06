#!/usr/bin/env bash
# Deterministic checks for the Google Antigravity 2.0 project adapter.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
cd "$REPO_ROOT"

fail() { echo "FAIL: $*" >&2; exit 1; }
CURRENT_AGENTS_VERSION="$(node -e 'process.stdout.write(String(require(process.argv[1]).agents_version))' "$SCRIPT_DIR/current-contract.json")"
assert_file() { [ -f "$1" ] || fail "required file missing: $1"; }

ROOT="skills/story-setup/references/antigravity"
HOOK="$ROOT/hooks/story_antigravity_hook.js"
CORE="$ROOT/hooks/story_hook_core.js"
GENERATOR="skills/story-setup/scripts/generate-antigravity-agents.mjs"

for file in \
  "$ROOT/hooks/hooks.json" \
  "$HOOK" \
  "$CORE" \
  "$ROOT/rules/oh-story.md" \
  "$GENERATOR" \
  skills/story-setup/scripts/deploy-antigravity-skills.py \
  skills/story-setup/scripts/merge-antigravity-hooks.py; do
  assert_file "$file"
done

python3 -m json.tool "$ROOT/hooks/hooks.json" >/dev/null
node --check "$HOOK"
node --check "$CORE"
node --check "$GENERATOR"
cmp -s "$CORE" skills/story-setup/references/templates/hooks/story_hook_core.js \
  || fail "Antigravity shared hook core is stale"

python3 - <<'PY'
import json
from pathlib import Path

hooks = json.loads(Path('skills/story-setup/references/antigravity/hooks/hooks.json').read_text())
assert set(hooks) == {'oh-story'}
group = hooks['oh-story']
assert set(group) == {'PreToolUse', 'PostToolUse', 'PreInvocation', 'Stop'}
for event, entries in group.items():
    assert isinstance(entries, list) and entries, event
    for entry in entries:
        handlers = entry.get('hooks', [entry])
        for handler in handlers:
            assert handler['type'] == 'command'
            assert 'hooks/story_antigravity_hook.js' in handler['command']
            assert '.agents/.agents/' not in handler['command']
            assert isinstance(handler['timeout'], int) and 1 <= handler['timeout'] <= 30
expected_matcher = 'run_command|write_file|edit_file|write_to_file|replace_file_content|multi_replace_file_content'
assert group['PreToolUse'][0]['matcher'] == expected_matcher
assert group['PostToolUse'][0]['matcher'] == expected_matcher

rule = Path('skills/story-setup/references/antigravity/rules/oh-story.md').read_text()
assert rule.startswith('---\ntrigger: always_on\n---\n')
assert len(rule) < 12_000
assert '.agents/skills/' in rule and 'invoke_subagent' in rule
assert 'Role' in rule and 'send_message' in rule and 'read_file' in rule
assert '~/.gemini/' in rule and 'scratch/' in rule and 'inside the current workspace' in rule
PY

node "$GENERATOR" --dest "$TMP_DIR/agents" >/dev/null
mkdir -p "$TMP_DIR/agents/user-agent"
printf '%s\n' 'user-owned agent' > "$TMP_DIR/agents/user-agent/agent.md"
printf '%s\n' 'legacy managed agent' > "$TMP_DIR/agents/story-explorer.md"
mkdir -p "$TMP_DIR/outside-agent"
printf '%s\n' 'outside canary' > "$TMP_DIR/outside-agent/agent.md"
rm -rf "$TMP_DIR/agents/story-architect"
ln -s "$TMP_DIR/outside-agent" "$TMP_DIR/agents/story-architect"
node "$GENERATOR" --dest "$TMP_DIR/agents" >/dev/null
[ "$(cat "$TMP_DIR/agents/user-agent/agent.md")" = "user-owned agent" ] \
  || fail "generator must preserve user-owned agents"
[ ! -e "$TMP_DIR/agents/story-explorer.md" ] \
  || fail "generator must remove its legacy flat managed agent"
[ ! -L "$TMP_DIR/agents/story-architect" ] \
  || fail "generator must replace a managed agent symlink with a real directory"
[ "$(cat "$TMP_DIR/outside-agent/agent.md")" = "outside canary" ] \
  || fail "generator must not write through a managed agent symlink"
python3 - "$TMP_DIR/agents" <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
expected = {
    'chapter-extractor', 'character-designer', 'consistency-checker',
    'narrative-writer', 'story-architect', 'story-explorer', 'story-researcher',
}
agents = sorted(path for path in root.glob('*/agent.md') if path.parent.name in expected)
assert {path.parent.name for path in agents} == expected
allowed_tools = {
    'view_file', 'find_by_name', 'grep_search', 'write_to_file',
    'replace_file_content', 'multi_replace_file_content', 'run_command',
}
for agent in agents:
    text = agent.read_text(encoding='utf-8')
    assert text.startswith('---\n')
    front = text.split('---\n', 2)[1]
    name = re.search(r'^name:\s*(\S+)$', front, re.M).group(1)
    assert name == agent.parent.name
    assert re.search(r'^mainAgent:\s*false$', front, re.M)
    assert re.search(r'^subagent:\s*true$', front, re.M)
    assert re.search(r'^model:\s*(flash|pro)$', front, re.M)
    assert re.search(r'^commandExecutionPolicy:\s*sandbox$', front, re.M)
    tools = set(re.findall(r'^  - ([a-z_]+)$', front, re.M))
    assert tools and tools <= allowed_tools, (agent, tools)
    body = text.split('---\n', 2)[2]
    if 'run_command' not in tools:
        assert '执行 `git rev-parse --show-toplevel`' not in body, agent
    assert '.claude/skills/' not in text
    assert '.agents/skills/story-setup/references/agent-references/' in text
    assert f'TypeName: "{name}"' in text
    assert 'send_message' in text and 'read_file' in text and 'write_file' in text and 'edit_file' in text
researcher = (root / 'story-researcher/agent.md').read_text(encoding='utf-8')
assert 'has no WebSearch/webReader tool' in researcher
assert 'never claim that web fallback ran' in researcher
assert '### 第四步：WebSearch/webReader（兜底）' not in researcher
assert 'CDP 不可用时交回父会话' in researcher
assert 'WebSearch/webReader 作为兜底' not in researcher
PY

mkdir -p "$TMP_DIR/safe-dest"
printf 'keep\n' > "$TMP_DIR/safe-dest/sentinel.md"
mkdir -p "$TMP_DIR/empty-source"
if node "$GENERATOR" --source "$TMP_DIR/empty-source" --dest "$TMP_DIR/safe-dest" >/dev/null 2>&1; then
  fail "generator must reject an empty source directory"
fi
assert_file "$TMP_DIR/safe-dest/sentinel.md"

python3 scripts/test-antigravity-hook-merge.py
python3 scripts/test-antigravity-skills-deploy.py
node scripts/test-antigravity-hooks.mjs

grep -q 'target_cli = antigravity' skills/story-setup/SKILL.md \
  || fail "story-setup does not detect Antigravity"
grep -q "agents_version: $CURRENT_AGENTS_VERSION" skills/story-setup/SKILL.md \
  || fail "story-setup deployment contract is not v$CURRENT_AGENTS_VERSION"
# 入口按宿主只读一份部署文件：入口要路由到 Antigravity 那份，算法与校验写在那份里。
grep -q 'references/deploy-antigravity\.md' skills/story-setup/SKILL.md \
  || fail "story-setup entry does not route antigravity to its deploy file"
grep -q 'Antigravity 部署算法' skills/story-setup/references/deploy-antigravity.md \
  || fail "story-setup lacks Antigravity deployment algorithm"
grep -q 'references_dir` 写 `\.agents/skills/story-setup/references/agent-references' skills/story-setup/references/deploy-antigravity.md \
  || fail "Antigravity deploy file must set references_dir to .agents/skills"
grep -q -- '--migrate-symlink' skills/story-setup/references/deploy-antigravity.md \
  || fail "Antigravity deploy file must gate .agents/skills symlink migration on author consent"

echo "Antigravity adapter checks passed."
