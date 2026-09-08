#!/usr/bin/env bash
# Deterministic checks for the ZCode plugin and story-setup deployment surface.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

fail() { echo "FAIL: $*" >&2; exit 1; }
assert_file() { [ -f "$1" ] || fail "required file missing: $1"; }
assert_grep() { grep -Eq "$1" "$2" || fail "$3 ($2)"; }

ROOT="skills/story-setup/references/zcode"
HOOK="$ROOT/hooks/story_zcode_hook.js"
HOOK_CORE="$ROOT/hooks/story_hook_core.js"

echo "ZCode adapter check"
echo "==================="
echo "Repo: $REPO_ROOT"

for file in \
  .zcode-plugin/plugin.json \
  marketplace.json \
  "$ROOT/AGENTS.md.tmpl" \
  "$ROOT/config.json.patch" \
  "$ROOT/hooks/hooks.json" \
  "$HOOK" \
  "$HOOK_CORE"; do
  assert_file "$file"
done

for file in .zcode-plugin/plugin.json marketplace.json "$ROOT/config.json.patch" "$ROOT/hooks/hooks.json"; do
  python3 -m json.tool "$file" >/dev/null
done
node --check "$HOOK"
node --check "$HOOK_CORE"
echo "  OK JSON/JavaScript syntax"

python3 - <<'PY'
import json
from pathlib import Path

plugin = json.loads(Path('.zcode-plugin/plugin.json').read_text())
assert plugin['commands'] == 'skills/story-setup/references/zcode/commands'
assert plugin['hooks'] == 'skills/story-setup/references/zcode/hooks/hooks.json'
for key in ('agents', 'channels', 'lspServers', 'outputStyles', 'settings'):
    assert key not in plugin, f'non-runnable ZCode component declared: {key}'

market = json.loads(Path('marketplace.json').read_text())
assert market['version'] == 1
PY
# ZCode's GitHub importer may discover the Claude catalog (#390); verify both
# catalog paths against both native manifests, not just the root ZCode catalog.
python3 "$SCRIPT_DIR/check-plugin-packaging.py" --root "$REPO_ROOT"
echo "  OK native plugin/marketplace manifest"

python3 - <<'PY'
import re
from pathlib import Path

skills = sorted(Path('skills').glob('*/SKILL.md'))
commands = sorted(Path('skills/story-setup/references/zcode/commands').glob('*.md'))
assert len(skills) == 13, f'expected 13 skills, got {len(skills)}'
assert len(commands) == 13, f'expected 13 commands, got {len(commands)}'
expected = {p.parent.name for p in skills}
assert {p.stem for p in commands} == expected

for skill in skills:
    text = skill.read_text(encoding='utf-8')
    front = text.split('---', 2)[1]
    name = re.search(r'^name:\s*["\']?([^"\'\n]+)', front, re.M)
    desc = re.search(r'^description:\s*(.+)$', front, re.M)
    assert name and name.group(1).strip() == skill.parent.name, skill
    assert desc, f'{skill}: missing description'
    value = desc.group(1).strip().strip('"\'')
    assert len(value) <= 1024, f'{skill}: description too long'

allowed = {'description', 'argument-hint', 'allowed-tools', 'model', 'skills', 'disable-noninteractive'}
for command in commands:
    assert re.fullmatch(r'[a-z0-9][a-z0-9_:-]{0,63}', command.stem), command
    text = command.read_text(encoding='utf-8')
    assert text.startswith('---\n'), command
    front, body = text.split('---', 2)[1:]
    keys = {line.split(':', 1)[0] for line in front.splitlines() if ':' in line}
    assert keys <= allowed, f'{command}: unsupported keys {keys - allowed}'
    assert 'description' in keys and 'skills' in keys
    assert '$ARGUMENTS' in body
PY
echo "  OK 13 Skills + 13 Commands (schema and one-to-one names)"

python3 - <<'PY'
import json
from pathlib import Path

supported = {'SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PermissionRequest', 'PostToolUse', 'PostToolUseFailure', 'Stop'}
# 事件 → 允许的 handler。只按集合校验 handler 名（"名字在白名单里就行"）等于放过
# "SessionStart 挂 post-tool-prose-check" 这类整块复制粘贴后忘改 args[1] 的错：
# story_zcode_hook.js 只看 process.argv[2] 分派，从不比对 hook_event_name，运行时表现是
# 会话起点静默不注入上下文 / 写后检查拿到错 payload 后什么都不报。必须逐事件锁死。
EVENT_HANDLERS = {
    'SessionStart': {'session-start'},
    'PreToolUse': {'pre-tool-prose-guard', 'pre-tool-commit-advisory'},
    'PostToolUse': {'post-tool-prose-check'},
}
plugin = json.loads(Path('skills/story-setup/references/zcode/hooks/hooks.json').read_text())['hooks']
config = json.loads(Path('skills/story-setup/references/zcode/config.json.patch').read_text())['hooks']
assert config['enabled'] is True
assert set(plugin) == set(EVENT_HANDLERS)
assert set(config['events']) == set(plugin)
assert set(plugin) <= supported

def flatten(events):
    # 必须把事件名一起带出来：丢掉 event key 就没法把 handler 绑回它该服务的事件。
    return [(event, hook) for event, groups in events.items() for group in groups for hook in group['hooks']]

plugin_hooks = flatten(plugin)
workspace_hooks = flatten(config['events'])
assert len(plugin_hooks) == len(workspace_hooks) == 4
expected_routes = {(event, handler) for event, handlers in EVENT_HANDLERS.items() for handler in handlers}
# 两份注册各自独立对表：只改 hooks.json 不改 config.json.patch（或反之）的漂移同样要红，
# 二者是手工分开维护的，且 check-shared-files.sh 刻意把 hooks.json 排除在字节 parity 之外。
for source, pairs in (('hooks.json', plugin_hooks), ('config.json.patch', workspace_hooks)):
    for event, hook in pairs:
        assert set(hook) <= {'type', 'command', 'args', 'timeoutMs'}
        assert hook['type'] == 'process' and hook['command'] == 'node'
        assert hook['args'][1] in EVENT_HANDLERS[event], (
            f'{source}: {event} 路由到了错误的 handler', hook['args'][1], sorted(EVENT_HANDLERS[event]))
    routes = {(event, hook['args'][1]) for event, hook in pairs}
    assert routes == expected_routes, (
        f'{source}: event→handler 注册漂移', sorted(expected_routes - routes), sorted(routes - expected_routes))
post_groups = plugin['PostToolUse']
assert len(post_groups) == 1 and post_groups[0]['matcher'] == 'Bash|Write|Edit|ApplyPatch'
# 路由测试（防"直调 runner 绕过 matcher"的假绿）：pre-tool-prose-guard 的 matcher 在 plugin
# 与 workspace config 两份里必须一致，且能路由 test-zcode-hooks 会喂给它的每种工具——含
# ApplyPatch（写正文的 apply-patch 目标必须真被 matcher 送进 handler，而不只是 runner 直调可拦）。
import re
def prose_guard_matcher(events):
    for group in events['PreToolUse']:
        if any(h['args'][1] == 'pre-tool-prose-guard' for h in group['hooks']):
            return group['matcher']
    return None
mc = prose_guard_matcher(config['events'])
mp = prose_guard_matcher(plugin)
assert mc is not None and mc == mp, ('pre-tool-prose-guard matcher drift between config and plugin', mc, mp)
for tool in ('Bash', 'Write', 'Edit', 'ApplyPatch'):
    assert re.search(mc, tool), ('pre-tool-prose-guard matcher does not route tool', tool, mc)
for _event, hook in plugin_hooks:
    assert hook['args'][0].startswith('${ZCODE_PLUGIN_ROOT}/')
for _event, hook in workspace_hooks:
    assert hook['args'][0] == '${ZCODE_PROJECT_DIR}/.zcode/hooks/story_zcode_hook.js'
PY
echo "  OK supported events + strict process-hook shape"

if grep -RqsE 'PreCompact|PostCompact|SessionEnd|SubagentStop|Notification' "$ROOT/hooks" "$ROOT/config.json.patch"; then
  fail "ZCode adapter contains unsupported hook events"
fi
[ ! -e "$ROOT/agents" ] || fail "ZCode 3.3.4 must not ship project agents"
[ ! -e "$ROOT/rules" ] || fail "ZCode has no .zcode/rules discovery surface"

assert_grep '\$story-long-write|\$story-setup' "$ROOT/AGENTS.md.tmpl" 'ZCode AGENTS template must document $skill invocation'
assert_grep 'project custom agents unavailable.*solo|不执行项目.*custom agents' "$ROOT/AGENTS.md.tmpl" "ZCode AGENTS template must document solo fallback"
assert_grep 'target_cli = zcode|target_cli.*zcode' skills/story-setup/SKILL.md "story-setup must document zcode target_cli"
assert_grep 'references/zcode/config\.json\.patch' skills/story-setup/SKILL.md "story-setup manifest missing ZCode config patch"
# 组合安装验证代理（CI 无 ZCode 运行时）：插件 manifest 与 workspace config 注册同一批 hooks，
# 部署算法必须记录二者互斥（装插件则跳过 config hooks 合并），否则 PreToolUse/PostToolUse 双触发。
assert_grep 'hooks 互斥' skills/story-setup/SKILL.md "story-setup must document the plugin/workspace hooks mutex (skip config hooks merge when plugin installed, avoid double-firing)"
assert_grep '\.zcode/skills/story-setup/references/agent-references' skills/story-setup/SKILL.md "story-setup missing ZCode reference path"

for skill in story-long-write story-short-write story-long-analyze story-import story-deslop story-review; do
  assert_grep 'ZCode 3\.3\.4|\.zcode/' "skills/$skill/SKILL.md" "$skill must document ZCode fallback"
done

echo "  OK deployment instructions + explicit capability boundaries"
echo ""
echo "OK: ZCode adapter checks passed"
