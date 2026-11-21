#!/usr/bin/env python3
"""Behavior regression for v17 -> current Codex hook registration upgrades."""

from __future__ import annotations

import copy
import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MERGER_PATH = ROOT / "skills/story-setup/scripts/merge-hooks.js"
TEMPLATE_PATH = ROOT / "skills/story-setup/references/codex/hooks/hooks.json"


def run_merger(existing_obj: object, template_obj: object, root: Path, name: str):
    existing_path = root / f"{name}-existing.json"
    template_path = root / f"{name}-template.json"
    output_path = root / f"{name}-output.json"
    existing_path.write_text(json.dumps(existing_obj, ensure_ascii=False), encoding="utf-8")
    template_path.write_text(json.dumps(template_obj, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run(
        [
            "node",
            str(MERGER_PATH),
            "--host",
            "codex",
            "--existing",
            str(existing_path),
            "--template",
            str(template_path),
            "--output",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc, output_path


def is_story_setup_hook(hook: dict[str, object]) -> bool:
    markers = (
        ".codex/hooks/story_codex_hook.py",
        ".codex/hooks/run-story-hook.sh",
        ".codex/hooks/run-story-hook.cmd",
    )
    commands = [
        str(hook.get(key, "")).lower().replace("\\", "/")
        for key in ("command", "commandWindows")
        if isinstance(hook.get(key), str)
    ]
    return any(marker in cmd for marker in markers for cmd in commands)


def all_commands(document: dict[str, object]):
    hooks = document.get("hooks", {})
    assert isinstance(hooks, dict)
    for blocks in hooks.values():
        assert isinstance(blocks, list)
        for block in blocks:
            assert isinstance(block, dict)
            commands = block.get("hooks", [])
            assert isinstance(commands, list)
            yield from commands


def legacy_document(template: dict[str, object]) -> dict[str, object]:
    legacy = copy.deepcopy(template)
    for index, hook in enumerate(all_commands(legacy)):
        assert isinstance(hook, dict)
        hook["command"] = (
            'PROJECT_ROOT="$PWD"; HOOK="$PROJECT_ROOT/.codex/hooks/story_codex_hook.py"; '
            f'python3 "$HOOK" legacy-{index}'
        )
        hook["commandWindows"] = (
            "if exist .codex\\hooks\\story_codex_hook.py "
            f"python .codex\\hooks\\story_codex_hook.py legacy-{index}"
        )
    legacy["approval_policy"] = "on-request"
    first_block = legacy["hooks"]["PreToolUse"][0]
    first_block["hooks"].append(
        {"type": "command", "command": "./user-check.sh", "timeout": 3}
    )
    legacy["hooks"]["UserEvent"] = [
        {"matcher": "custom", "hooks": [{"type": "command", "command": "./custom.sh"}]}
    ]
    return legacy


def main() -> None:
    template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    legacy = legacy_document(template)

    with tempfile.TemporaryDirectory(prefix="codex-hook-merge-") as tmp:
        root = Path(tmp)
        proc, out = run_merger(legacy, template, root, "upgrade")
        assert proc.returncode == 0, proc.stderr
        merged = json.loads(out.read_text(encoding="utf-8"))

        commands = list(all_commands(merged))
        rendered = json.dumps(merged, ensure_ascii=False)
        assert "story_codex_hook.py" not in rendered
        assert sum(is_story_setup_hook(command) for command in commands) == 6
        assert sum(command.get("command") == "./user-check.sh" for command in commands) == 1
        assert sum(command.get("command") == "./custom.sh" for command in commands) == 1
        assert merged["approval_policy"] == "on-request"

        proc_again, out_again = run_merger(merged, template, root, "idempotent")
        assert proc_again.returncode == 0, proc_again.stderr
        assert out_again.read_bytes() == out.read_bytes(), "merge must be idempotent"

        proc_bad_tpl, _ = run_merger({}, {"hooks": []}, root, "bad-tpl")
        assert proc_bad_tpl.returncode == 2, f"malformed template hooks must fail: {proc_bad_tpl}"

        # 用户手改出的非数组事件值（撞上模板事件名）必须走 MergeError/exit 2 诊断。
        for idx, bad in enumerate(({"matcher": "Bash", "hooks": []}, "nope", 5, None, True)):
            proc_bad, _ = run_merger({"hooks": {"PreToolUse": bad}}, template, root, f"bad-{idx}")
            assert proc_bad.returncode == 2, f"malformed existing event value must fail: {bad!r}"
            assert "existing.hooks.PreToolUse must be an array" in proc_bad.stderr, proc_bad.stderr

        # 未与模板撞名的非数组事件值仍原样保留（保留用户已有配置的契约不能被上面的校验收紧）。
        proc_user, out_user = run_merger({"hooks": {"UserEvent": {"a": 1}}}, template, root, "preserve")
        assert proc_user.returncode == 0, proc_user.stderr
        preserved = json.loads(out_user.read_text(encoding="utf-8"))
        assert preserved["hooks"]["UserEvent"] == {"a": 1}, preserved

    print("OK: Codex hook merge replaces v17 registrations and preserves user hooks")


if __name__ == "__main__":
    main()
