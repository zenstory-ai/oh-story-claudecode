#!/usr/bin/env python3
"""Opt-in real Claude CLI bundle migration/update/uninstall in isolated homes.

No model calls, user configuration edits, or third-party downloads. Invoked only
by check-claude-adapter.sh with CLAUDE_REAL_CHECK=1 (CLI compatibility CI).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MARKET = "oh-story-skills"
BUNDLE = f"oh-story@{MARKET}"
UNRELATED = "unrelated@fixture-other-market"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_scope(scope: str) -> None:
    with tempfile.TemporaryDirectory(prefix=f"ohstory-claude-{scope}-") as temporary:
        root = Path(temporary)
        source, other, workspace = (root / name for name in ("source", "other", "workspace"))
        workspace.mkdir()
        (workspace / "manuscript.md").write_text("User manuscript stays here.\n", encoding="utf-8")
        (root / "home").mkdir()
        env = {**os.environ, "HOME": str(root / "home"),
               "USERPROFILE": str(root / "home"), "CLAUDE_CONFIG_DIR": str(root / "config")}
        subprocess.run(["git", "init", "-q", str(workspace)], env=env, check=True)

        def cli(*args: str) -> str:
            result = subprocess.run(["claude", "plugin", *args], cwd=workspace, env=env,
                                    capture_output=True, text=True, timeout=120, check=False)
            assert result.returncode == 0, (args, result.stdout, result.stderr)
            return result.stdout

        def installed() -> list[dict[str, Any]]:
            value = json.loads(cli("list", "--json"))
            assert isinstance(value, list), value
            return value

        def assert_records(expected: set[str]) -> list[dict[str, Any]]:
            records = installed()
            assert {(item["id"], item["scope"]) for item in records} == {
                (name, scope) for name in expected
            }, records
            assert len(records) == len(expected), records
            assert (workspace / "manuscript.md").read_text(encoding="utf-8") == "User manuscript stays here.\n"
            return records

        # Separate catalog ensures migration never relies on removing a whole
        # marketplace or clearing every installed plugin/cache record.
        (other / "skills/unrelated").mkdir(parents=True)
        unrelated_skill = "---\nname: unrelated\ndescription: Unrelated fixture\n---\nKeep me.\n"
        (other / "skills/unrelated/SKILL.md").write_text(unrelated_skill, encoding="utf-8")
        write_json(other / ".claude-plugin/plugin.json", {
            "name": "unrelated", "version": "1.0.0", "description": "Unrelated fixture",
        })
        write_json(other / ".claude-plugin/marketplace.json", {
            "name": "fixture-other-market", "owner": {"name": "fixture"},
            "plugins": [{"name": "unrelated", "source": "./", "version": "1.0.0"}],
        })
        cli("marketplace", "add", str(other))
        cli("install", UNRELATED, "--scope", scope)
        unrelated_path = Path(assert_records({UNRELATED})[0]["installPath"])

        shutil.copytree(ROOT / "skills", source / "skills")
        names = sorted(path.parent.name for path in (source / "skills").glob("*/SKILL.md"))
        assert len(names) == 13, names
        # Reproduce the old public catalog without depending on git history or
        # checking source spelling. Each entry really goes through CLI install.
        write_json(source / ".claude-plugin/marketplace.json", {
            "name": MARKET, "owner": {"name": "fixture"},
            "plugins": [{"name": name, "source": "./", "strict": False,
                         "version": "1.1.1" if name == "story-review" else "1.0.0",
                         "skills": [f"./skills/{name}"]} for name in names],
        })
        cli("marketplace", "add", str(source))
        legacy_ids = {f"{name}@{MARKET}" for name in names}
        for identity in sorted(legacy_ids):
            cli("install", identity, "--scope", scope)
        assert_records(legacy_ids | {UNRELATED})
        # Migration is an explicit uninstall, not an implicit identity rename.
        # Perform it before catalog refresh, matching the documented instructions.
        for identity in sorted(legacy_ids):
            cli("uninstall", identity, "--scope", scope, "--keep-data")
        assert_records({UNRELATED})

        for filename in ("plugin.json", "marketplace.json"):
            shutil.copy2(ROOT / ".claude-plugin" / filename, source / ".claude-plugin" / filename)
        cli("marketplace", "update", MARKET)
        cli("install", BUNDLE, "--scope", scope)
        version = (ROOT / "skills/story/VERSION").read_text(encoding="utf-8").strip()

        def assert_bundle(expected_version: str) -> None:
            record = next(item for item in assert_records({BUNDLE, UNRELATED}) if item["id"] == BUNDLE)
            assert record["version"] == expected_version, record
            installed_root = Path(record["installPath"])
            payload = json.loads((installed_root / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
            assert (payload["name"], payload["version"]) == ("oh-story", expected_version), payload
            assert sorted(path.parent.name for path in (installed_root / "skills").glob("*/SKILL.md")) == names
            # This is public CLI inventory output, not a source-text assertion.
            details = cli("details", BUNDLE)
            skills = re.search(r"^\s*Skills \((\d+)\)\s+([^\n]+)", details, re.M)
            assert skills and int(skills[1]) == len(names), details
            assert sorted(re.split(r",\s*", skills[2].strip())) == names, details
            for component in ("Agents", "Hooks", "MCP servers", "LSP servers"):
                assert re.search(rf"^\s*{re.escape(component)} \(0\)\s*$", details, re.M), details
            assert (unrelated_path / "skills/unrelated/SKILL.md").read_text(encoding="utf-8") == unrelated_skill

        assert_bundle(version)
        # A fixture-only later version proves update stays on the same identity.
        major, minor, patch = version.split(".")
        updated_version = f"{major}.{minor}.{int(patch) + 1}"
        manifest_path = source / ".claude-plugin/plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = updated_version
        write_json(manifest_path, manifest)
        catalog_path = source / ".claude-plugin/marketplace.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        catalog["metadata"]["version"] = updated_version
        catalog["plugins"][0]["version"] = updated_version
        write_json(catalog_path, catalog)
        cli("marketplace", "update", MARKET)
        cli("update", BUNDLE, "--scope", scope)
        assert_bundle(updated_version)
        cli("uninstall", BUNDLE, "--scope", scope, "--keep-data")
        assert_records({UNRELATED})
        assert (unrelated_path / "skills/unrelated/SKILL.md").read_text(encoding="utf-8") == unrelated_skill
        print(f"PASS: Claude {scope} scope — 13 legacy plugins -> one bundle; 13 skills; update/uninstall; unrelated data preserved", flush=True)


def main() -> None:
    for scope in ("user", "project", "local"):
        test_scope(scope)


if __name__ == "__main__":
    main()
