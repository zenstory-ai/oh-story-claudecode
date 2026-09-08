#!/usr/bin/env python3
"""Behavior tests for capability-derived multi-CLI agent permissions."""

from __future__ import annotations

import argparse
import json
import os
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
    write_raw_agent(
        directory, name, f"tools: [{', '.join(tools)}]\n{disallowed_line}"
    )


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
                permissions[key.strip('"')] = value.strip()
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
    result = run_opencode_fixture(root, source_agents)
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


def test_generated_agents_are_in_sync() -> None:
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
    cases = {
        "renamed-reader": "tools: [Read, Glob, Grep]\ndisallowedTools: [Write, Edit, Bash]",
        "implicit-reader": "tools: [Read]",
        "renamed-writer": "tools: [Read, Write, Edit]",
        "write-without-edit": "tools: [Read, Write]\ndisallowedTools: [Edit]",
        "edit-without-write": "tools: [Read, Edit]\ndisallowedTools: [Write]",
        "shell-reader": "tools: [Read, Bash]",
        "denials-win": "tools: [Read, Write, Edit, Bash]\ndisallowedTools: [Write, Edit, Bash]",
        "story-researcher": "tools: [Read]\ndisallowedTools: [Write, Edit, Bash]",
        "mixed-read-like": "tools: [Read, Glob, Grep]\ndisallowedTools: [Read, Grep]",
    }
    with tempfile.TemporaryDirectory(prefix="agent-permissions-fixture-") as tmp:
        root = Path(tmp)
        source = root / "sources"
        for name, declaration in cases.items():
            write_raw_agent(source, name, declaration)
        result = run(str(CODEX_GENERATOR), "--source", str(source), "--dest", str(root / "codex"))
        assert result.returncode == 0, result.stdout + result.stderr
        codex = codex_documents(root / "codex")
        for name in ("renamed-reader", "implicit-reader", "denials-win", "story-researcher", "mixed-read-like"):
            assert codex[name].get("sandbox_mode") == "read-only", name
        for name in ("renamed-writer", "write-without-edit", "edit-without-write", "shell-reader"):
            assert "sandbox_mode" not in codex[name], name

        generated = prepare_opencode_root(root / "opencode", source)
        permissions = {
            path.stem: opencode_permissions(path)
            for path in (generated / "agents").glob("*.md")
        }
        reader = {"*": "deny", "read": "allow", "glob": "allow", "grep": "allow", "edit": "deny", "bash": "deny"}
        assert permissions["renamed-reader"] == reader
        only_read = {**reader, "glob": "deny", "grep": "deny"}
        for name in ("implicit-reader", "denials-win", "story-researcher"):
            assert permissions[name] == only_read, name
        assert permissions["mixed-read-like"] == {**reader, "read": "deny", "grep": "deny"}
        for name in ("renamed-writer", "write-without-edit", "edit-without-write"):
            assert permissions[name] == {**only_read, "edit": "allow"}, name
        assert permissions["shell-reader"] == {**only_read, "bash": "allow"}

        result = subprocess.run(
            ["node", str(ANTIGRAVITY_GENERATOR), "--source", str(source), "--dest", str(root / "agy")],
            text=True, capture_output=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert antigravity_tools(root / "agy/denials-win/agent.md") == ["view_file"]
        assert antigravity_tools(root / "agy/mixed-read-like/agent.md") == ["find_by_name"]
        assert antigravity_tools(root / "agy/write-without-edit/agent.md") == ["view_file", "write_to_file"]
        assert antigravity_tools(root / "agy/edit-without-write/agent.md") == ["view_file", "replace_file_content", "multi_replace_file_content"]


def test_empty_and_inherited_tools_are_distinct() -> None:
    cases = {
        "empty": "tools: []",
        "all-denied": "tools: [Read, Glob, Grep]\ndisallowedTools: [Read, Glob, Grep]",
        "inherit": "",
        "inherit-minus-glob": "disallowedTools: [Glob, Write, Edit, Bash]",
    }
    with tempfile.TemporaryDirectory(prefix="agent-permissions-inheritance-") as tmp:
        root = Path(tmp)
        for name, declaration in cases.items():
            source = root / name / "sources"
            write_raw_agent(source, name, declaration)
            result = run(str(CODEX_GENERATOR), "--source", str(source), "--dest", str(root / name / "codex"))
            if name in {"empty", "all-denied"}:
                assert result.returncode != 0 and "zero effective tools" in result.stderr, result.stderr
                assert not (root / name / "codex").exists()
            else:
                assert result.returncode == 0, result.stderr
                assert "sandbox_mode" not in codex_documents(root / name / "codex")[name]
            generated = prepare_opencode_root(root / name / "opencode", source)
            permissions = opencode_permissions(generated / f"agents/{name}.md")
            if name in {"empty", "all-denied"}:
                assert permissions == {"*": "deny", "read": "deny", "glob": "deny", "grep": "deny", "edit": "deny", "bash": "deny"}
            elif name == "inherit":
                assert permissions == {}
            else:
                assert permissions == {"glob": "deny", "edit": "deny", "bash": "deny"}
            result = subprocess.run(
                ["node", str(ANTIGRAVITY_GENERATOR), "--source", str(source), "--dest", str(root / name / "agy")],
                text=True, capture_output=True,
            )
            assert result.returncode != 0, name
            assert not (root / name / "agy").exists()


def test_codex_recognizes_other_mutating_tools() -> None:
    with tempfile.TemporaryDirectory(prefix="codex-mutating-tools-") as tmp:
        root = Path(tmp)
        for tool in ("NotebookEdit", "PowerShell"):
            write_agent(root / "sources", tool, ["Read", tool])
            write_agent(root / "sources", f"denied-{tool}", ["Read", tool], [tool])
        result = run(str(CODEX_GENERATOR), "--source", str(root / "sources"), "--dest", str(root / "codex"))
        assert result.returncode == 0, result.stderr
        docs = codex_documents(root / "codex")
        for tool in ("NotebookEdit", "PowerShell"):
            assert "sandbox_mode" not in docs[tool]
            assert docs[f"denied-{tool}"]["sandbox_mode"] == "read-only"
        result = run_opencode_fixture(root / "opencode", root / "sources")
        assert result.returncode != 0 and "unsupported OpenCode capability" in result.stderr
        result = subprocess.run(
            ["node", str(ANTIGRAVITY_GENERATOR), "--source", str(root / "sources"), "--dest", str(root / "agy")],
            text=True, capture_output=True,
        )
        assert result.returncode != 0 and "unsupported Antigravity capability" in result.stderr


def test_invalid_capability_declarations_fail_closed() -> None:
    cases = [
        "tools: [Read, NotARealTool]",
        "tools: [Read]\ndisallowedTools: [NotARealTool]",
        "tools: Read, Write",
        "tools: [Read, Write]\ndisallowedTools: [Write",
        "tools: []\ndisallowedTools: Write, Edit",
        'tools: ["Read", "Write"]junk',
        "tools:\n  - Read\n  - Write",
    ]
    for capability_lines in cases:
        assert_invalid_capabilities_fail_before_publish(capability_lines)


def test_opencode_runtime(cli: str) -> None:
    """Exercise the V1 tool registry and allow/deny checks without model calls."""
    with tempfile.TemporaryDirectory(prefix="opencode-agent-permissions-") as tmp:
        root = Path(tmp).resolve()
        source = root / "sources"
        for name, declaration in {
            "reader": "tools: [Read]",
            "glob-only": "tools: [Read, Glob, Grep]\ndisallowedTools: [Read, Grep]",
            "inherit-minus-glob": "disallowedTools: [Glob, Write, Edit, Bash]",
            "writer": "tools: [Read, Write]\ndisallowedTools: [Edit, Bash]",
            "shell": "tools: [Read, Bash]",
            "empty": "tools: []",
        }.items():
            write_raw_agent(source, name, declaration)
        generated = prepare_opencode_root(root / "generator", source)
        project = root / "project"
        shutil.copytree(generated / "agents", project / ".opencode/agents")
        shutil.copytree(OPENCODE_BASELINE / "agents", project / ".opencode/agents", dirs_exist_ok=True)
        (project / "opencode.json").write_text(json.dumps({
            "model": "fixture/probe",
            "provider": {"fixture": {
                "npm": "@ai-sdk/openai-compatible",
                "options": {"baseURL": "http://127.0.0.1:9/v1", "apiKey": "fixture"},
                "models": {"probe": {"name": "probe", "limit": {"context": 10000, "output": 1000}}},
            }},
        }), encoding="utf-8")
        (project / "canary.txt").write_text("PERMISSION_CANARY\n", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("OPENCODE_", "ANTHROPIC_", "OPENAI_", "XDG_"))}
        env["HOME"] = str(root / "home")
        for kind in ("CONFIG", "DATA", "CACHE", "STATE"):
            env[f"XDG_{kind}_HOME"] = str(root / "home" / kind.lower())

        def invoke(name: str, *args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [cli, "debug", "agent", name, "--pure", *args],
                cwd=project, env=env, text=True, capture_output=True, timeout=90,
            )

        for name in ("reader", "empty", "chapter-extractor", "character-designer", "consistency-checker",
                     "narrative-writer", "story-architect", "story-explorer", "story-researcher"):
            result = invoke(name)
            assert result.returncode == 0, result.stdout + result.stderr
            tools = json.loads(result.stdout)["tools"]
            for tool in ("task", "webfetch", "skill"):
                assert tools[tool] is False, (name, tool, tools)
            if name == "empty":
                assert not any(tools.values()), tools
            elif name != "reader":
                assert all(tools[t] for t in ("read", "glob", "grep")), (name, tools)
                assert tools["bash"] == (name in {"narrative-writer", "story-researcher"}), (name, tools)

        checks = [
            ("reader", "read", {"filePath": str(project / "canary.txt")}, True),
            ("reader", "write", {"filePath": str(project / "reader-write.txt"), "content": "DENIED"}, False),
            ("reader", "bash", {"command": "printf DENIED > shell-write.txt", "description": "Write fixture"}, False),
            ("glob-only", "read", {"filePath": str(project / "canary.txt")}, False),
            ("glob-only", "grep", {"pattern": "PERMISSION_CANARY", "path": "."}, False),
            ("glob-only", "glob", {"pattern": "canary.txt"}, True),
            ("inherit-minus-glob", "read", {"filePath": str(project / "canary.txt")}, True),
            ("inherit-minus-glob", "glob", {"pattern": "canary.txt"}, False),
            ("inherit-minus-glob", "grep", {"pattern": "PERMISSION_CANARY", "path": "."}, True),
            ("writer", "write", {"filePath": str(project / "created.txt"), "content": "CREATED"}, True),
            ("shell", "bash", {"command": "printf SHELL_OK", "description": "Fixture shell control"}, True),
            ("empty", "read", {"filePath": str(project / "canary.txt")}, False),
            ("empty", "write", {"filePath": str(project / "empty-write.txt"), "content": "DENIED"}, False),
        ]
        for name, tool, params, allowed in checks:
            result = invoke(name, "--tool", tool, "--params", json.dumps(params))
            output = result.stdout + result.stderr
            if allowed:
                assert result.returncode == 0, (name, tool, output)
                if tool in {"read", "grep"}:
                    assert "PERMISSION_CANARY" in output, output
                elif tool == "glob":
                    assert "canary.txt" in output, output
            else:
                assert result.returncode != 0 and "disabled" in output.lower(), (name, tool, output)
            print(f"  OpenCode {name}/{tool}: {'allow' if allowed else 'deny'}")
        assert (project / "created.txt").read_text(encoding="utf-8") == "CREATED"
        for filename in ("reader-write.txt", "shell-write.txt", "empty-write.txt"):
            assert not (project / filename).exists(), filename
        assert (project / "canary.txt").read_text(encoding="utf-8") == "PERMISSION_CANARY\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opencode", help="OpenCode V1 executable for real tool permission checks")
    args = parser.parse_args()
    test_generated_agents_are_in_sync()
    test_permissions_follow_capabilities_not_names()
    test_empty_and_inherited_tools_are_distinct()
    test_codex_recognizes_other_mutating_tools()
    test_invalid_capability_declarations_fail_closed()
    if args.opencode:
        test_opencode_runtime(str(Path(args.opencode).resolve()))
    print("PASS: agent permissions derive from canonical capabilities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
