#!/usr/bin/env bash
# Deterministic checks for the Reasonix native plugin manifest (issue #204/#252).
# Reasonix (DeepSeek-Reasonix CLI) reads a root reasonix-plugin.json (Manifest v2:
# apiVersion = "reasonix.io/plugin/v2") and scans project skill roots.
# Static by default; set REASONIX_REAL_CHECK=1 to invoke the installed Reasonix CLI
# in an isolated REASONIX_HOME for plugin install/doctor and workspace skill discovery.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

fail() { echo "FAIL: $*" >&2; exit 1; }

echo "Reasonix adapter check"
echo "======================"
echo "Repo: $REPO_ROOT"

[ -f reasonix-plugin.json ] || fail "reasonix-plugin.json missing"
python3 -m json.tool reasonix-plugin.json >/dev/null || fail "reasonix-plugin.json is not valid JSON"

python3 - <<'PY'
import json, re
from pathlib import Path

manifest = json.loads(Path('reasonix-plugin.json').read_text())
assert manifest.get('apiVersion') == 'reasonix.io/plugin/v2', f"apiVersion must be 'reasonix.io/plugin/v2', got {manifest.get('apiVersion')!r}"
assert re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,127}', manifest.get('name', '')), f"bad name: {manifest.get('name')!r}"
assert manifest['name'] == 'oh-story', manifest['name']
assert manifest['skills'] == 'skills', manifest.get('skills')
assert isinstance(manifest.get('description'), str) and manifest['description'], 'description required'
version = Path('skills/story/VERSION').read_text().strip()
assert manifest['version'] == version, f"version {manifest['version']!r} must match skills/story/VERSION {version!r}"
# The manifest promises the skills under `skills`; keep it honest.
skills = sorted(Path('skills').glob('*/SKILL.md'))
assert len(skills) == 14, f'expected 14 skills, got {len(skills)}'
PY
echo "  OK reasonix-plugin.json (Manifest v2 schema + version pin + 14 Skills)"

if [ "${REASONIX_REAL_CHECK:-0}" = "1" ]; then
  command -v reasonix >/dev/null 2>&1 \
    || fail "REASONIX_REAL_CHECK=1 but reasonix is not on PATH"
  TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ohstory-reasonix-check.XXXXXX")"
  trap 'rm -rf "$TMP_DIR"' EXIT
  mkdir -p "$TMP_DIR/plugin-home" "$TMP_DIR/project-home" "$TMP_DIR/empty-workspace" "$TMP_DIR/workspace/.agents"
  echo "  Reasonix: $(reasonix --version)"

  # 1. Native plugin package lifecycle (Manifest v2 install + plugin doctor + capability discovery)
  DRY_JSON="$TMP_DIR/plugin-dry-run.json"
  REASONIX_HOME="$TMP_DIR/plugin-home" reasonix plugin install "$REPO_ROOT" --dry-run >"$DRY_JSON"
  INSTALL_JSON="$TMP_DIR/plugin-install.json"
  REASONIX_HOME="$TMP_DIR/plugin-home" reasonix plugin install "$REPO_ROOT" --yes >"$INSTALL_JSON"
  REASONIX_HOME="$TMP_DIR/plugin-home" reasonix plugin doctor oh-story >/dev/null
  PLUGIN_CAP_JSON="$TMP_DIR/plugin-capabilities.json"
  (cd "$TMP_DIR/empty-workspace" && REASONIX_HOME="$TMP_DIR/plugin-home" reasonix doctor capabilities --json >"$PLUGIN_CAP_JSON")

  python3 - "$DRY_JSON" "$INSTALL_JSON" "$PLUGIN_CAP_JSON" "$REPO_ROOT" <<'PY'
import json
import sys
from pathlib import Path

dry = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
installed = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
caps = json.loads(Path(sys.argv[3]).read_text(encoding='utf-8'))
repo_root = Path(sys.argv[4])
expected_skills = {p.parent.name for p in (repo_root / 'skills').glob('*/SKILL.md')}
version = (repo_root / 'skills/story/VERSION').read_text(encoding='utf-8').strip()

for label, payload, expected_status, expected_applied in (
    ('dry-run', dry, 'planned', False),
    ('install', installed, 'done', True),
):
    assert payload.get('ok') is True, f'{label}: expected ok=True, got {payload}'
    assert payload.get('status') == expected_status, f'{label}: unexpected status {payload.get("status")!r}'
    assert payload.get('applied') is expected_applied, f'{label}: unexpected applied {payload.get("applied")!r}'
    actions = payload.get('actions') or []
    assert len(actions) == 1, f'{label}: expected 1 action, got {actions}'
    action = actions[0]
    assert action.get('name') == 'oh-story', action
    assert action.get('manifestKind') == 'reasonix', action
    assert action.get('compatibility') == 'full', action
    assert action.get('skillCount') == len(expected_skills), action
    assert action.get('version') == version, action

summary = caps.get('summary') or {}
assert summary.get('errors') == 0, f'plugin capabilities reported errors: {caps}'
packages = (caps.get('plugins') or {}).get('packages') or []
oh_story = [pkg for pkg in packages if pkg.get('name') == 'oh-story']
assert len(oh_story) == 1, f'expected oh-story in plugins.packages, got {packages}'
pkg = oh_story[0]
assert pkg.get('enabled') is True and pkg.get('status') == 'ok', pkg
assert pkg.get('manifest_kind') == 'reasonix' and pkg.get('skills') == len(expected_skills), pkg

entries = {
    entry.get('name'): entry
    for entry in (caps.get('skills') or {}).get('entries') or []
    if isinstance(entry, dict)
}
missing = sorted(expected_skills - set(entries))
assert not missing, f'missing plugin-discovered skills: {missing}'
for name in sorted(expected_skills):
    entry = entries[name]
    assert entry.get('status') == 'winner', f'{name}: expected status=winner, got {entry}'
    assert f'/plugins/oh-story/skills/{name}/SKILL.md' in str(entry.get('path', '')), f'{name}: unexpected plugin path {entry}'
PY
  echo "  OK Reasonix CLI native plugin install + doctor + 14 plugin skills discovered"

  # 2. Project-level story-setup deployment (.agents/skills -> ../skills)
  cp -R "$REPO_ROOT/skills" "$TMP_DIR/workspace/skills"
  ln -s ../skills "$TMP_DIR/workspace/.agents/skills"
  PROJECT_CAP_JSON="$TMP_DIR/project-capabilities.json"
  (cd "$TMP_DIR/workspace" && REASONIX_HOME="$TMP_DIR/project-home" reasonix doctor capabilities --json >"$PROJECT_CAP_JSON")

  python3 - "$PROJECT_CAP_JSON" "$REPO_ROOT" <<'PY'
import json
import sys
from pathlib import Path

caps = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
repo_root = Path(sys.argv[2])
expected_skills = {p.parent.name for p in (repo_root / 'skills').glob('*/SKILL.md')}

summary = caps.get('summary') or {}
assert summary.get('errors') == 0, f'project capabilities reported errors: {caps}'
roots = (caps.get('skills') or {}).get('roots') or []
agents_roots = [r for r in roots if r.get('path') == '<workspace>/.agents/skills']
assert len(agents_roots) == 1 and agents_roots[0].get('status') == 'ok', f'expected active <workspace>/.agents/skills root, got {roots}'

entries = {
    entry.get('name'): entry
    for entry in (caps.get('skills') or {}).get('entries') or []
    if isinstance(entry, dict)
}
missing = sorted(expected_skills - set(entries))
assert not missing, f'missing workspace-discovered skills: {missing}'
for name in sorted(expected_skills):
    entry = entries[name]
    assert entry.get('scope') == 'project', f'{name}: expected scope=project, got {entry}'
    assert entry.get('status') == 'winner', f'{name}: expected status=winner, got {entry}'
    assert entry.get('path') == f'<workspace>/.agents/skills/{name}/SKILL.md', f'{name}: unexpected workspace path {entry}'
PY
  echo "  OK Reasonix CLI workspace .agents/skills discovery (14 project skills)"
fi

echo ""
echo "OK: Reasonix adapter checks passed"
