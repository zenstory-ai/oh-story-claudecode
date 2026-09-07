#!/usr/bin/env python3
"""Public-CLI regressions for the cross-platform plugin packaging guard."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast


SCRIPT = Path(__file__).with_name("check-plugin-packaging.py")
SKILLS = (
    "browser-cdp",
    "story",
    "story-cover",
    "story-deslop",
    "story-import",
    "story-long-analyze",
    "story-long-scan",
    "story-long-write",
    "story-review",
    "story-setup",
    "story-short-analyze",
    "story-short-scan",
    "story-short-write",
)
VERSION = "9.8.7"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def make_fixture(root: Path) -> None:
    for skill in SKILLS:
        skill_dir = root / "skills" / skill
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {skill}\ndescription: fixture\n---\n",
            encoding="utf-8",
        )
    (root / "skills/story/VERSION").write_text(VERSION + "\n", encoding="utf-8")
    write_json(
        root / ".claude-plugin/marketplace.json",
        {
            "name": "oh-story-skills",
            "metadata": {"version": VERSION},
            "plugins": [{"name": "oh-story", "source": "./", "version": VERSION}],
        },
    )
    write_json(
        root / "marketplace.json",
        {
            "name": "oh-story-zcode",
            "plugins": [{"name": "oh-story", "source": "./", "version": VERSION}],
        },
    )
    write_json(
        root / ".claude-plugin/plugin.json",
        {"name": "oh-story", "version": VERSION, "description": "fixture"},
    )
    write_json(
        root / ".zcode-plugin/plugin.json",
        {
            "name": "oh-story",
            "version": VERSION,
            "skills": "skills",
            "commands": "commands",
            "hooks": "hooks.json",
        },
    )


def run_cli(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), "--json", *extra],
        text=True,
        capture_output=True,
        check=False,
    )


def json_report(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"CLI did not emit JSON: {result.stdout!r}; {result.stderr!r}") from exc
    require(isinstance(report, dict), "JSON report must be an object")
    return cast(dict[str, Any], report)


def error_codes(report: dict[str, Any]) -> set[str]:
    errors = cast(list[Any] | None, report.get("errors"))
    if not isinstance(errors, list):
        raise AssertionError("report errors must be a list")
    return {
        error["code"]
        for error in errors
        if isinstance(error, dict) and isinstance(error.get("code"), str)
    }


def mutate_json(root: Path, relative: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    path = root / relative
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), "fixture JSON must be an object")
    mutate(value)
    write_json(path, value)


def assert_failure(
    label: str,
    relative: str,
    mutate: Callable[[Path], None],
    expected_code: str,
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        make_fixture(root)
        mutate(root)
        result = run_cli(root)
        report = json_report(result)
        require(result.returncode == 1, f"{label}: expected exit 1, got {result.returncode}")
        require(report.get("ok") is False, f"{label}: failure report must set ok=false")
        require(
            expected_code in error_codes(report),
            f"{label}: expected {expected_code}, got {report['errors']}",
        )
        errors = cast(list[Any], report["errors"])
        paths = {
            error.get("path")
            for error in errors
            if isinstance(error, dict) and error.get("code") == expected_code
        }
        require(relative in paths, f"{label}: expected structured path {relative}, got {paths}")


def json_mutation(
    relative: str, mutate: Callable[[dict[str, Any]], None]
) -> Callable[[Path], None]:
    return lambda root: mutate_json(root, relative, mutate)


def test_success() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        make_fixture(root)
        result = run_cli(root)
        report = json_report(result)
        require(result.returncode == 0, f"valid fixture failed: {report}")
        require(
            report
            == {
                "ok": True,
                "plugin": "oh-story",
                "version": VERSION,
                "skills": list(SKILLS),
                "errors": [],
            },
            f"unexpected success report: {report}",
        )


def test_catalog_mutations() -> None:
    catalogs = (
        (".claude-plugin/marketplace.json", "oh-story-zcode"),
        ("marketplace.json", "oh-story-skills"),
    )
    for relative, wrong_catalog_name in catalogs:
        def set_catalog_name(
            data: dict[str, Any], name: str = wrong_catalog_name
        ) -> None:
            data.update(name=name)

        assert_failure(
            f"{relative} catalog identity",
            relative,
            json_mutation(relative, set_catalog_name),
            "catalog-name",
        )
        assert_failure(
            f"{relative} entry identity",
            relative,
            json_mutation(relative, lambda data: data["plugins"][0].update(name="story")),
            "catalog-entry-name",
        )
        assert_failure(
            f"{relative} entry version",
            relative,
            json_mutation(relative, lambda data: data["plugins"][0].update(version="1.0.0")),
            "catalog-entry-version",
        )
        assert_failure(
            f"{relative} entry source",
            relative,
            json_mutation(relative, lambda data: data["plugins"][0].update(source="./skills")),
            "catalog-entry-source",
        )
        assert_failure(
            f"{relative} entry count",
            relative,
            json_mutation(
                relative,
                lambda data: data["plugins"].append(dict(data["plugins"][0])),
            ),
            "catalog-entry-count",
        )
        assert_failure(
            f"{relative} disables native manifest authority",
            relative,
            json_mutation(relative, lambda data: data["plugins"][0].update(strict=False)),
            "catalog-entry-strict",
        )
        for component in ("skills", "agents", "hooks", "commands", "mcpServers", "lspServers"):
            def set_entry_component(
                data: dict[str, Any], key: str = component
            ) -> None:
                data["plugins"][0].update({key: "filtered"})

            assert_failure(
                f"{relative} filters {component}",
                relative,
                json_mutation(
                    relative,
                    set_entry_component,
                ),
                "catalog-entry-components",
            )


def test_native_and_version_mutations() -> None:
    for relative in (".claude-plugin/plugin.json", ".zcode-plugin/plugin.json"):
        assert_failure(
            f"{relative} identity",
            relative,
            json_mutation(relative, lambda data: data.update(name="other")),
            "native-plugin-name",
        )
        assert_failure(
            f"{relative} version",
            relative,
            json_mutation(relative, lambda data: data.update(version="1.0.0")),
            "native-plugin-version",
        )

    assert_failure(
        "Claude metadata version",
        ".claude-plugin/marketplace.json",
        json_mutation(
            ".claude-plugin/marketplace.json",
            lambda data: data["metadata"].update(version="1.0.0"),
        ),
        "catalog-metadata-version",
    )
    def write_wrong_version(root: Path) -> None:
        (root / "skills/story/VERSION").write_text("1.0.0\n", encoding="utf-8")

    assert_failure(
        "VERSION drift",
        ".claude-plugin/marketplace.json",
        write_wrong_version,
        "catalog-entry-version",
    )
    assert_failure(
        "ZCode skills root",
        ".zcode-plugin/plugin.json",
        json_mutation(
            ".zcode-plugin/plugin.json",
            lambda data: data.update(skills="./skills/story"),
        ),
        "zcode-skills-root",
    )
    for component in ("skills", "agents", "hooks", "commands", "mcpServers", "lspServers"):
        def set_native_component(
            data: dict[str, Any], key: str = component
        ) -> None:
            data.update({key: "filtered"})

        assert_failure(
            f"Claude native overrides {component}",
            ".claude-plugin/plugin.json",
            json_mutation(
                ".claude-plugin/plugin.json",
                set_native_component,
            ),
            "claude-component-override",
        )


def test_missing_malformed_and_skill_inventory() -> None:
    def write_malformed_catalog(root: Path) -> None:
        (root / "marketplace.json").write_text("{broken", encoding="utf-8")

    for relative in (".claude-plugin/plugin.json", ".zcode-plugin/plugin.json"):
        def remove_native_manifest(root: Path, path: str = relative) -> None:
            (root / path).unlink()

        assert_failure(
            f"missing native manifest {relative}",
            relative,
            remove_native_manifest,
            "missing-artifact",
        )
    assert_failure(
        "malformed catalog",
        "marketplace.json",
        write_malformed_catalog,
        "malformed-json",
    )
    for relative in (
        ".claude-plugin/marketplace.json",
        ".claude-plugin/plugin.json",
        ".zcode-plugin/plugin.json",
    ):
        def write_malformed_json(root: Path, path: str = relative) -> None:
            (root / path).write_text("{broken", encoding="utf-8")

        assert_failure(
            f"malformed JSON {relative}",
            relative,
            write_malformed_json,
            "malformed-json",
        )
    assert_failure(
        "missing root skill",
        "skills",
        lambda root: (root / "skills/story-cover/SKILL.md").unlink(),
        "root-skills",
    )


def test_invalid_usage() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--not-an-option"],
        text=True,
        capture_output=True,
        check=False,
    )
    require(result.returncode == 2, f"invalid usage must exit 2, got {result.returncode}")


def main() -> int:
    test_success()
    test_catalog_mutations()
    test_native_and_version_mutations()
    test_missing_malformed_and_skill_inventory()
    test_invalid_usage()
    print("plugin packaging CLI tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
