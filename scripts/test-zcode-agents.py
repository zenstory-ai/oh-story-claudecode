#!/usr/bin/env python3
"""Behavior regression for generated ZCode plugin agents."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts/generate-zcode-agents.py"
CALLER_SKILLS = (
    "story", "story-long-write", "story-short-write", "story-long-analyze",
    "story-import", "story-deslop", "story-review",
)


def caller_contract_errors(root: Path) -> list[str]:
    """Inspect entrypoints and every cold reference, not just generated roles."""
    patterns = (
        (r"\bAgent\s*\(\s*subagent_type\s*:", "Claude-only invocation"),
        (r"canonical(?:\s+agent)?\s*目录\s*已部署|检查\s*canonical\s*目录", "file-only role availability"),
        (r"只检查[^。；\n]{0,32}canonical\s*目录", "file-only version preflight"),
    )
    errors: list[str] = []
    for skill in CALLER_SKILLS:
        for path in sorted((root / "skills" / skill).rglob("*.md")):
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for pattern, label in patterns:
                    if re.search(pattern, line):
                        errors.append(f"{path.relative_to(root)}:{line_number}: {label}")
    return errors


def test_caller_contract_guard() -> None:
    with tempfile.TemporaryDirectory(prefix="zcode-caller-") as raw:
        root = Path(raw)
        path = root / "skills/story-short-write/references/nested/workflow.md"
        path.parent.mkdir(parents=True)
        for invalid in (
            '派 Agent(subagent_type: "consistency-checker", prompt: "核对")',
            "当前运行时的 canonical 目录已部署 story-explorer 时才派出",
            "按顶部兼容性检查 canonical 目录",
            "但只检查当前运行时的 canonical 目录",
        ):
            path.write_text(invalid, encoding="utf-8")
            assert len(caller_contract_errors(root)) == 1, invalid
        path.write_text("按 SKILL 顶部的当前宿主角色来源检查，ZCode 查插件注册角色；Prompt：核对", encoding="utf-8")
        assert not caller_contract_errors(root)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GENERATOR), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    raw, body = text[4:].split("\n---\n", 1)
    data: dict[str, str] = {}
    lines = raw.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        key, marker, value = line.partition(":")
        assert marker and line == line.lstrip(), (path, line)
        if value.strip() == "|":
            block: list[str] = []
            index += 1
            while index < len(lines) and lines[index].startswith("  "):
                block.append(lines[index][2:])
                index += 1
            data[key] = "\n".join(block)
            continue
        data[key] = value.strip()
        index += 1
    return data, body


def write_source(directory: Path, front: str, body: str = "Fixture body.\n") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "fixture.md").write_text(
        f"---\n{front.rstrip()}\n---\n{body}", encoding="utf-8"
    )


def test_permissions_and_adaptation() -> None:
    with tempfile.TemporaryDirectory(prefix="zcode-agent-generate-") as raw:
        root = Path(raw)
        source = root / "source"
        destination = root / "destination"
        destination.mkdir()
        (destination / "retired.md").write_text("retired\n", encoding="utf-8")
        (destination / "user.txt").write_text("keep\n", encoding="utf-8")
        write_source(
            source,
            """name: fixture
description: |
  fixture description
tools: [Read, Glob, Write, Bash]
disallowedTools: [Write, Bash]
model: sonnet
maxTurns: 9
hooks:
  PreToolUse:
    - matcher: \"Write\"""",
            """读取当前 Claude 部署的 `.claude/skills/story/SKILL.md`。
重新运行 `/story-setup`，然后通过 `Agent(subagent_type: \"fixture\")` 调用。
""",
        )
        result = run("--source", str(source), "--dest", str(destination))
        assert result.returncode == 0, result.stdout + result.stderr
        assert not (destination / "retired.md").exists()
        assert (destination / "user.txt").read_text(encoding="utf-8") == "keep\n"
        data, body = frontmatter(destination / "fixture.md")
        assert data == {
            "name": "fixture",
            "description": "fixture description",
            "model": "inherit",
            "tools": "[Read, Glob]",
            "disallowedTools": "[Write, Bash]",
            "maxTurns": "9",
            "injectAgentsMd": "false",
        }, data
        assert "hooks" not in data
        assert ".zcode/skills/story/SKILL.md" in body
        assert "当前 ZCode 部署" in body
        assert "$story-setup" in body and "/story-setup" not in body
        assert "Agent(subagent_type" not in body


def test_invalid_sources_fail_before_publish() -> None:
    cases = {
        "missing-name": "description: x\ntools: [Read]\nmaxTurns: 3",
        "missing-description": "name: fixture\ntools: [Read]\nmaxTurns: 3",
        "missing-tools": "name: fixture\ndescription: x\nmaxTurns: 3",
        "bad-tools": "name: fixture\ndescription: x\ntools: [Read, Unknown]\nmaxTurns: 3",
        "empty-effective-tools": "name: fixture\ndescription: x\ntools: [Read]\ndisallowedTools: [Read]\nmaxTurns: 3",
        "bad-max-turns": "name: fixture\ndescription: x\ntools: [Read]\nmaxTurns: many",
    }
    for label, front in cases.items():
        with tempfile.TemporaryDirectory(prefix=f"zcode-agent-{label}-") as raw:
            root = Path(raw)
            source = root / "source"
            destination = root / "destination"
            write_source(source, front)
            destination.mkdir()
            sentinel = destination / "keep.md"
            sentinel.write_text("keep\n", encoding="utf-8")
            result = run("--source", str(source), "--dest", str(destination))
            assert result.returncode != 0, (label, result.stdout, result.stderr)
            assert sentinel.read_text(encoding="utf-8") == "keep\n", label
            assert not (destination / "fixture.md").exists(), label


def test_check_detects_drift() -> None:
    with tempfile.TemporaryDirectory(prefix="zcode-agent-check-") as raw:
        root = Path(raw)
        source = root / "source"
        destination = root / "destination"
        write_source(
            source,
            "name: fixture\ndescription: fixture\ntools: [Read]\nmodel: opus\nmaxTurns: 3",
        )
        generated = run("--source", str(source), "--dest", str(destination))
        assert generated.returncode == 0, generated.stdout + generated.stderr
        checked = run("--source", str(source), "--dest", str(destination), "--check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        (destination / "fixture.md").write_text("drift\n", encoding="utf-8")
        drifted = run("--source", str(source), "--dest", str(destination), "--check")
        assert drifted.returncode != 0, (drifted.stdout, drifted.stderr)


def main() -> int:
    test_permissions_and_adaptation()
    test_invalid_sources_fail_before_publish()
    test_check_detects_drift()
    test_caller_contract_guard()
    errors = caller_contract_errors(ROOT)
    assert not errors, "\n".join(errors)
    print("PASS: ZCode agents preserve bounded capabilities and generate deterministically")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
