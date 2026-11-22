#!/usr/bin/env python3
"""Behavior tests for project-local Antigravity skill materialization."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "skills/story-setup/scripts/deploy-antigravity-skills.js"


def load_known_skills() -> list[str]:
    proc = subprocess.run(
        ["node", "-e", "console.log(JSON.stringify(require(process.argv[1]).KNOWN_SKILLS))", str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(proc.stdout)


def run_deploy(source: Path, dest: Path, *, migrate_symlink: bool = False):
    cmd = ["node", str(SCRIPT_PATH), "--source", str(source), "--dest", str(dest)]
    if migrate_symlink:
        cmd.append("--migrate-symlink")
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")


def make_source(root: Path, known_skills: list[str]) -> Path:
    source = root / "source"
    for name in known_skills:
        skill = source / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: {name}\ndescription: fixture\n---\nnew\n", encoding="utf-8")
    return source


def main() -> None:
    known_skills = load_known_skills()
    # The deployer materializes only the skills it names; a skill added under skills/
    # without updating KNOWN_SKILLS would silently never reach Antigravity projects.
    shipped = {path.parent.name for path in (ROOT / "skills").glob("*/SKILL.md")}
    assert set(known_skills) == shipped, (
        f"KNOWN_SKILLS drift: missing={sorted(shipped - set(known_skills))}, "
        f"stale={sorted(set(known_skills) - shipped)}"
    )

    with tempfile.TemporaryDirectory(prefix="oh-story-antigravity-skills-") as directory:
        root = Path(directory)
        source = make_source(root, known_skills)
        destination = root / "project/.agents/skills"
        (destination / "story").mkdir(parents=True)
        (destination / "story/SKILL.md").write_text("old\n", encoding="utf-8")
        (destination / "user-skill").mkdir()
        (destination / "user-skill/SKILL.md").write_text("keep\n", encoding="utf-8")
        outside = root / "outside.md"
        outside.write_text("do not touch\n", encoding="utf-8")
        (destination / "story-cover").symlink_to(outside)

        proc = run_deploy(source, destination, migrate_symlink=False)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "materialized", proc.stdout
        assert not destination.is_symlink()
        assert (destination / "user-skill/SKILL.md").read_text(encoding="utf-8") == "keep\n"
        assert (destination / "story/SKILL.md").read_text(encoding="utf-8").endswith("new\n")
        assert outside.read_text(encoding="utf-8") == "do not touch\n"

        linked_target = root / "shared-skills"
        (linked_target / "user-skill").mkdir(parents=True)
        (linked_target / "user-skill/SKILL.md").write_text("shared keep\n", encoding="utf-8")
        linked = root / "linked-project/.agents/skills"
        linked.parent.mkdir(parents=True)
        linked.symlink_to(os.path.relpath(linked_target, linked.parent), target_is_directory=True)
        proc_reject = run_deploy(source, linked, migrate_symlink=False)
        assert proc_reject.returncode != 0, "symlink destination must require explicit migration"
        assert linked.is_symlink()
        assert not (linked_target / "story").exists()

        proc_migrate = run_deploy(source, linked, migrate_symlink=True)
        assert proc_migrate.returncode == 0, proc_migrate.stderr
        assert proc_migrate.stdout.strip() == "materialized", proc_migrate.stdout
        assert linked.is_dir() and not linked.is_symlink()
        assert (linked / "user-skill/SKILL.md").read_text(encoding="utf-8") == "shared keep\n"
        assert not (linked_target / "story").exists(), "migration must not write through the old symlink"

        proc_noop = run_deploy(linked, linked, migrate_symlink=False)
        assert proc_noop.returncode == 0, proc_noop.stderr
        assert proc_noop.stdout.strip() == "same-object no-op", proc_noop.stdout

        # --flag=value CLI syntax must be accepted
        eq_dest = root / "eq-project/.agents/skills"
        proc_eq = subprocess.run(
            ["node", str(SCRIPT_PATH), f"--source={source}", f"--dest={eq_dest}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert proc_eq.returncode == 0, proc_eq.stderr
        assert proc_eq.stdout.strip() == "materialized", proc_eq.stdout

        # Stale backup preservation: throwing DeployError must NOT delete an existing stale backup
        backup_probe = subprocess.run(
            [
                "node",
                "-e",
                (
                    "const fs = require('node:fs');"
                    "const path = require('node:path');"
                    "const { deploy, DeployError } = require(process.argv[1]);"
                    "const source = process.argv[2];"
                    "const dest = process.argv[3];"
                    "const backup = path.join(path.dirname(dest), path.basename(dest) + '.backup-' + process.pid);"
                    "fs.mkdirSync(backup, { recursive: true });"
                    "fs.writeFileSync(path.join(backup, 'sentinel.txt'), 'precious', 'utf8');"
                    "let caught = null;"
                    "try { deploy(source, dest); } catch (e) { caught = e; }"
                    "if (!(caught instanceof DeployError) || !caught.message.includes('stale deployment backup exists')) {"
                    "  console.error('unexpected error:', caught);"
                    "  process.exit(1);"
                    "}"
                    "if (fs.readFileSync(path.join(backup, 'sentinel.txt'), 'utf8') !== 'precious') {"
                    "  console.error('stale backup was modified or deleted');"
                    "  process.exit(1);"
                    "}"
                ),
                str(SCRIPT_PATH),
                str(source),
                str(destination),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert backup_probe.returncode == 0, backup_probe.stderr

    print("Antigravity skill deployment tests passed.")


if __name__ == "__main__":
    main()
