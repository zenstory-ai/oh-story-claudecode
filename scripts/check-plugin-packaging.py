#!/usr/bin/env python3
"""Validate the repository's Claude Code and ZCode plugin packaging contract."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TypedDict


PLUGIN_NAME = "oh-story"
CLAUDE_CATALOG_NAME = "oh-story-skills"
ZCODE_CATALOG_NAME = "oh-story-zcode"
COMPONENT_KEYS = ("skills", "agents", "hooks", "commands", "mcpServers", "lspServers")
EXPECTED_SKILLS = frozenset(
    {
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
    }
)


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    message: str


class Report(TypedDict):
    ok: bool
    plugin: str
    version: str | None
    skills: list[str]
    errors: list[dict[str, Any]]


def add(findings: list[Finding], code: str, path: str, message: str) -> None:
    findings.append(Finding(code=code, path=path, message=message))


def load_json(root: Path, relative: str, findings: list[Finding]) -> dict[str, Any] | None:
    path = root / relative
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        add(findings, "missing-artifact", relative, "required packaging artifact is missing")
        return None
    except (OSError, UnicodeError) as exc:
        add(findings, "unreadable-artifact", relative, f"cannot read packaging artifact: {exc}")
        return None

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        add(
            findings,
            "malformed-json",
            relative,
            f"invalid JSON at line {exc.lineno}, column {exc.colno}",
        )
        return None
    if not isinstance(value, dict):
        add(findings, "invalid-json-root", relative, "JSON root must be an object")
        return None
    return value


def load_version(root: Path, findings: list[Finding]) -> str | None:
    relative = "skills/story/VERSION"
    path = root / relative
    try:
        version = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        add(findings, "missing-artifact", relative, "required packaging artifact is missing")
        return None
    except (OSError, UnicodeError) as exc:
        add(findings, "unreadable-artifact", relative, f"cannot read version file: {exc}")
        return None
    if not version:
        add(findings, "invalid-version", relative, "VERSION must contain a non-empty string")
        return None
    return version


def discover_skills(root: Path, findings: list[Finding]) -> list[str]:
    skills_root = root / "skills"
    if not skills_root.is_dir():
        add(findings, "missing-artifact", "skills", "root skills directory is missing")
        return []
    skills = sorted(
        child.name
        for child in skills_root.iterdir()
        if child.is_dir() and (child / "SKILL.md").is_file()
    )
    actual = set(skills)
    if actual != EXPECTED_SKILLS:
        missing = sorted(EXPECTED_SKILLS - actual)
        unexpected = sorted(actual - EXPECTED_SKILLS)
        add(
            findings,
            "root-skills",
            "skills",
            f"expected the 13 root skills; missing={missing}, unexpected={unexpected}",
        )
    return skills


def validate_catalog(
    catalog: dict[str, Any] | None,
    relative: str,
    expected_catalog_name: str,
    version: str | None,
    findings: list[Finding],
    *,
    require_metadata_version: bool,
) -> None:
    if catalog is None:
        return
    if catalog.get("name") != expected_catalog_name:
        add(
            findings,
            "catalog-name",
            relative,
            f"catalog name must remain {expected_catalog_name!r}",
        )

    if require_metadata_version:
        metadata = catalog.get("metadata")
        metadata_version = metadata.get("version") if isinstance(metadata, dict) else None
        if version is not None and metadata_version != version:
            add(
                findings,
                "catalog-metadata-version",
                relative,
                f"metadata.version must equal VERSION ({version})",
            )

    plugins = catalog.get("plugins")
    if not isinstance(plugins, list):
        add(findings, "catalog-plugins-type", relative, "plugins must be an array")
        return
    if len(plugins) != 1:
        add(
            findings,
            "catalog-entry-count",
            relative,
            f"catalog must contain exactly one root bundle entry, found {len(plugins)}",
        )

    for index, entry in enumerate(plugins):
        if not isinstance(entry, dict):
            add(
                findings,
                "catalog-entry-type",
                relative,
                f"plugins[{index}] must be an object",
            )
            continue
        if entry.get("name") != PLUGIN_NAME:
            add(
                findings,
                "catalog-entry-name",
                relative,
                f"plugins[{index}].name must be {PLUGIN_NAME!r}",
            )
        if entry.get("source") != "./":
            add(
                findings,
                "catalog-entry-source",
                relative,
                f"plugins[{index}].source must be './'",
            )
        if version is not None and entry.get("version") != version:
            add(
                findings,
                "catalog-entry-version",
                relative,
                f"plugins[{index}].version must equal VERSION ({version})",
            )
        if entry.get("strict", True) is not True:
            add(
                findings,
                "catalog-entry-strict",
                relative,
                f"plugins[{index}] must retain default native manifest authority",
            )
        shadowed = sorted(key for key in COMPONENT_KEYS if key in entry)
        if shadowed:
            add(
                findings,
                "catalog-entry-components",
                relative,
                f"plugins[{index}] must not filter root bundle components: {shadowed}",
            )


def validate_native_plugin(
    plugin: dict[str, Any] | None,
    relative: str,
    version: str | None,
    findings: list[Finding],
    *,
    claude: bool,
) -> None:
    if plugin is None:
        return
    if plugin.get("name") != PLUGIN_NAME:
        add(findings, "native-plugin-name", relative, f"name must be {PLUGIN_NAME!r}")
    if version is not None and plugin.get("version") != version:
        add(
            findings,
            "native-plugin-version",
            relative,
            f"version must equal VERSION ({version})",
        )
    if claude:
        overrides = sorted(key for key in COMPONENT_KEYS if key in plugin)
        if overrides:
            add(
                findings,
                "claude-component-override",
                relative,
                f"Claude root plugin must use default discovery, not overrides: {overrides}",
            )
    elif plugin.get("skills") != "skills":
        add(
            findings,
            "zcode-skills-root",
            relative,
            "ZCode native plugin skills must be exactly 'skills'",
        )


def validate(root: Path) -> Report:
    findings: list[Finding] = []
    version = load_version(root, findings)
    skills = discover_skills(root, findings)
    claude_catalog_path = ".claude-plugin/marketplace.json"
    zcode_catalog_path = "marketplace.json"
    claude_plugin_path = ".claude-plugin/plugin.json"
    zcode_plugin_path = ".zcode-plugin/plugin.json"

    validate_catalog(
        load_json(root, claude_catalog_path, findings),
        claude_catalog_path,
        CLAUDE_CATALOG_NAME,
        version,
        findings,
        require_metadata_version=True,
    )
    validate_catalog(
        load_json(root, zcode_catalog_path, findings),
        zcode_catalog_path,
        ZCODE_CATALOG_NAME,
        version,
        findings,
        require_metadata_version=False,
    )
    validate_native_plugin(
        load_json(root, claude_plugin_path, findings),
        claude_plugin_path,
        version,
        findings,
        claude=True,
    )
    validate_native_plugin(
        load_json(root, zcode_plugin_path, findings),
        zcode_plugin_path,
        version,
        findings,
        claude=False,
    )
    return {
        "ok": not findings,
        "plugin": PLUGIN_NAME,
        "version": version,
        "skills": skills,
        "errors": [asdict(finding) for finding in findings],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository root (defaults to the checker script's parent repository)",
    )
    parser.add_argument("--json", action="store_true", help="emit one JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = validate(args.root.resolve())
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    elif report["ok"]:
        print(
            f"plugin packaging OK: {report['plugin']} {report['version']} "
            f"({len(report['skills'])} skills)"
        )
    else:
        for error in report["errors"]:
            assert isinstance(error, dict)
            print(f"{error['path']}: {error['code']}: {error['message']}", file=sys.stderr)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
