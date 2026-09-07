#!/usr/bin/env python3
"""Check or synchronize intentionally duplicated, skill-local runtime assets.

Runtime skills remain self-contained after deployment, while this manifest gives the
repository a single maintenance source for each duplicated executable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Group:
    name: str
    source: Path
    targets: tuple[Path, ...]


class ManifestError(ValueError):
    pass


# 递归枚举 skills/*/scripts/ 时要跳过的非运行时目录：开发机上的构建缓存
# （__pycache__、node_modules）不是需要登记的重复脚本。
IGNORED_SCRIPT_DIRS = frozenset({".git", "__pycache__", "node_modules", ".venv"})
MARKDOWN_SUFFIXES = frozenset({".md", ".mdx"})


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "sync"))
    parser.add_argument("--root", type=Path, default=script_dir.parent)
    parser.add_argument("--manifest", type=Path, default=script_dir / "shared-assets.json")
    return parser.parse_args()


def inside_root(root: Path, raw: object, field: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ManifestError(f"{field} must be a non-empty relative path")
    relative = Path(raw)
    if relative.is_absolute():
        raise ManifestError(f"{field} must be relative: {raw}")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ManifestError(f"{field} escapes repository root: {raw}") from exc
    return resolved


def load_groups(root: Path, manifest_path: Path) -> list[Group]:
    try:
        data: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"unable to read manifest {manifest_path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ManifestError("manifest version must be 1")
    raw_groups = data.get("groups")
    if not isinstance(raw_groups, list) or not raw_groups:
        raise ManifestError("manifest groups must be a non-empty array")

    groups: list[Group] = []
    names: set[str] = set()
    source_owners: dict[Path, str] = {}
    target_owners: dict[Path, str] = {}
    for index, raw_group in enumerate(raw_groups):
        if not isinstance(raw_group, dict):
            raise ManifestError(f"groups[{index}] must be an object")
        name = raw_group.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ManifestError(f"groups[{index}].name must be a non-empty string")
        if name in names:
            raise ManifestError(f"duplicate group name: {name}")
        names.add(name)
        source = inside_root(root, raw_group.get("source"), f"{name}.source")
        previous_source_owner = source_owners.get(source)
        if previous_source_owner:
            raise ManifestError(
                "ambiguous managed source "
                f"{source.relative_to(root)} in {previous_source_owner} and {name}"
            )
        raw_targets = raw_group.get("targets")
        if not isinstance(raw_targets, list) or not raw_targets:
            raise ManifestError(f"{name}.targets must be a non-empty array")
        targets = tuple(
            inside_root(root, raw_target, f"{name}.targets[{target_index}]")
            for target_index, raw_target in enumerate(raw_targets)
        )
        for managed_path in (source, *targets):
            if managed_path.suffix.lower() in MARKDOWN_SUFFIXES:
                raise ManifestError(
                    f"{name}: runtime manifest cannot manage Markdown path "
                    f"{managed_path.relative_to(root)}"
                )
        if len(set(targets)) != len(targets):
            duplicate = next(
                target for target in targets if targets.count(target) > 1
            )
            raise ManifestError(
                f"duplicate managed target {duplicate.relative_to(root)} repeated in {name}"
            )
        for target in targets:
            previous = target_owners.get(target)
            if previous:
                raise ManifestError(
                    f"duplicate managed target {target.relative_to(root)} in {previous} and {name}"
                )
            if target.name != source.name:
                raise ManifestError(
                    f"{name}: target {target.relative_to(root)} must keep canonical "
                    f"basename {source.name}"
                )
        if source in targets:
            raise ManifestError(f"{name}: source must not also be a target")
        source_owners[source] = name
        for target in targets:
            target_owners[target] = name
        groups.append(Group(name=name, source=source, targets=targets))

    # Sources are immutable canonical inputs. A path managed as a target may not
    # become a source in another group: allowing that makes sync results depend on
    # manifest order and permits copy chains or cycles. Validate after parsing all
    # groups so the rule is independent of which group appears first.
    source_targets = sorted(source_owners.keys() & target_owners.keys())
    if source_targets:
        path = source_targets[0]
        raise ManifestError(
            f"managed path {path.relative_to(root)} is both source for "
            f"{source_owners[path]} and target for {target_owners[path]}"
        )

    # A duplicated runtime basename has exactly one canonical owner. Validate
    # this after source/target overlap so copy chains and cycles keep the more
    # actionable order-independence error.
    basename_owners: dict[str, str] = {}
    for group in groups:
        previous = basename_owners.get(group.source.name)
        if previous:
            raise ManifestError(
                f"duplicate canonical basename {group.source.name} in "
                f"{previous} and {group.name}; use one canonical group"
            )
        basename_owners[group.source.name] = group.name
    return groups


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        mode = stat.S_IMODE(source.stat().st_mode)
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, target)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def unmanaged_duplicate_scripts(root: Path, groups: list[Group]) -> list[tuple[str, list[Path]]]:
    scripts_by_name: dict[str, list[Path]] = defaultdict(list)
    skills_dir = root / "skills"
    if skills_dir.is_dir():
        # 必须递归：共享 helper 常放在 skills/<skill>/scripts/lib/ 这类子目录，
        # 单层 glob 会让这些更深的重复副本绕过守卫、各自漂移后直接发给用户。
        for scripts_dir in sorted(skills_dir.glob("*/scripts")):
            if not scripts_dir.is_dir():
                continue
            for path in sorted(scripts_dir.rglob("*")):
                if not path.is_file():
                    continue
                if any(
                    part in IGNORED_SCRIPT_DIRS
                    for part in path.relative_to(scripts_dir).parts[:-1]
                ):
                    continue
                scripts_by_name[path.name].append(path.resolve())
    managed = {
        path.resolve()
        for group in groups
        for path in (group.source, *group.targets)
    }
    return [
        (name, sorted(paths))
        for name, paths in sorted(scripts_by_name.items())
        if len(paths) > 1 and any(path not in managed for path in paths)
    ]


def run(command: str, root: Path, groups: list[Group]) -> int:
    unmanaged = unmanaged_duplicate_scripts(root, groups)
    if unmanaged:
        for name, paths in unmanaged:
            print(f"UNMANAGED DUPLICATE [{name}]")
            for path in paths:
                print(f"  {path.relative_to(root)}")
        print("ERROR: register intentional duplicate scripts in scripts/shared-assets.json", file=sys.stderr)
        return 2

    issues = 0
    changed = 0
    for group in groups:
        if not group.source.is_file():
            print(f"MISSING SOURCE [{group.name}] {group.source.relative_to(root)}")
            issues += 1
            continue
        try:
            source_hash = digest(group.source)
            source_mode = stat.S_IMODE(group.source.stat().st_mode)
        except OSError as exc:
            print(
                f"SOURCE ERROR [{group.name}] {group.source.relative_to(root)}: {exc}"
            )
            issues += 1
            continue
        for target in group.targets:
            relative = target.relative_to(root)
            if not target.is_file():
                if command == "sync":
                    try:
                        atomic_copy(group.source, target)
                    except OSError as exc:
                        print(f"COPY FAILED [{group.name}] {relative}: {exc}")
                        issues += 1
                    else:
                        changed += 1
                        print(f"SYNC [{group.name}] {relative}")
                else:
                    print(f"MISSING [{group.name}] {relative}")
                    issues += 1
                continue
            try:
                content_matches = digest(target) == source_hash
                mode_matches = stat.S_IMODE(target.stat().st_mode) == source_mode
            except OSError as exc:
                print(f"TARGET ERROR [{group.name}] {relative}: {exc}")
                issues += 1
                continue
            if content_matches and mode_matches:
                continue
            if command == "sync":
                try:
                    atomic_copy(group.source, target)
                except OSError as exc:
                    print(f"COPY FAILED [{group.name}] {relative}: {exc}")
                    issues += 1
                else:
                    changed += 1
                    print(f"SYNC [{group.name}] {relative}")
            else:
                kinds = []
                if not content_matches:
                    kinds.append("content")
                if not mode_matches:
                    kinds.append("mode")
                print(f"DRIFT [{group.name}] {relative} ({'+'.join(kinds)})")
                issues += 1

    if command == "check":
        if issues:
            print(f"FAIL: {issues} managed shared asset(s) are missing or stale")
            return 1
        managed_count = sum(len(group.targets) for group in groups)
        print(f"OK: {len(groups)} canonical groups manage {managed_count} synchronized copies")
        return 0

    if issues:
        print(f"FAIL: synchronization incomplete; {issues} managed shared asset issue(s)")
        return 1
    print(f"OK: synchronized {changed} shared asset(s)")
    return 0


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    manifest = args.manifest.resolve()
    try:
        groups = load_groups(root, manifest)
    except ManifestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return run(args.command, root, groups)


if __name__ == "__main__":
    raise SystemExit(main())
