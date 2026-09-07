#!/usr/bin/env bash
# test-opencode-cli-e2e.sh — real OpenCode CLI smoke for project-local story setup assets.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT="$REPO_ROOT/skills/story-setup/references/opencode"
TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/ohstory-opencode-e2e.XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT
CLI_HOME="$TMP_ROOT/home"

fail() { echo "FAIL: $*" >&2; exit 1; }

if ! command -v opencode >/dev/null 2>&1; then
  fail "opencode CLI not found on PATH. Install with: npm install -g opencode-ai"
fi

run_opencode() {
  HOME="$CLI_HOME" \
    XDG_CONFIG_HOME="$CLI_HOME/.config" \
    XDG_DATA_HOME="$CLI_HOME/.local/share" \
    XDG_CACHE_HOME="$CLI_HOME/.cache" \
    XDG_STATE_HOME="$CLI_HOME/.local/state" \
    command opencode "$@"
}

mkdir -p "$CLI_HOME"

echo "OpenCode CLI E2E"
echo "================"
echo "Repo: $REPO_ROOT"
echo "OpenCode: $(command -v opencode) ($(run_opencode --version))"

cd "$REPO_ROOT"

echo "  Checking repo-local skill discovery"
run_opencode debug skill >"$TMP_ROOT/repo-skills.json"
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
    "story-inspiration-distill",
    "story-long-analyze",
    "story-long-scan",
    "story-long-write",
    "story-review",
    "story-runtime-guard",
    "story-setup",
    "story-short-analyze",
    "story-short-scan",
    "story-short-write",
}

data = json.loads(Path(sys.argv[1]).read_text())
repo_root = Path(sys.argv[2]).resolve()
items = {
    item.get("name") or item.get("id"): item
    for item in data
    if isinstance(item, dict)
}
names = set(items)
missing = sorted(expected - names)
if missing:
    raise SystemExit(f"missing OpenCode-discovered story skills: {missing}")
for name in expected:
    location = items[name].get("location")
    if not isinstance(location, str):
        raise SystemExit(f"{name}: OpenCode output omitted skill location")
    actual = Path(location).resolve()
    wanted = (repo_root / "skills" / name / "SKILL.md").resolve()
    if actual != wanted:
        raise SystemExit(f"{name}: expected location {wanted}, got {actual}")
print(f"    OK {len(expected)} story skills discovered")
PY

PROJECT="$TMP_ROOT/project"
mkdir -p \
  "$PROJECT/.opencode/agents" \
  "$PROJECT/.opencode/commands" \
  "$PROJECT/.opencode/plugins" \
  "$PROJECT/skills/story-setup/references"

cp -R "$ROOT/agents/." "$PROJECT/.opencode/agents/"
cp -R "$ROOT/commands/." "$PROJECT/.opencode/commands/"
cp "$ROOT/plugin.ts" "$PROJECT/.opencode/plugins/story-hooks.ts"
cp "$ROOT/opencode.json.patch" "$PROJECT/opencode.json"
cp "$ROOT/AGENTS.md.tmpl" "$PROJECT/AGENTS.md"
cp -R "$REPO_ROOT/skills/story-setup/references/agent-references" \
  "$PROJECT/skills/story-setup/references/agent-references"

echo "  Checking deployed project config/agents/commands/plugin"
(
  cd "$PROJECT"
  run_opencode debug config >"$TMP_ROOT/project-config.json"
)

python3 - "$TMP_ROOT/project-config.json" <<'PY'
import json
import sys
from pathlib import Path

cfg = json.loads(Path(sys.argv[1]).read_text())

expected_commands = {
    "browser-cdp",
    "story",
    "story-cover",
    "story-deslop",
    "story-import",
    "story-inspiration-distill",
    "story-long-analyze",
    "story-long-scan",
    "story-long-write",
    "story-review",
    "story-runtime-guard",
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

plugins = [str(item) for item in cfg.get("plugin") or []]
if not any(item == "./.opencode/plugins/story-hooks.ts" or item.endswith("/.opencode/plugins/story-hooks.ts") for item in plugins):
    raise SystemExit(f"story-hooks plugin not loaded: {plugins}")

commands = set((cfg.get("command") or {}).keys())
agents = set((cfg.get("agent") or {}).keys())
missing_commands = sorted(expected_commands - commands)
missing_agents = sorted(expected_agents - agents)
if missing_commands:
    raise SystemExit(f"missing OpenCode commands: {missing_commands}")
if missing_agents:
    raise SystemExit(f"missing OpenCode agents: {missing_agents}")

agent = (cfg.get("agent") or {}).get("story-explorer") or {}
agent_name = agent.get("name") or agent.get("id")
if agent_name not in (None, "story-explorer"):
    raise SystemExit(f"resolved story-explorer returned wrong name/id: {agent_name!r}")
if agent.get("mode") != "subagent":
    raise SystemExit(f"story-explorer mode should be subagent, got {agent.get('mode')!r}")
if "小说" not in json.dumps(agent, ensure_ascii=False) and "story" not in json.dumps(agent).lower():
    raise SystemExit("story-explorer prompt/description did not load story content")

print(f"    OK {len(expected_commands)} commands, {len(expected_agents)} agents, story-hooks plugin")
PY

echo ""
echo "OK: OpenCode CLI E2E passed"
