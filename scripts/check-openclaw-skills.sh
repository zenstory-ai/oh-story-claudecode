#!/usr/bin/env bash
# check-openclaw-skills.sh — OpenClaw AgentSkills/frontmatter compatibility checks.
# Static by default; set OPENCLAW_REAL_CHECK=1 to run an isolated OpenClaw CLI
# smoke test with a temporary profile and workspace.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$REPO_ROOT" ]; then
  echo "Error: not in a git repository" >&2
  exit 1
fi

SKILLS_DIR="$REPO_ROOT/skills"
EXPECTED_COUNT=14

echo "OpenClaw skills check"
echo "====================="
echo "Repo: $REPO_ROOT"

python3 - "$SKILLS_DIR" "$EXPECTED_COUNT" <<'PY'
from pathlib import Path
import json
import re
import sys

skills_dir = Path(sys.argv[1])
expected = int(sys.argv[2])
failures: list[str] = []
skill_files = sorted(skills_dir.glob('*/SKILL.md'))

if len(skill_files) != expected:
    failures.append(f'expected {expected} SKILL.md files, found {len(skill_files)}')

frontmatter_re = re.compile(r'^---\n(.*?)\n---\n', re.S)
for path in skill_files:
    rel = path.relative_to(skills_dir.parent)
    text = path.read_text(encoding='utf-8')
    match = frontmatter_re.match(text)
    if not match:
        failures.append(f'{rel}: missing opening YAML frontmatter block')
        continue
    raw = match.group(1)
    lines = raw.splitlines()
    for idx, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if line[:1].isspace():
            failures.append(f'{rel}:{idx}: repository compatibility profile requires single-line top-level keys; found indented/block line')
        if re.match(r'^(description|metadata):\s*[>|]', line):
            failures.append(f'{rel}:{idx}: repository compatibility profile requires single-line {line.split(":",1)[0]}')
    data = {}
    for line in lines:
        if not line.strip() or line.lstrip().startswith('#') or line[:1].isspace():
            continue
        if ':' not in line:
            failures.append(f'{rel}: invalid frontmatter line without colon: {line!r}')
            continue
        key, value = line.split(':', 1)
        value = value.strip()
        try:
            data[key] = json.loads(value) if value.startswith(('"', '{', '[', 'true', 'false', 'null')) else value
        except Exception:
            # OpenClaw accepts YAML/JSON5. This repository deliberately keeps a
            # strict-JSON single-line subset for older/fallback parser compatibility.
            data[key] = value.strip('"')
    name = data.get('name')
    desc = data.get('description')
    if not isinstance(name, str) or not name.strip():
        failures.append(f'{rel}: missing string name')
    if name and name != path.parent.name:
        failures.append(f'{rel}: name {name!r} must match directory {path.parent.name!r}')
    if not isinstance(desc, str) or not desc.strip():
        failures.append(f'{rel}: missing string description')
    elif '\n' in desc:
        failures.append(f'{rel}: description must be single-line')
    meta_lines = [line for line in lines if line.startswith('metadata:')]
    if not meta_lines:
        failures.append(f'{rel}: repository skills must declare metadata.openclaw source/gating metadata')
    elif len(meta_lines) > 1:
        failures.append(f'{rel}: duplicate metadata keys')
    else:
        raw_meta = meta_lines[0].split(':', 1)[1].strip()
        if not (raw_meta.startswith('{') and raw_meta.endswith('}')):
            failures.append(f'{rel}: repository compatibility profile requires a single-line strict-JSON metadata object')
        else:
            try:
                parsed_meta = json.loads(raw_meta)
            except Exception as exc:
                failures.append(f'{rel}: strict metadata JSON parse failed: {exc}')
            else:
                oc = parsed_meta.get('openclaw')
                if not isinstance(oc, dict):
                    failures.append(f'{rel}: metadata.openclaw must be an object')
                else:
                    source = oc.get('source')
                    if not isinstance(source, str) or not source:
                        failures.append(f'{rel}: metadata.openclaw.source must be a non-empty string')
                    os_filter = oc.get('os')
                    if os_filter is not None and (
                        not isinstance(os_filter, list)
                        or not all(x in ('darwin', 'linux', 'win32') for x in os_filter)
                    ):
                        failures.append(f'{rel}: metadata.openclaw.os must contain only darwin/linux/win32')
                    requires = oc.get('requires')
                    if requires is not None:
                        if not isinstance(requires, dict):
                            failures.append(f'{rel}: metadata.openclaw.requires must be an object')
                        else:
                            for key in ('bins', 'anyBins', 'env', 'config'):
                                value = requires.get(key)
                                if value is not None and (
                                    not isinstance(value, list)
                                    or not all(isinstance(x, str) for x in value)
                                ):
                                    failures.append(f'{rel}: metadata.openclaw.requires.{key} must be string[]')

if failures:
    print('FAIL: OpenClaw skill compatibility errors:', file=sys.stderr)
    for item in failures:
        print(f'  - {item}', file=sys.stderr)
    sys.exit(1)

for path in skill_files:
    print(f'  OK {path.parent.name}')
print(f'OK: {len(skill_files)} skills have OpenClaw-compatible single-line frontmatter')
PY

if [ "${OPENCLAW_REAL_CHECK:-0}" = "1" ]; then
  if ! command -v openclaw >/dev/null 2>&1; then
    echo "FAIL: OPENCLAW_REAL_CHECK=1 but openclaw is not on PATH" >&2
    exit 1
  fi
  TMP_DIR="$(mktemp -d)"
  PROFILE="ohstory-check-$$"
  cleanup() {
    rm -rf "$TMP_DIR"
  }
  trap cleanup EXIT

  # Official OpenClaw path overrides keep profiles, config, credentials, and
  # sessions inside the disposable test root instead of the caller's HOME.
  export OPENCLAW_HOME="$TMP_DIR/home"
  export OPENCLAW_STATE_DIR="$TMP_DIR/state"
  export OPENCLAW_CONFIG_PATH="$TMP_DIR/state/openclaw.json"

  mkdir -p "$TMP_DIR/workspace"
  echo "  OpenClaw: $(openclaw --version)"
  cp -R "$SKILLS_DIR" "$TMP_DIR/workspace/skills"
  # Exercise the documented top-level metadata.openclaw.os gate with a platform
  # that intentionally excludes the current runner.
  case "$(uname -s)" in
    Darwin) PROBE_OS="linux" ;;
    *) PROBE_OS="darwin" ;;
  esac
  mkdir -p "$TMP_DIR/workspace/skills/ohstory-os-probe"
  cat >"$TMP_DIR/workspace/skills/ohstory-os-probe/SKILL.md" <<EOF
---
name: ohstory-os-probe
description: OpenClaw CLI compatibility probe for the documented OS eligibility gate.
metadata: {"openclaw":{"os":["$PROBE_OS"]}}
---

Compatibility probe only.
EOF
  openclaw --profile "$PROFILE" agents add ohstory-check \
    --workspace "$TMP_DIR/workspace" \
    --agent-dir "$TMP_DIR/agent" \
    --model "test/model" \
    --non-interactive \
    --json >/dev/null
  LIST_JSON="$TMP_DIR/skills.json"
  openclaw --profile "$PROFILE" skills list --agent ohstory-check --json >"$LIST_JSON"
  python3 - "$LIST_JSON" "$EXPECTED_COUNT" "$TMP_DIR/workspace/skills" <<'PY'
import json
import os
import shutil
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
expected = int(sys.argv[2])
skills_dir = Path(sys.argv[3])
skills = data.get('skills', [])
story = [s for s in skills if s.get('name') == 'browser-cdp' or str(s.get('name', '')).startswith('story')]
errors = []
if data.get('workspaceDir') is None:
    errors.append('missing workspaceDir in openclaw skills output')
if len(story) != expected:
    errors.append(f'expected {expected} story skills from temporary workspace, got {len(story)}')

def declared_openclaw(name: str) -> dict:
    path = skills_dir / name / 'SKILL.md'
    metadata_line = next(
        (line for line in path.read_text(encoding='utf-8').splitlines() if line.startswith('metadata:')),
        '',
    )
    if not metadata_line:
        return {}
    metadata = json.loads(metadata_line.split(':', 1)[1].strip())
    return metadata.get('openclaw', {})

for item in story:
    name = str(item.get('name', ''))
    if item.get('source') != 'openclaw-workspace':
        errors.append(f'{name}: expected source openclaw-workspace, got {item.get("source")}')
    openclaw = declared_openclaw(name)
    requires = openclaw.get('requires', {})
    actual_missing = item.get('missing') or {}
    expected_bins = sorted(binary for binary in requires.get('bins', []) if shutil.which(binary) is None)
    expected_env = sorted(key for key in requires.get('env', []) if not os.environ.get(key))
    any_bins = requires.get('anyBins', [])
    expected_any_bins = sorted(any_bins) if any_bins and not any(shutil.which(binary) for binary in any_bins) else []
    for key, expected_values in (
        ('bins', expected_bins),
        ('env', expected_env),
        ('anyBins', expected_any_bins),
    ):
        actual_values = sorted(actual_missing.get(key) or [])
        if actual_values != expected_values:
            errors.append(f'{name}: missing.{key} expected {expected_values}, got {actual_values}')
    declared_os = openclaw.get('os', [])
    for key, declared in (('config', requires.get('config', [])), ('os', declared_os)):
        undeclared = set(actual_missing.get(key) or []) - set(declared or [])
        if undeclared:
            errors.append(f'{name}: CLI reported undeclared missing.{key}: {sorted(undeclared)}')
    has_missing = any(actual_missing.get(key) for key in ('bins', 'anyBins', 'env', 'config', 'os'))
    if item.get('eligible') is not (not has_missing):
        errors.append(f'{name}: eligible={item.get("eligible")} inconsistent with missing={actual_missing}')

probe = next((s for s in skills if s.get('name') == 'ohstory-os-probe'), None)
if probe is None:
    errors.append('OpenClaw CLI did not report the OS-gated compatibility probe')
else:
    probe_os = declared_openclaw('ohstory-os-probe').get('os', [])
    actual_os = (probe.get('missing') or {}).get('os') or []
    if sorted(actual_os) != sorted(probe_os):
        errors.append(f'OS probe: missing.os expected {probe_os}, got {actual_os}')
    if probe.get('eligible') is not False:
        errors.append(f'OS probe: expected eligible=False, got {probe.get("eligible")}')
if errors:
    for err in errors:
        print(f'FAIL: {err}', file=sys.stderr)
    sys.exit(1)
print(f'OK: OpenClaw CLI discovered {len(story)} workspace story skills')
PY
fi

echo "OK: OpenClaw skills checks passed"
