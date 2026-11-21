#!/usr/bin/env python3
"""Merge current story-setup Claude hooks without preserving stale matchers.

Only registrations whose command invokes a known story-setup hook script are
managed. They are removed from their historical event/matcher block before the
current template is appended; unrelated hooks and top-level settings survive.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any


MANAGED_HOOK_SCRIPTS = frozenset(
    {
        "run-story-hook.sh",
        "check-prose-after-write.sh",
        "detect-story-gaps.sh",
        "guard-outline-before-prose.sh",
        "post-compact.sh",
        "pre-compact.sh",
        "session-end.sh",
        "session-start.sh",
        "validate-story-commit.sh",
    }
)


class MergeError(ValueError):
    pass


def is_story_setup_hook(hook: object) -> bool:
    if not isinstance(hook, dict) or not isinstance(hook.get("command"), str):
        return False
    normalized = hook["command"].replace("\\", "/")
    return any(f"/.claude/hooks/{name}" in normalized for name in MANAGED_HOOK_SCRIPTS)


def require_hooks(document: object, label: str) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise MergeError(f"{label} root must be a JSON object")
    hooks = document.get("hooks", {})
    if not isinstance(hooks, dict):
        raise MergeError(f"{label}.hooks must be a JSON object")
    return hooks


def strip_managed_registrations(hooks: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for event, raw_blocks in hooks.items():
        if not isinstance(raw_blocks, list):
            cleaned[event] = copy.deepcopy(raw_blocks)
            continue
        blocks: list[Any] = []
        for raw_block in raw_blocks:
            if not isinstance(raw_block, dict) or not isinstance(raw_block.get("hooks"), list):
                blocks.append(copy.deepcopy(raw_block))
                continue
            block = copy.deepcopy(raw_block)
            block["hooks"] = [hook for hook in block["hooks"] if not is_story_setup_hook(hook)]
            if not block["hooks"]:
                continue
            blocks.append(block)
        if blocks:
            cleaned[event] = blocks
    return cleaned


def merge_documents(existing: object, template: object) -> dict[str, Any]:
    existing_hooks = require_hooks(existing, "existing")
    template_hooks = require_hooks(template, "template")
    for event, blocks in template_hooks.items():
        if not isinstance(blocks, list):
            raise MergeError(f"template.hooks.{event} must be an array")

    result = copy.deepcopy(existing)
    assert isinstance(result, dict)
    merged = strip_managed_registrations(existing_hooks)
    for event, blocks in template_hooks.items():
        if event in merged and not isinstance(merged[event], list):
            raise MergeError(f"existing.hooks.{event} must be an array")
        merged.setdefault(event, []).extend(copy.deepcopy(blocks))
    result["hooks"] = merged
    return result


def read_json(path: Path, *, missing_ok: bool = False) -> object:
    if missing_ok and not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MergeError(f"unable to read {path}: {exc}") from exc


def atomic_write_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--existing", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        atomic_write_json(
            args.output,
            merge_documents(read_json(args.existing, missing_ok=True), read_json(args.template)),
        )
    except MergeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
