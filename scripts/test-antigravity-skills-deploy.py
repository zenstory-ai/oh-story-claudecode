#!/usr/bin/env python3
"""Behavior tests for project-local Antigravity skill materialization."""

from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "skills/story-setup/scripts/deploy-antigravity-skills.py"
SPEC = importlib.util.spec_from_file_location("deploy_antigravity_skills", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def make_source(root: Path) -> Path:
    source = root / "source"
    for name in MODULE.KNOWN_SKILLS:
        skill = source / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: {name}\ndescription: fixture\n---\nnew\n", encoding="utf-8")
    return source


def can_create_symlink(root: Path) -> bool:
    target = root / "symlink-probe-target"
    link = root / "symlink-probe"
    target.write_text("probe\n", encoding="utf-8")
    try:
        link.symlink_to(target)
    except OSError:
        return False
    link.unlink()
    return True


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="oh-story-antigravity-skills-") as directory:
        root = Path(directory)
        source = make_source(root)
        destination = root / "project/.agents/skills"
        (destination / "story").mkdir(parents=True)
        (destination / "story/SKILL.md").write_text("old\n", encoding="utf-8")
        (destination / "user-skill").mkdir()
        (destination / "user-skill/SKILL.md").write_text("keep\n", encoding="utf-8")
        outside = root / "outside.md"
        outside.write_text("do not touch\n", encoding="utf-8")
        symlink_supported = can_create_symlink(root)
        if symlink_supported:
            (destination / "story-cover").symlink_to(outside)

        assert MODULE.deploy(source, destination, migrate_symlink=False) == "materialized"
        assert not destination.is_symlink()
        assert (destination / "user-skill/SKILL.md").read_text() == "keep\n"
        assert (destination / "story/SKILL.md").read_text().endswith("new\n")
        assert len([path for path in destination.iterdir() if (path / "SKILL.md").is_file()]) == len(MODULE.KNOWN_SKILLS) + 1
        assert outside.read_text() == "do not touch\n"

        if symlink_supported:
            linked_target = root / "shared-skills"
            (linked_target / "user-skill").mkdir(parents=True)
            (linked_target / "user-skill/SKILL.md").write_text("shared keep\n", encoding="utf-8")
            linked = root / "linked-project/.agents/skills"
            linked.parent.mkdir(parents=True)
            linked.symlink_to(os.path.relpath(linked_target, linked.parent), target_is_directory=True)
            try:
                MODULE.deploy(source, linked, migrate_symlink=False)
            except MODULE.DeployError:
                pass
            else:
                raise AssertionError("symlink destination must require explicit migration")
            assert linked.is_symlink()
            assert not (linked_target / "story").exists()

            assert MODULE.deploy(source, linked, migrate_symlink=True) == "materialized"
            assert linked.is_dir() and not linked.is_symlink()
            assert (linked / "user-skill/SKILL.md").read_text() == "shared keep\n"
            assert not (linked_target / "story").exists(), "migration must not write through the old symlink"
            assert MODULE.deploy(linked, linked, migrate_symlink=False) == "same-object no-op"
        else:
            print("SKIP: Windows symlink privilege unavailable; symlink migration branch not exercised")

    print("Antigravity skill deployment tests passed.")


if __name__ == "__main__":
    main()
