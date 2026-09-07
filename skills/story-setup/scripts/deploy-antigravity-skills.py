#!/usr/bin/env python3
"""Materialize oh-story skills into a project-local Antigravity skill root.

Only the 15 known oh-story directories are replaced. Unknown user skills are
preserved. An existing ``.agents/skills`` symlink is never followed for writes;
it can be materialized only after the caller explicitly opts in.
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path


KNOWN_SKILLS = (
    "browser-cdp",
    "story",
    "story-cover",
    "story-deslop",
    "story-import",
    "story-inspiration-distill",
    "story-long-analyze",
    "story-long-scan",
    "story-long-write",
    "story-review",
    "story-runtime-guard",
    "story-setup",
    "story-short-analyze",
    "story-short-scan",
    "story-short-write",
)


class DeployError(ValueError):
    pass


def copy_entry(source: Path, destination: Path, *, dereference: bool) -> None:
    if source.is_dir() and (dereference or not source.is_symlink()):
        shutil.copytree(source, destination, symlinks=not dereference)
    elif source.is_symlink() and not dereference:
        destination.symlink_to(os.readlink(source), target_is_directory=source.is_dir())
    else:
        shutil.copy2(source, destination, follow_symlinks=dereference)


def validate_source(source: Path) -> None:
    if not source.is_dir():
        raise DeployError(f"source skill root is missing: {source}")
    for name in KNOWN_SKILLS:
        skill = source / name
        if not skill.is_dir() or not (skill / "SKILL.md").is_file():
            raise DeployError(f"source skill is incomplete: {skill}")


def deploy(source: Path, destination: Path, *, migrate_symlink: bool) -> str:
    source = source.resolve()
    validate_source(source)
    destination = destination.absolute()

    if destination.exists() and not destination.is_symlink() and destination.samefile(source):
        return "same-object no-op"
    if destination.is_symlink() and not migrate_symlink:
        raise DeployError(
            f"destination is a symlink: {destination}; rerun only after explicit symlink migration approval"
        )
    if destination.exists() and not destination.is_dir():
        raise DeployError(f"destination must be a directory: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent))
    backup = destination.with_name(f"{destination.name}.backup-{os.getpid()}")
    original_link = os.readlink(destination) if destination.is_symlink() else None
    existing_root = destination.resolve() if destination.is_symlink() else destination
    moved_existing = False
    try:
        if existing_root.exists():
            if not existing_root.is_dir():
                raise DeployError(f"symlink target must be a directory: {existing_root}")
            for entry in existing_root.iterdir():
                copy_entry(entry, staging / entry.name, dereference=False)

        for name in KNOWN_SKILLS:
            target = staging / name
            if target.is_symlink() or target.exists():
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            copy_entry(source / name, target, dereference=True)

        if backup.exists() or backup.is_symlink():
            raise DeployError(f"stale deployment backup exists: {backup}")
        if destination.is_symlink():
            destination.unlink()
        elif destination.exists():
            destination.rename(backup)
            moved_existing = True
        staging.rename(destination)
        if moved_existing:
            shutil.rmtree(backup)
        return "materialized"
    except Exception:
        if not destination.exists() and not destination.is_symlink():
            if moved_existing and backup.exists():
                backup.rename(destination)
            elif original_link is not None:
                destination.symlink_to(original_link, target_is_directory=True)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if backup.exists():
            shutil.rmtree(backup)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--dest", required=True, type=Path)
    parser.add_argument("--migrate-symlink", action="store_true")
    args = parser.parse_args()
    print(deploy(args.source, args.dest, migrate_symlink=args.migrate_symlink))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
