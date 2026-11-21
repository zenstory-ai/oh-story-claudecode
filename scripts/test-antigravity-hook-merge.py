#!/usr/bin/env python3
"""Behavior tests for the Antigravity named-group hook merger."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MERGER_PATH = ROOT / "skills/story-setup/scripts/merge-hooks.js"


def run_antigravity_merge(existing_path: Path, template_path: Path):
    return subprocess.run(
        ["node", str(MERGER_PATH), "--host", "antigravity", str(existing_path), str(template_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def main() -> None:
    existing = {
        "user-checks": {"PreToolUse": [{"matcher": "run_command", "hooks": []}]},
        "oh-story": {"Stop": [{"type": "command", "command": "legacy"}]},
        "metadata": {"owner": "user"},
    }
    template = {"oh-story": {"PreInvocation": [{"type": "command", "command": "current"}]}}

    with tempfile.TemporaryDirectory(prefix="oh-story-antigravity-merge-") as directory:
        root = Path(directory)
        target = root / ".agents/hooks.json"
        template_path = root / "template.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(existing), encoding="utf-8")
        target.chmod(0o640)
        template_path.write_text(json.dumps(template), encoding="utf-8")

        proc = run_antigravity_merge(target, template_path)
        assert proc.returncode == 0, proc.stderr
        first_bytes = target.read_bytes()
        merged = json.loads(first_bytes.decode("utf-8"))
        assert merged["oh-story"] == template["oh-story"]
        assert merged["user-checks"] == existing["user-checks"]
        assert merged["metadata"] == existing["metadata"]
        assert target.stat().st_mode & 0o777 == 0o640

        proc_again = run_antigravity_merge(target, template_path)
        assert proc_again.returncode == 0, proc_again.stderr
        assert target.read_bytes() == first_bytes, "merge must be idempotent"

        bad_template = root / "bad-template.json"
        bad_template.write_text(json.dumps({"other": {}}), encoding="utf-8")
        bad_target = root / "bad-target.json"
        bad_target.write_text(json.dumps({}), encoding="utf-8")
        proc_bad = run_antigravity_merge(bad_target, bad_template)
        assert proc_bad.returncode != 0, "template without object-valued oh-story must fail"

    print("Antigravity hook merge tests passed.")


if __name__ == "__main__":
    main()
