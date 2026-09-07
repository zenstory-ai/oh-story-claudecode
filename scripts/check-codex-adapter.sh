#!/usr/bin/env bash
# check-codex-adapter.sh — deterministic checks for the Codex adapter surface.
#
# Codex support here is repo skill discovery (.agents/skills symlink) plus
# `$story-setup` project deployment (.codex/agents + .codex/hooks). There is no
# materialized plugin package; agent TOMLs are generated from the Claude agent
# templates by scripts/generate-codex-agents.py.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
assert_file() { [ -f "$1" ] || fail "required file missing: $1"; }
assert_path() { [ -e "$1" ] || fail "required path missing: $1"; }
assert_grep() { grep -Eq "$1" "$2" || fail "$3 ($2)"; }

cd "$REPO_ROOT"

echo "Codex adapter check"
echo "==================="
echo "Repo: $REPO_ROOT"

CODEX_DIR="skills/story-setup/references/codex"
assert_path ".agents/skills"
assert_file "$CODEX_DIR/AGENTS.md.tmpl"
assert_file "$CODEX_DIR/hooks/hooks.json"
assert_file "$CODEX_DIR/hooks/story_codex_hook.py"
assert_file "$CODEX_DIR/hooks/run-story-hook.sh"
assert_file "$CODEX_DIR/hooks/run-story-hook.cmd"
assert_path "$CODEX_DIR/agents"
assert_file "scripts/generate-codex-agents.py"
assert_file "scripts/generate-codex-hooks.py"
assert_file "scripts/test-codex-hook-merge.py"
assert_file "skills/story-setup/scripts/merge-codex-hooks.py"

python3 -m json.tool "$CODEX_DIR/hooks/hooks.json" >/dev/null
python3 - <<'PY'
from pathlib import Path
for name in (
    'scripts/generate-codex-agents.py',
    'scripts/generate-codex-hooks.py',
    'skills/story-setup/references/codex/hooks/story_codex_hook.py',
):
    compile(Path(name).read_text(encoding='utf-8'), name, 'exec')
PY
python3 scripts/generate-codex-hooks.py --check
python3 scripts/test-codex-hook-merge.py

echo "  OK JSON/Python syntax"

# Windows encoding safety (issue #164 class): the hook carries Chinese 正文/细纲 over
# stdin/stdout, so it must use UTF-8 bytes, not Windows' ANSI code page text streams.
HOOK_PY="$CODEX_DIR/hooks/story_codex_hook.py"
# Walk the AST instead of grepping lines. A line-based read_text(/encoding= pair fails both ways:
# it reports a regression against a correct call wrapped over two lines (or against a comment that
# merely mentions .read_text()), and it accepts `p.read_text() + p.read_text(encoding="utf-8")[:0]`
# because the encoding token is somewhere on the line. The AST sees calls, never comments.
python3 - "$HOOK_PY" <<'PY'
import ast
import sys
from pathlib import Path

path = Path(sys.argv[1])
tree = ast.parse(path.read_text(encoding="utf-8"), str(path))


def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


required = {"sys.stdin.buffer.read", "sys.stdout.buffer.write"}
seen = set()
problems = []
for node in ast.walk(tree):
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        continue
    name = dotted(node.func)
    if name in required:
        seen.add(name)
    if name in ("sys.stdin.read", "sys.stdout.write"):
        problems.append(f"line {node.lineno}: text-mode {name}() (Windows ANSI hazard)")
    if node.func.attr == "read_text" and not any(kw.arg == "encoding" for kw in node.keywords):
        problems.append(f"line {node.lineno}: read_text() without encoding='utf-8' (Windows ANSI hazard)")
for name in sorted(required - seen):
    problems.append(f"missing UTF-8 byte stdio call: {name}()")
if problems:
    raise SystemExit("FAIL: Codex hook Windows encoding safety (issue #164):\n  " + "\n  ".join(problems))
PY

echo "  OK Windows encoding safety (UTF-8 stdio + file reads)"

# Prose backstop parity surface: Codex has no PostToolUse, so the light prose net runs at Stop
# (sweeping git-changed 正文) and continuity runs at SessionStart. These must stay present.
assert_grep 'def prose_net_findings' "$HOOK_PY" "Codex hook must carry the light prose net (parity with claude/opencode)"
assert_grep 'def find_changed_prose_files' "$HOOK_PY" "Codex Stop sweep must discover git-changed prose"
assert_grep 'def continuity_findings' "$HOOK_PY" "Codex hook must carry the continuity backstop (追踪 staleness + dup-title)"

echo "  OK prose backstop parity surface (Stop net + SessionStart continuity)"

# .agents/skills is a relative symlink to skills/ (the agentskills.io path Codex scans), so
# there is no second skill copy. Must be a valid relative symlink: an invalid/absolute one
# (openai/codex#11314) or a Windows no-symlinks text stub silently breaks discovery.
[ -L ".agents/skills" ] || fail ".agents/skills must be a symlink (got a regular file/dir; on Windows enable git core.symlinks)"
target="$(readlink .agents/skills)"
[ "$target" = "../skills" ] || fail ".agents/skills symlink target must be relative '../skills', got '$target'"
skill_count="$(find skills -maxdepth 2 -name SKILL.md | wc -l | tr -d ' ')"
[ "$skill_count" = "15" ] || fail "expected 15 skills, found $skill_count"
for skill in skills/*/SKILL.md; do
  name="$(basename "$(dirname "$skill")")"
  assert_file ".agents/skills/$name/SKILL.md"
done

echo "  OK .agents/skills discovery symlink ($skill_count skills)"

# Custom-agent TOMLs are generated deterministically from the Claude templates.
python3 scripts/generate-codex-agents.py --dest "$TMP_DIR/agents" >/dev/null
diff -qr "$TMP_DIR/agents" "$CODEX_DIR/agents" >/dev/null \
  || fail "generated Codex agents are stale; run scripts/generate-codex-agents.py"
if grep -RInE '当前 Claude 部署|(^|[^[:alnum:]_])/story(-[a-z0-9-]+)?' "$CODEX_DIR/agents"; then
  fail "generated Codex agents must use Codex platform wording and \$story* invocations"
fi

# A missing/empty source must fail before touching the destination. Otherwise a
# typo in --source silently prunes every generated TOML while returning success.
mkdir -p "$TMP_DIR/empty-source" "$TMP_DIR/safe-dest"
printf 'keep\n' > "$TMP_DIR/safe-dest/sentinel.toml"
if python3 scripts/generate-codex-agents.py \
  --source "$TMP_DIR/empty-source" --dest "$TMP_DIR/safe-dest" >/dev/null 2>&1; then
  fail "Codex generator must reject an empty source directory"
fi
assert_file "$TMP_DIR/safe-dest/sentinel.toml"

# A malformed later source must also fail before any earlier valid source is
# written. This locks the generator's validate-all-then-write behavior.
mkdir -p "$TMP_DIR/malformed-source" "$TMP_DIR/transactional-dest"
cat >"$TMP_DIR/malformed-source/a.md" <<'EOF'
---
name: a
description: valid first fixture
---
body
EOF
printf 'missing frontmatter\n' >"$TMP_DIR/malformed-source/b.md"
printf 'keep old a\n' >"$TMP_DIR/transactional-dest/a.toml"
printf 'keep sentinel\n' >"$TMP_DIR/transactional-dest/sentinel.toml"
cp -R "$TMP_DIR/transactional-dest" "$TMP_DIR/transactional-before"
if python3 scripts/generate-codex-agents.py \
  --source "$TMP_DIR/malformed-source" \
  --dest "$TMP_DIR/transactional-dest" >/dev/null 2>&1; then
  fail "Codex generator must reject malformed agent source"
fi
diff -qr "$TMP_DIR/transactional-before" "$TMP_DIR/transactional-dest" >/dev/null \
  || fail "Codex generator modified destination before validating all sources"

# A filesystem failure while publishing a later rendered file must not expose an
# earlier update.  Keep b.toml as a directory so the second write fails after
# a.toml has already been prepared.
mkdir -p "$TMP_DIR/write-failure-source" "$TMP_DIR/write-failure-dest/b.toml"
cat >"$TMP_DIR/write-failure-source/a.md" <<'EOF'
---
name: a
description: valid first fixture
---
new a body
EOF
cat >"$TMP_DIR/write-failure-source/b.md" <<'EOF'
---
name: b
description: valid second fixture
---
new b body
EOF
printf 'keep old a\n' > "$TMP_DIR/write-failure-dest/a.toml"
printf 'keep manual asset\n' > "$TMP_DIR/write-failure-dest/manual.txt"
cp -R "$TMP_DIR/write-failure-dest" "$TMP_DIR/write-failure-before"
if python3 scripts/generate-codex-agents.py \
  --source "$TMP_DIR/write-failure-source" \
  --dest "$TMP_DIR/write-failure-dest" >/dev/null 2>&1; then
  fail "Codex generator must fail when a generated target is a directory"
fi
diff -qr "$TMP_DIR/write-failure-before" "$TMP_DIR/write-failure-dest" >/dev/null \
  || fail "Codex generator exposed a partial update after a destination write failure"

# Also inject a failure during the second atomic commit (after a.toml was
# replaced) and verify the rollback restores every generated byte while keeping
# unrelated files in the destination directory.
python3 - "scripts/generate-codex-agents.py" "$TMP_DIR" <<'PY'
import importlib.util
import sys
from pathlib import Path

script = Path(sys.argv[1]).resolve()
dest = Path(sys.argv[2]) / "codex-commit-failure"
dest.mkdir()
(dest / "a.toml").write_text("old a\n", encoding="utf-8")
(dest / "b.toml").write_text("old b\n", encoding="utf-8")
(dest / "manual.txt").write_text("manual\n", encoding="utf-8")
before = {path.name: path.read_bytes() for path in dest.iterdir()}
spec = importlib.util.spec_from_file_location("generate_codex_atomic", script)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
real_replace = module.os.replace
calls = 0

def fail_second(src, dst):
    global calls
    calls += 1
    if calls == 2:
        raise OSError("injected second-commit failure")
    return real_replace(src, dst)

module.os.replace = fail_second
try:
    module.publish_rendered({"a.toml": "new a\n", "b.toml": "new b\n"}, dest)
except OSError:
    pass
else:
    raise SystemExit("Codex publisher did not surface injected commit failure")
after = {path.name: path.read_bytes() for path in dest.iterdir()}
if after != before:
    raise SystemExit("Codex publisher failed to roll back an interrupted commit")
PY

# A stale generated file that cannot be removed (immutable flag, lock, read-only
# mount) must not abort the rollback: every restorable file returns to its prior
# bytes and the un-removable file keeps its original content.
python3 - "scripts/generate-codex-agents.py" "$TMP_DIR" <<'PY'
import importlib.util
import sys
from pathlib import Path

script = Path(sys.argv[1]).resolve()
dest = Path(sys.argv[2]) / "codex-immutable-stale"
dest.mkdir()
(dest / "a.toml").write_text("old a\n", encoding="utf-8")
(dest / "stale.toml").write_text("old stale\n", encoding="utf-8")
(dest / "manual.txt").write_text("manual\n", encoding="utf-8")
before = {path.name: path.read_bytes() for path in dest.iterdir()}
spec = importlib.util.spec_from_file_location("generate_codex_immutable", script)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

real_unlink = Path.unlink
real_copy2 = module.shutil.copy2
# Key the fault on the file's OWN path, not its name: a real immutable file
# still allows being read/copied into the backup dir, so only writes and unlinks
# targeting stale.toml itself must fail. Keying on the name would also block the
# backup copy and abort before the rollback path is ever exercised.
victim = (dest / "stale.toml").resolve()


def blocked_unlink(self, *args, **kwargs):
    if self.resolve() == victim:
        raise PermissionError("simulated immutable stale file")
    return real_unlink(self, *args, **kwargs)


def blocked_copy2(src, dst, *args, **kwargs):
    if Path(dst).resolve() == victim:
        raise PermissionError("simulated immutable stale file")
    return real_copy2(src, dst, *args, **kwargs)


Path.unlink = blocked_unlink
module.shutil.copy2 = blocked_copy2
try:
    module.publish_rendered({"a.toml": "new a\n"}, dest)
except PermissionError:
    pass
else:
    raise SystemExit("Codex publisher did not surface the un-removable stale file")
finally:
    Path.unlink = real_unlink
    module.shutil.copy2 = real_copy2
after = {path.name: path.read_bytes() for path in dest.iterdir()}
if after != before:
    raise SystemExit(
        f"Codex rollback left a partial update past an un-removable file: {before} -> {after}"
    )
PY

# Agent names become output filenames. Reject path-like or filename-mismatched
# names before staging so hostile/mistyped frontmatter cannot escape --dest.
mkdir -p "$TMP_DIR/escape-source" "$TMP_DIR/escape-dest"
cat >"$TMP_DIR/escape-source/safe.md" <<'EOF'
---
name: ../victim
description: must be rejected
---
body
EOF
printf 'outside sentinel\n' > "$TMP_DIR/victim.toml"
if python3 scripts/generate-codex-agents.py \
  --source "$TMP_DIR/escape-source" \
  --dest "$TMP_DIR/escape-dest" >/dev/null 2>&1; then
  fail "Codex generator must reject path-like agent names"
fi
[ "$(cat "$TMP_DIR/victim.toml")" = "outside sentinel" ] \
  || fail "Codex generator let an agent name escape the destination"
[ -z "$(find "$TMP_DIR/escape-dest" -mindepth 1 -print -quit)" ] \
  || fail "Codex generator touched the destination for an invalid agent name"

python3 - <<'PY'
try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        from pip._vendor import tomli as tomllib
from pathlib import Path
expected = {
    'chapter-extractor', 'character-designer', 'consistency-checker',
    'narrative-writer', 'story-architect', 'story-explorer', 'story-researcher',
}
read_only = {'chapter-extractor', 'consistency-checker', 'story-explorer'}
found = set()
for path in sorted(Path('skills/story-setup/references/codex/agents').glob('*.toml')):
    data = tomllib.loads(path.read_text(encoding='utf-8'))
    for key in ('name', 'description', 'developer_instructions'):
        assert data.get(key), f'{path}: missing {key}'
    name = data['name']
    instructions = data['developer_instructions']
    assert path.name == f'{name}.toml', f'{path}: filename/name mismatch'
    assert '.codex/skills/story-setup/references/agent-references/' in instructions
    for stale in ('.claude/skills/', '.opencode/skills/', '{项目根}/skills/story-setup/references/agent-references/'):
        assert stale not in instructions, f'{path}: stale cross-CLI reference fallback {stale}'
    assert 'agent_type' in instructions, f'{path}: missing Codex agent_type guidance'
    assert 'subagent_type' not in instructions, f'{path}: leaked Claude subagent_type wording'
    assert 'unknown agent_type' in instructions, f'{path}: missing runtime fallback guidance'
    if name in read_only:
        assert data.get('sandbox_mode') == 'read-only', f'{path}: expected read-only sandbox'
    found.add(name)
assert found == expected, found
PY

echo "  OK Codex custom-agent TOML (schema + generator determinism)"

# The generated registration owns only root lookup + event routing. Interpreter probing and
# hook dispatch live in one launcher per platform instead of being copied into six JSON commands.
assert_grep 'for candidate in python3 python py' "$CODEX_DIR/hooks/run-story-hook.sh" "POSIX launcher must probe Python interpreters"
assert_grep 'for %%P in \(python3 python py\) do' "$CODEX_DIR/hooks/run-story-hook.cmd" "Windows launcher must probe the current interpreter list"
assert_grep 'set "PYBIN=%%P"' "$CODEX_DIR/hooks/run-story-hook.cmd" "Windows launcher must retain the first working interpreter"
if grep -q 'git rev-parse' "$CODEX_DIR/hooks/hooks.json" "$CODEX_DIR/hooks/run-story-hook.sh" "$CODEX_DIR/hooks/run-story-hook.cmd"; then
  fail "deployment hooks must not require git to launch story_codex_hook.py"
fi

# Every launcher must (a) propagate the resolved root to Python (CODEX_PROJECT_DIR=$PROJECT_ROOT)
# and (b) no-op when the hook file is absent instead of running "//.codex/..." (root="/"). And
# the Python hook must self-locate from __file__ so a Git Bash MSYS root still resolves on Windows.
#
# 每份注册的 event token 还必须与三个消费方的白名单逐一对齐：run-story-hook.sh 的 case、
# run-story-hook.cmd 的 if /I 链、story_codex_hook.py main() 的分派。少一处就是一个永久哑火的
# hook（launcher case 落到 *) exit 2，stdout/stderr 全空），而 command↔commandWindows 的一致性
# 断言只证明两边抄的是同一个错字。白名单从三个消费方解析出来比较，不在这里再抄第五份。
python3 - "$CODEX_DIR/hooks/hooks.json" "$CODEX_DIR/hooks/story_codex_hook.py" \
  "$CODEX_DIR/hooks/run-story-hook.sh" "$CODEX_DIR/hooks/run-story-hook.cmd" <<'PY'
import json, re, sys
from pathlib import Path
hooks = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["hooks"]
all_hooks = [h for arr in hooks.values() for blk in arr for h in blk["hooks"]]
assert all_hooks, "no launcher commands found"
registered = []
for h in all_hooks:
    c = h["command"]
    assert '.codex/hooks/run-story-hook.sh' in c, f"POSIX command must route through the shared launcher: {c}"
    assert 'python3 python py' not in c and 'story_codex_hook.py' not in c, f"registration duplicated launcher logic: {c}"
    w = h.get("commandWindows")
    assert w, f"hook missing commandWindows (Windows = cmd.exe /C): {c[:60]}"
    assert "run-story-hook.cmd" in w and "powershell -NoProfile" in w, f"Windows command must locate the shared launcher: {w}"
    assert "story_codex_hook.py" not in w and "python3" not in w, f"Windows registration duplicated launcher logic: {w}"
    posix_event = c.rsplit(" ", 1)[-1]
    assert f"'{posix_event}'" in w, f"command/commandWindows event mismatch: {posix_event} vs {w}"
    registered.append(posix_event)

# 同一个 handler 被注册两次 = 复制粘贴整块后忘了改 event token，另一个事件因此没有注册。
dupes = sorted({e for e in registered if registered.count(e) > 1})
assert not dupes, f"hooks.json registers the same event token more than once: {dupes}"

launcher_sh = Path(sys.argv[3]).read_text(encoding="utf-8")
launcher_cmd = Path(sys.argv[4]).read_text(encoding="utf-8")
hook_py = Path(sys.argv[2]).read_text(encoding="utf-8")

# 只在 case "$EVENT" in ... esac 这一段里收 arm，且把每个 arm 的 a|b|c 全部展开：
# 别的 case 块（比如探测 PYBIN）不会污染白名单，名单被改写成一行一个 arm 也照样解析。
case_block = re.search(r'case[ \t]+"\$EVENT"[ \t]+in(.*?)esac', launcher_sh, re.S)
assert case_block, 'run-story-hook.sh must gate "$EVENT" with a case allowlist'
sh_tokens = set()
for arm in re.findall(r'^[ \t]*([a-z0-9|-]+)\)', case_block.group(1), re.M):
    sh_tokens.update(arm.split("|"))
allowed = {
    "run-story-hook.sh": sh_tokens,
    "run-story-hook.cmd": set(re.findall(r'"%EVENT%"=="([a-z0-9-]+)"', launcher_cmd)),
    "story_codex_hook.py": set(re.findall(r'event == "([a-z0-9-]+)"', hook_py)),
}
for name, tokens in allowed.items():
    assert tokens, f"{name}: no event allowlist found (the parser or the file shape changed)"
    assert tokens == set(registered), (
        f"event token drift between hooks.json and {name}: "
        f"registered-only={sorted(set(registered) - tokens)}, {name}-only={sorted(tokens - set(registered))}"
    )

assert "Path(__file__)" in hook_py and "_deployed_root_from_file" in hook_py, \
    "story_codex_hook.py must self-locate the project root from __file__ (Windows MSYS-path safety)"
PY

echo "  OK generated launcher routing + Python self-location + cmd.exe commandWindows"

# Reference-path contract: generated Codex agents use only the bundle story-setup deploys.
python3 - "$CODEX_DIR/agents" <<'PY'
import sys
from pathlib import Path
for path in sorted(Path(sys.argv[1]).glob("*.toml")):
    text = path.read_text(encoding="utf-8")
    if "1. `{项目根}/" not in text:
        continue  # this agent has no numbered reference list
    assert text.count("1. `{项目根}/.codex/skills/story-setup/references/agent-references/") == 1, \
        f"{path.name}: numbered reference list must contain the canonical Codex path once"
    for stale in (".claude/skills/", ".opencode/skills/", "{项目根}/skills/story-setup/references/agent-references/"):
        assert stale not in text, f"{path.name}: stale cross-CLI reference fallback {stale}"
PY

echo "  OK Codex agent canonical reference path"

assert_grep '\$story-setup|\$story-long-write|/skills' "$CODEX_DIR/AGENTS.md.tmpl" "Codex AGENTS template must mention skill invocation"
assert_grep '\.codex/agents/\*\.toml' "$CODEX_DIR/AGENTS.md.tmpl" "Codex AGENTS template must mention custom agent location"
assert_grep '\.codex/hooks\.json' "$CODEX_DIR/AGENTS.md.tmpl" "Codex AGENTS template must mention hooks location"
assert_grep 'references/codex' skills/story-setup/SKILL.md "story-setup must document Codex references"
assert_grep 'target_cli:.*codex|codex.*target_cli' skills/story-setup/SKILL.md "story-setup must document codex target_cli"
assert_grep '\.codex/agents|\.codex/hooks\.json' skills/story-review/SKILL.md "story-review must check Codex agents"

echo "  OK Codex docs/instruction anchors"
echo ""
echo "OK: Codex adapter checks passed"
