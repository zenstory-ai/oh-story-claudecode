#!/usr/bin/env python3
"""Check or sync explicitly managed cross-skill reference copies."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


IGNORED_DIRS = frozenset({".git", ".omc", "__pycache__", "node_modules", ".venv"})
MARKDOWN_SUFFIXES = frozenset({".md", ".mdx"})


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Group:
    name: str
    source: Path
    targets: tuple[Path, ...]

    @property
    def paths(self) -> tuple[Path, ...]:
        return (self.source, *self.targets)


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "sync"))
    parser.add_argument("--root", type=Path, default=script_dir.parent)
    parser.add_argument(
        "--manifest", type=Path, default=script_dir / "shared-references.json"
    )
    parser.add_argument(
        "--runtime-manifest",
        type=Path,
        help="optional runtime asset manifest used to reject cross-manifest ownership",
    )
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


def string_list(raw: object, field: str) -> list[str]:
    if not isinstance(raw, list) or not raw:
        raise ManifestError(f"{field} must be a non-empty array")
    if any(not isinstance(item, str) or not item.strip() for item in raw):
        raise ManifestError(f"{field} entries must be non-empty strings")
    if len(set(raw)) != len(raw):
        raise ManifestError(f"{field} contains duplicates")
    return raw


def load_groups(
    root: Path, manifest_path: Path, *, runtime_manifest: bool = False
) -> list[Group]:
    try:
        data: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"unable to read manifest {manifest_path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ManifestError("manifest version must be 1")

    groups: list[Group] = []
    names: set[str] = set()
    for index, raw in enumerate(data.get("groups", [])):
        if not isinstance(raw, dict):
            raise ManifestError(f"groups[{index}] must be an object")
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ManifestError(f"groups[{index}].name must be unique and non-empty")
        names.add(name)
        source = inside_root(root, raw.get("source"), f"{name}.source")
        targets = tuple(
            inside_root(root, item, f"{name}.targets")
            for item in string_list(raw.get("targets"), f"{name}.targets")
        )
        groups.append(Group(name, source, targets))

    for index, raw in enumerate(data.get("tree_groups", [])):
        if not isinstance(raw, dict):
            raise ManifestError(f"tree_groups[{index}] must be an object")
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ManifestError(
                f"tree_groups[{index}].name must be unique and non-empty"
            )
        names.add(name)
        source_dir = inside_root(root, raw.get("source"), f"{name}.source")
        target_dirs = [
            inside_root(root, item, f"{name}.targets")
            for item in string_list(raw.get("targets"), f"{name}.targets")
        ]
        filenames = string_list(raw.get("files"), f"{name}.files")
        if source_dir.is_dir():
            declared_files = {Path(filename).as_posix() for filename in filenames}
            actual_files = {
                path.relative_to(source_dir).as_posix()
                for path in source_dir.rglob("*")
                if path.is_file() and not any(part in IGNORED_DIRS for part in path.parts)
            }
            if actual_files != declared_files:
                missing = sorted(declared_files - actual_files)
                extra = sorted(actual_files - declared_files)
                details = []
                if missing:
                    details.append(f"missing from source: {', '.join(missing)}")
                if extra:
                    details.append(f"undeclared source files: {', '.join(extra)}")
                raise ManifestError(f"{name}.files is not a complete source tree ({'; '.join(details)})")
        for filename in filenames:
            relative = Path(filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise ManifestError(f"{name}.files entry is unsafe: {filename}")
            source = inside_root(
                root,
                (source_dir.relative_to(root) / relative).as_posix(),
                f"{name}.files[{filename}].source",
            )
            targets = tuple(
                inside_root(
                    root,
                    (target.relative_to(root) / relative).as_posix(),
                    f"{name}.files[{filename}].targets",
                )
                for target in target_dirs
            )
            groups.append(
                Group(
                    f"{name}:{relative.as_posix()}",
                    source,
                    targets,
                )
            )

    if not groups:
        raise ManifestError("manifest must declare at least one reference group")

    for group in groups:
        for managed_path in group.paths:
            is_markdown = managed_path.suffix.lower() in MARKDOWN_SUFFIXES
            if runtime_manifest and is_markdown:
                raise ManifestError(
                    f"{group.name}: runtime manifest cannot manage Markdown path "
                    f"{managed_path.relative_to(root)}"
                )
            if not runtime_manifest and not is_markdown:
                raise ManifestError(
                    f"{group.name}: reference manifest may manage only Markdown paths; "
                    f"got {managed_path.relative_to(root)}"
                )

    source_owners: dict[Path, str] = {}
    target_owners: dict[Path, str] = {}
    for group in groups:
        if group.source in source_owners:
            raise ManifestError(
                f"duplicate source {group.source.relative_to(root)} in "
                f"{source_owners[group.source]} and {group.name}"
            )
        source_owners[group.source] = group.name
        for target in group.targets:
            if target == group.source:
                raise ManifestError(f"{group.name}: source cannot also be a target")
            if target in target_owners:
                raise ManifestError(
                    f"duplicate target {target.relative_to(root)} in "
                    f"{target_owners[target]} and {group.name}"
                )
            target_owners[target] = group.name
    overlap = source_owners.keys() & target_owners.keys()
    if overlap:
        path = sorted(overlap)[0]
        raise ManifestError(
            f"managed path {path.relative_to(root)} is both source and target"
        )
    return groups


def validate_cross_manifest_ownership(
    root: Path,
    reference_manifest: Path,
    groups: list[Group],
    runtime_manifest: Path,
) -> None:
    reference_owners = {
        managed_path: group.name
        for group in groups
        for managed_path in group.paths
    }
    runtime_groups = load_groups(root, runtime_manifest, runtime_manifest=True)
    runtime_owners = {
        managed_path: group.name
        for group in runtime_groups
        for managed_path in group.paths
    }
    overlap = sorted(reference_owners.keys() & runtime_owners.keys())
    if not overlap:
        return
    managed_path = overlap[0]
    raise ManifestError(
        f"cross-manifest owner conflict for {managed_path.relative_to(root)}: "
        f"{reference_manifest.name}[{reference_owners[managed_path]}] and "
        f"{runtime_manifest.name}[{runtime_owners[managed_path]}]"
    )


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
        os.chmod(tmp_path, stat.S_IMODE(source.stat().st_mode))
        os.replace(tmp_path, target)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def skill_owner(root: Path, path: Path) -> str | None:
    try:
        relative = path.resolve().relative_to((root / "skills").resolve())
    except ValueError:
        return None
    return relative.parts[0] if len(relative.parts) >= 3 else None


def reference_files(root: Path) -> list[Path]:
    command = [
        "git",
        "-C",
        str(root),
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        "skills/*/references/**",
    ]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode == 0:
        paths = []
        for raw in result.stdout.split(b"\0"):
            if not raw:
                continue
            relative = os.fsdecode(raw)
            path = inside_root(
                root,
                relative,
                f"discovered reference {relative}",
            )
            if path.is_file() and not any(part in IGNORED_DIRS for part in path.parts):
                paths.append(path)
        return sorted(set(paths))

    paths = []
    for ref_dir in sorted((root / "skills").glob("*/references")):
        for path in ref_dir.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            confined = inside_root(
                root,
                relative,
                f"discovered reference {relative}",
            )
            if not any(part in IGNORED_DIRS for part in confined.parts):
                paths.append(confined)
    return sorted(set(paths))


def unmanaged_exact_pairs(root: Path, groups: list[Group]) -> list[tuple[Path, Path]]:
    managed_pairs = {
        frozenset(pair)
        for group in groups
        for pair in itertools.combinations(group.paths, 2)
    }
    by_digest: dict[str, list[Path]] = {}
    for path in reference_files(root):
        if path.stat().st_size == 0:
            continue
        by_digest.setdefault(digest(path), []).append(path)

    unmanaged: list[tuple[Path, Path]] = []
    for paths in by_digest.values():
        for left, right in itertools.combinations(paths, 2):
            if skill_owner(root, left) == skill_owner(root, right):
                continue
            if frozenset((left, right)) not in managed_pairs:
                unmanaged.append((left, right))
    return unmanaged


def run(command: str, root: Path, groups: list[Group]) -> int:
    issues = 0
    changed = 0
    for group in groups:
        if not group.source.is_file():
            print(f"MISSING SOURCE [{group.name}] {group.source.relative_to(root)}")
            issues += 1
            continue
        source_digest = digest(group.source)
        for target in group.targets:
            if command == "sync":
                if not target.is_file() or digest(target) != source_digest:
                    atomic_copy(group.source, target)
                    print(f"SYNCED [{group.name}] {target.relative_to(root)}")
                    changed += 1
                continue
            if not target.is_file():
                print(f"MISSING TARGET [{group.name}] {target.relative_to(root)}")
                issues += 1
            elif digest(target) != source_digest:
                print(f"DRIFT [{group.name}] {target.relative_to(root)}")
                issues += 1

    if command == "sync":
        print(f"Shared references synchronized: {changed} changed")
        return 0

    unmanaged = unmanaged_exact_pairs(root, groups)
    for left, right in unmanaged:
        print("UNMANAGED EXACT REFERENCE COPY")
        print(f"  {left.relative_to(root)}")
        print(f"  {right.relative_to(root)}")
        issues += 1
    if issues:
        print(f"Shared reference check failed: {issues} issue(s)", file=sys.stderr)
        return 1
    target_count = sum(len(group.targets) for group in groups)
    print(f"Shared references: {len(groups)} groups / {target_count} synchronized copies")
    return 0


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    manifest = args.manifest.resolve()
    try:
        groups = load_groups(root, manifest)
        if args.runtime_manifest is not None:
            validate_cross_manifest_ownership(
                root,
                manifest,
                groups,
                args.runtime_manifest.resolve(),
            )
        return run(args.command, root, groups)
    except ManifestError as exc:
        print(f"MANIFEST ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
