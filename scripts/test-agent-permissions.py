#!/usr/bin/env python3
"""Behavior tests for capability-derived multi-CLI agent permissions."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CODEX_GENERATOR = REPO_ROOT / "scripts/generate-codex-agents.py"
OPENCODE_GENERATOR = REPO_ROOT / "scripts/sync-opencode.py"
ANTIGRAVITY_GENERATOR = (
    REPO_ROOT / "skills/story-setup/scripts/generate-antigravity-agents.mjs"
)
TEMPLATES = REPO_ROOT / "skills/story-setup/references/templates"
CODEX_BASELINE = REPO_ROOT / "skills/story-setup/references/codex/agents"
OPENCODE_BASELINE = REPO_ROOT / "skills/story-setup/references/opencode"


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def write_agent(
    directory: Path,
    name: str,
    tools: list[str],
    disallowed: list[str] | None = None,
) -> None:
    disallowed_line = (
        f"disallowedTools: [{', '.join(disallowed)}]\n" if disallowed else ""
    )
    text = (
        "---\n"
        f"name: {name}\n"
        f"description: {name} fixture\n"
        f"tools: [{', '.join(tools)}]\n"
        f"{disallowed_line}"
        "maxTurns: 3\n"
        "---\n"
        f"# {name}\n\nCapability fixture.\n"
    )
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.md").write_text(text, encoding="utf-8")


def write_raw_agent(directory: Path, name: str, capability_lines: str) -> None:
    text = (
        "---\n"
        f"name: {name}\n"
        f"description: {name} fixture\n"
        f"{capability_lines.rstrip()}\n"
        "maxTurns: 3\n"
        "---\n"
        f"# {name}\n\nCapability fixture.\n"
    )
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.md").write_text(text, encoding="utf-8")


def codex_documents(directory: Path) -> dict[str, dict[str, object]]:
    return {
        path.stem: tomllib.loads(path.read_text(encoding="utf-8"))
        for path in directory.glob("*.toml")
    }


def opencode_permissions(path: Path) -> dict[str, str]:
    permissions: dict[str, str] = {}
    in_permissions = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line == "permission:":
            in_permissions = True
            continue
        if in_permissions and line.startswith("  "):
            key, separator, value = line.strip().partition(":")
            if separator and value.strip() in {"allow", "deny", "ask"}:
                permissions[key] = value.strip()
            continue
        if in_permissions:
            break
    return permissions


def antigravity_tools(path: Path) -> list[str]:
    tools: list[str] = []
    in_tools = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line == "tools:":
            in_tools = True
            continue
        if in_tools and line.startswith("  - "):
            tools.append(line.removeprefix("  - "))
            continue
        if in_tools:
            break
    return tools


def prepare_opencode_root(root: Path, source_agents: Path) -> Path:
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(OPENCODE_GENERATOR, scripts / OPENCODE_GENERATOR.name)
    template_root = root / "skills/story-setup/references/templates"
    shutil.copytree(source_agents, template_root / "agents")
    (template_root / "CLAUDE.md.tmpl").write_text(
        "# Fixture instructions\n", encoding="utf-8"
    )
    result = run(str(scripts / OPENCODE_GENERATOR.name), cwd=root)
    assert result.returncode == 0, result.stdout + result.stderr
    return root / "skills/story-setup/references/opencode"


def run_opencode_fixture(root: Path, source_agents: Path) -> subprocess.CompletedProcess[str]:
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(OPENCODE_GENERATOR, scripts / OPENCODE_GENERATOR.name)
    template_root = root / "skills/story-setup/references/templates"
    shutil.copytree(source_agents, template_root / "agents")
    (template_root / "CLAUDE.md.tmpl").write_text(
        "# Fixture instructions\n", encoding="utf-8"
    )
    return run(str(scripts / OPENCODE_GENERATOR.name), cwd=root)


def assert_invalid_capabilities_fail_before_publish(capability_lines: str) -> None:
    with tempfile.TemporaryDirectory(prefix="agent-capability-invalid-") as tmp:
        root = Path(tmp)
        source = root / "sources"
        write_raw_agent(source, "invalid-capabilities", capability_lines)

        codex_dest = root / "codex"
        codex_dest.mkdir()
        codex_sentinel = codex_dest / "existing.toml"
        codex_sentinel.write_text("existing codex output\n", encoding="utf-8")
        result = run(
            str(CODEX_GENERATOR),
            "--source",
            str(source),
            "--dest",
            str(codex_dest),
        )
        assert result.returncode != 0, result.stdout + result.stderr
        assert codex_sentinel.read_text(encoding="utf-8") == "existing codex output\n"
        assert not (codex_dest / "invalid-capabilities.toml").exists()

        opencode_root = root / "opencode-fixture"
        opencode_dest = opencode_root / "skills/story-setup/references/opencode"
        (opencode_dest / "agents").mkdir(parents=True)
        opencode_sentinel = opencode_dest / "agents/existing.md"
        opencode_sentinel.write_text("existing opencode output\n", encoding="utf-8")
        result = run_opencode_fixture(opencode_root, source)
        assert result.returncode != 0, result.stdout + result.stderr
        assert (
            opencode_sentinel.read_text(encoding="utf-8")
            == "existing opencode output\n"
        )
        assert not (opencode_dest / "agents/invalid-capabilities.md").exists()

        antigravity_dest = root / "antigravity"
        antigravity_dest.mkdir()
        antigravity_sentinel = antigravity_dest / "existing.txt"
        antigravity_sentinel.write_text(
            "existing antigravity output\n", encoding="utf-8"
        )
        result = subprocess.run(
            [
                "node",
                str(ANTIGRAVITY_GENERATOR),
                "--source",
                str(source),
                "--dest",
                str(antigravity_dest),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0, result.stdout + result.stderr
        assert (
            antigravity_sentinel.read_text(encoding="utf-8")
            == "existing antigravity output\n"
        )
        assert not (antigravity_dest / "invalid-capabilities").exists()


def test_existing_agents_are_byte_identical() -> None:
    with tempfile.TemporaryDirectory(prefix="agent-permissions-baseline-") as tmp:
        root = Path(tmp)
        codex_dest = root / "codex"
        result = run(
            str(CODEX_GENERATOR),
            "--source",
            str(TEMPLATES / "agents"),
            "--dest",
            str(codex_dest),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        expected_codex = sorted(path.name for path in CODEX_BASELINE.glob("*.toml"))
        assert sorted(path.name for path in codex_dest.glob("*.toml")) == expected_codex
        for filename in expected_codex:
            assert (codex_dest / filename).read_bytes() == (
                CODEX_BASELINE / filename
            ).read_bytes(), filename

        opencode_root = root / "opencode-fixture"
        generated = prepare_opencode_root(opencode_root, TEMPLATES / "agents")
        expected_opencode = sorted(
            path.name for path in (OPENCODE_BASELINE / "agents").glob("*.md")
        )
        assert sorted(path.name for path in (generated / "agents").glob("*.md")) == (
            expected_opencode
        )
        for filename in expected_opencode:
            assert (generated / "agents" / filename).read_bytes() == (
                OPENCODE_BASELINE / "agents" / filename
            ).read_bytes(), filename

def test_permissions_follow_capabilities_not_names() -> None:
    with tempfile.TemporaryDirectory(prefix="agent-permissions-fixture-") as tmp:
        root = Path(tmp)
        source = root / "sources"
        write_agent(
            source,
            "renamed-reader",
            ["Read", "Glob", "Grep"],
            ["Write", "Edit", "Bash"],
        )
        write_agent(source, "renamed-writer", ["Read", "Write", "Edit"])
        write_agent(source, "renamed-create-only", ["Read", "Write"], ["Edit"])
        write_agent(source, "shell-reader", ["Read", "Bash"])
        write_agent(
            source,
            "denials-win",
            ["Read", "Write", "Edit", "Bash"],
            ["Write", "Edit", "Bash"],
        )
        write_agent(
            source,
            "story-researcher",
            ["Read"],
            ["Write", "Edit", "Bash"],
        )
        write_agent(source, "read-denied", ["Read"], ["Read"])
        write_agent(
            source,
            "all-read-like-denied",
            ["Read", "Glob", "Grep"],
            ["Read", "Glob", "Grep"],
        )
        write_agent(
            source,
            "mixed-read-like",
            ["Read", "Glob", "Grep"],
            ["Read", "Grep"],
        )
        write_raw_agent(
            source,
            "empty-tools-mutators-denied",
            "tools: []\ndisallowedTools: [Write, Edit, Bash]",
        )
        write_raw_agent(
            source,
            "omitted-tools-mutators-denied",
            "disallowedTools: [Write, Edit, Bash]",
        )

        codex_dest = root / "codex"
        result = run(
            str(CODEX_GENERATOR),
            "--source",
            str(source),
            "--dest",
            str(codex_dest),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        codex = codex_documents(codex_dest)
        assert codex["renamed-reader"].get("sandbox_mode") == "read-only"
        assert "sandbox_mode" not in codex["renamed-writer"]
        assert "sandbox_mode" not in codex["renamed-create-only"]
        assert "sandbox_mode" not in codex["shell-reader"]
        assert codex["denials-win"].get("sandbox_mode") == "read-only"
        assert codex["story-researcher"].get("sandbox_mode") == "read-only"
        assert codex["empty-tools-mutators-denied"].get("sandbox_mode") == "read-only"
        assert codex["omitted-tools-mutators-denied"].get("sandbox_mode") == "read-only"

        generated = prepare_opencode_root(root / "opencode-fixture", source)
        permissions = {
            path.stem: opencode_permissions(path)
            for path in (generated / "agents").glob("*.md")
        }
        assert permissions["renamed-reader"] == {
            "read": "allow",
            "edit": "deny",
            "bash": "deny",
        }
        assert permissions["renamed-writer"]["edit"] == "allow"
        assert permissions["renamed-create-only"]["edit"] == "allow"
        assert permissions["shell-reader"]["bash"] == "allow"
        assert permissions["denials-win"] == {
            "read": "allow",
            "edit": "deny",
            "bash": "deny",
        }
        assert permissions["story-researcher"] == {
            "read": "allow",
            "edit": "deny",
            "bash": "deny",
        }
        assert permissions["read-denied"] == {"read": "deny"}
        assert permissions["all-read-like-denied"] == {"read": "deny"}
        assert permissions["mixed-read-like"] == {"read": "allow"}
        assert permissions["empty-tools-mutators-denied"] == {
            "edit": "deny",
            "bash": "deny",
        }
        assert permissions["omitted-tools-mutators-denied"] == {
            "edit": "deny",
            "bash": "deny",
        }

        antigravity_source = root / "antigravity-sources"
        write_agent(
            antigravity_source,
            "denied-write-edit-bash",
            ["Read", "Write", "Edit", "Bash"],
            ["Write", "Edit", "Bash"],
        )
        write_agent(
            antigravity_source,
            "denied-read",
            ["Read", "Bash"],
            ["Read"],
        )
        write_agent(
            antigravity_source,
            "denied-some-read-like",
            ["Read", "Glob", "Grep"],
            ["Read", "Grep"],
        )
        antigravity_dest = root / "antigravity"
        result = subprocess.run(
            [
                "node",
                str(ANTIGRAVITY_GENERATOR),
                "--source",
                str(antigravity_source),
                "--dest",
                str(antigravity_dest),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        antigravity = {
            path.parent.name: antigravity_tools(path)
            for path in antigravity_dest.glob("*/agent.md")
        }
        assert antigravity["denied-write-edit-bash"] == ["view_file"]
        assert antigravity["denied-read"] == ["run_command"]
        assert antigravity["denied-some-read-like"] == ["find_by_name"]


def test_invalid_capability_declarations_fail_closed() -> None:
    cases = [
        "tools: Read, Write",
        "tools: [Read, Write]\ndisallowedTools: [Write",
        "tools: []\ndisallowedTools: Write, Edit",
        'tools: ["Read", "Write"]junk',
        "tools:\n  - Read\n  - Write",
    ]
    for capability_lines in cases:
        assert_invalid_capabilities_fail_before_publish(capability_lines)


def test_antigravity_rejects_agents_with_no_effective_tools() -> None:
    with tempfile.TemporaryDirectory(prefix="antigravity-no-effective-tools-") as tmp:
        root = Path(tmp)
        source = root / "sources"
        write_raw_agent(
            source,
            "all-tools-denied",
            "tools: [Read, Glob, Grep]\n"
            "disallowedTools: [Read, Glob, Grep]",
        )
        destination = root / "antigravity"
        result = subprocess.run(
            [
                "node",
                str(ANTIGRAVITY_GENERATOR),
                "--source",
                str(source),
                "--dest",
                str(destination),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0, result.stdout + result.stderr
        assert not destination.exists()


def main() -> int:
    test_existing_agents_are_byte_identical()
    test_permissions_follow_capabilities_not_names()
    test_invalid_capability_declarations_fail_closed()
    test_antigravity_rejects_agents_with_no_effective_tools()
    print("PASS: agent permissions derive from canonical capabilities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
