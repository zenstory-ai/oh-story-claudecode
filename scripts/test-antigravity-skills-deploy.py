#!/usr/bin/env python3
"""Behavior tests for project-local Antigravity skill materialization."""

from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path
from unittest.mock import patch


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


def test_backup_preservation() -> None:
    with tempfile.TemporaryDirectory(prefix="oh-story-deploy-recovery-") as directory:
        root = Path(directory)
        source = make_source(root)
        destination = root / "project/skills"
        destination.mkdir(parents=True)
        original = destination / "user.txt"
        original.write_bytes(b"original")
        backup = destination.with_name(f"{destination.name}.backup-{os.getpid()}")
        backup.mkdir()
        sentinel = backup / "recovery.txt"
        sentinel.write_bytes(b"preexisting recovery")
        try:
            MODULE.deploy(source, destination, migrate_symlink=False)
        except MODULE.DeployError as exc:
            assert "stale deployment backup" in str(exc)
        else:
            raise AssertionError("preexisting backup must stop deployment")
        assert sentinel.read_bytes() == b"preexisting recovery"
        assert original.read_bytes() == b"original"
        sentinel.unlink()
        backup.rmdir()

        real_rename = Path.rename

        def failed_install_and_restore(path, target):
            if path == destination:
                return real_rename(path, target)
            raise OSError("injected rename failure")

        with patch.object(Path, "rename", failed_install_and_restore):
            try:
                MODULE.deploy(source, destination, migrate_symlink=False)
            except OSError:
                pass
            else:
                raise AssertionError("failed install must report failure")
        assert not destination.exists()
        assert (backup / "user.txt").read_bytes() == b"original", "failed rollback must retain recovery data"
        assert not list(destination.parent.glob(".skills.staging-*"))


def main() -> None:
    test_backup_preservation()
    # The deployer materializes only the skills it names; a skill added under skills/
    # without updating KNOWN_SKILLS would silently never reach Antigravity projects.
    shipped = {path.parent.name for path in (ROOT / "skills").glob("*/SKILL.md")}
    assert set(MODULE.KNOWN_SKILLS) == shipped, (
        f"KNOWN_SKILLS drift: missing={sorted(shipped - set(MODULE.KNOWN_SKILLS))}, "
        f"stale={sorted(set(MODULE.KNOWN_SKILLS) - shipped)}"
    )

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
        (destination / "story-cover").symlink_to(outside)

        assert MODULE.deploy(source, destination, migrate_symlink=False) == "materialized"
        assert not destination.is_symlink()
        assert (destination / "user-skill/SKILL.md").read_text() == "keep\n"
        assert (destination / "story/SKILL.md").read_text().endswith("new\n")
        assert outside.read_text() == "do not touch\n"

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

    print("Antigravity skill deployment tests passed.")


if __name__ == "__main__":
    main()
