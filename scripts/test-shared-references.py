#!/usr/bin/env python3
"""Regression tests for explicit reference governance and consumer reachability."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
CHECKER = SCRIPT_DIR / "shared-references.py"
CONSUMERS = SCRIPT_DIR / "check-agent-reference-consumers.py"
SIMILARITY = SCRIPT_DIR / "check-reference-similarity.py"
SHORT_ANALYSIS = SCRIPT_DIR / "check-short-analysis-scope.py"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def manifest(root: Path) -> Path:
    path = root / "shared-references.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "groups": [
                    {
                        "name": "aliased-copy",
                        "source": "skills/a/references/guide.md",
                        "targets": ["skills/b/references/b-guide.md"],
                    }
                ],
                "tree_groups": [
                    {
                        "name": "cards",
                        "source": "skills/a/references/cards",
                        "targets": ["skills/c/references/cards"],
                        "files": ["one.md"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def runtime_manifest(
    root: Path,
    groups: list[dict[str, object]],
    tree_groups: list[dict[str, object]] | None = None,
) -> Path:
    path = root / "shared-assets.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "groups": groups,
                "tree_groups": tree_groups or [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_reference_manifest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write(root / "skills/a/references/guide.md", "guide\n")
        write(root / "skills/b/references/b-guide.md", "guide\n")
        write(root / "skills/a/references/cards/one.md", "card\n")
        write(root / "skills/c/references/cards/one.md", "card\n")
        config = manifest(root)

        result = run(CHECKER, "check", "--root", str(root), "--manifest", str(config))
        assert result.returncode == 0, result.stdout + result.stderr

        write(root / "skills/b/references/b-guide.md", "drift\n")
        result = run(CHECKER, "check", "--root", str(root), "--manifest", str(config))
        assert result.returncode == 1 and "DRIFT" in result.stdout
        result = run(CHECKER, "sync", "--root", str(root), "--manifest", str(config))
        assert result.returncode == 0
        assert (root / "skills/b/references/b-guide.md").read_text() == "guide\n"

        write(root / "skills/d/references/unmanaged.md", "guide\n")
        result = run(CHECKER, "check", "--root", str(root), "--manifest", str(config))
        assert result.returncode == 1
        assert "UNMANAGED EXACT REFERENCE COPY" in result.stdout

        write(root / "skills/a/references/cards/two.md", "new card\n")
        result = run(CHECKER, "check", "--root", str(root), "--manifest", str(config))
        assert result.returncode == 2
        assert "undeclared source files: two.md" in result.stderr


def test_cross_manifest_ownership() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write(root / "skills/a/references/guide.md", "guide\n")
        write(root / "skills/b/references/b-guide.md", "guide\n")
        write(root / "skills/a/references/cards/one.md", "card\n")
        write(root / "skills/c/references/cards/one.md", "card\n")
        references = manifest(root)

        runtime = runtime_manifest(
            root,
            [
                {
                    "name": "runtime-only",
                    "source": "skills/a/scripts/tool.js",
                    "targets": ["skills/b/scripts/tool.js"],
                }
            ],
        )
        result = run(
            CHECKER,
            "check",
            "--root",
            str(root),
            "--manifest",
            str(references),
            "--runtime-manifest",
            str(runtime),
        )
        assert result.returncode == 0, result.stdout + result.stderr

        cases = (
            (
                "duplicate-source",
                "skills/a/references/guide.md",
                "skills/z/references/runtime-target.md",
            ),
            (
                "duplicate-target",
                "skills/z/references/runtime-source.md",
                "skills/b/references/b-guide.md",
            ),
            (
                "reference-tree-target",
                "skills/z/references/runtime-source.md",
                "skills/c/references/cards/one.md",
            ),
        )
        for name, source, target in cases:
            runtime = runtime_manifest(
                root,
                [{"name": name, "source": source, "targets": [target]}],
            )
            result = run(
                CHECKER,
                "check",
                "--root",
                str(root),
                "--manifest",
                str(references),
                "--runtime-manifest",
                str(runtime),
            )
            assert result.returncode == 2, result.stdout + result.stderr
            assert "runtime manifest cannot manage Markdown" in result.stderr
            assert source in result.stderr or target in result.stderr
            assert name in result.stderr

        runtime = runtime_manifest(
            root,
            [],
            [
                {
                    "name": "runtime-tree",
                    "source": "skills/z/references/cards",
                    "targets": ["skills/c/references/cards"],
                    "files": ["one.md"],
                }
            ],
        )
        result = run(
            CHECKER,
            "check",
            "--root",
            str(root),
            "--manifest",
            str(references),
            "--runtime-manifest",
            str(runtime),
        )
        assert result.returncode == 2, result.stdout + result.stderr
        assert "runtime manifest cannot manage Markdown" in result.stderr
        assert "skills/z/references/cards/one.md" in result.stderr
        assert "runtime-tree:one.md" in result.stderr

        # Custom/standalone fixtures stay isolated unless the caller explicitly
        # opts into a second manifest. A same-directory runtime manifest must not
        # be guessed and applied behind the caller's back.
        runtime_manifest(
            root,
            [
                {
                    "name": "implicit-conflict",
                    "source": "skills/a/references/guide.md",
                    "targets": ["skills/z/references/runtime-target.md"],
                }
            ],
        )
        result = run(
            CHECKER, "check", "--root", str(root), "--manifest", str(references)
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_manifest_domains() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write(root / "skills/a/references/guide.MD", "guide\n")
        write(root / "skills/b/references/guide.mDx", "guide\n")
        references = root / "shared-references.json"
        references.write_text(
            json.dumps(
                {
                    "version": 1,
                    "groups": [
                        {
                            "name": "markdown-case-insensitive",
                            "source": "skills/a/references/guide.MD",
                            "targets": ["skills/b/references/guide.mDx"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        allowed = run(
            CHECKER, "check", "--root", str(root), "--manifest", str(references)
        )
        assert allowed.returncode == 0, allowed.stdout + allowed.stderr

        invalid_cases = (
            ("non-markdown-source", "skills/a/references/guide.js", "skills/b/references/guide.md"),
            ("non-markdown-target", "skills/a/references/guide.md", "skills/b/references/guide.txt"),
        )
        for name, source_name, target_name in invalid_cases:
            write(root / source_name, "guide\n")
            write(root / target_name, "guide\n")
            references.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "groups": [
                            {"name": name, "source": source_name, "targets": [target_name]}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            rejected = run(
                CHECKER, "check", "--root", str(root), "--manifest", str(references)
            )
            assert rejected.returncode == 2, rejected.stdout + rejected.stderr
            assert "reference manifest may manage only Markdown" in rejected.stderr

        write(root / "skills/a/references/cards/data.JSON", "{}\n")
        write(root / "skills/b/references/cards/data.JSON", "{}\n")
        references.write_text(
            json.dumps(
                {
                    "version": 1,
                    "groups": [],
                    "tree_groups": [
                        {
                            "name": "non-markdown-tree-file",
                            "source": "skills/a/references/cards",
                            "targets": ["skills/b/references/cards"],
                            "files": ["data.JSON"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        rejected = run(
            CHECKER, "check", "--root", str(root), "--manifest", str(references)
        )
        assert rejected.returncode == 2, rejected.stdout + rejected.stderr
        assert "reference manifest may manage only Markdown" in rejected.stderr
        assert "non-markdown-tree-file:data.JSON" in rejected.stderr

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write(root / "skills/a/references/guide.md", "reference\n")
        write(root / "skills/b/references/guide.md", "reference\n")
        references = root / "shared-references.json"
        references.write_text(
            json.dumps(
                {
                    "version": 1,
                    "groups": [
                        {
                            "name": "reference",
                            "source": "skills/a/references/guide.md",
                            "targets": ["skills/b/references/guide.md"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        for filename in ("story_hook_core.js", "runtime_helper.PY"):
            source = root / "skills/runtime/references" / filename
            target = root / "skills/runtime/references/runtime-shadow" / filename
            write(source, f"runtime {filename}\n")
            write(target, f"runtime {filename}\n")
            runtime = runtime_manifest(
                root,
                [
                    {
                        "name": filename,
                        "source": source.relative_to(root).as_posix(),
                        "targets": [target.relative_to(root).as_posix()],
                    }
                ],
            )
            allowed = run(
                CHECKER,
                "check",
                "--root",
                str(root),
                "--manifest",
                str(references),
                "--runtime-manifest",
                str(runtime),
            )
            assert allowed.returncode == 0, allowed.stdout + allowed.stderr

        markdown_source = root / "skills/runtime/references/long-format.MD"
        markdown_target = root / "skills/runtime/references/runtime-shadow/long-format.MD"
        write(markdown_source, "runtime-invalid markdown\n")
        write(markdown_target, "runtime-invalid markdown\n")
        runtime = runtime_manifest(
            root,
            [
                {
                    "name": "markdown-runtime",
                    "source": markdown_source.relative_to(root).as_posix(),
                    "targets": [markdown_target.relative_to(root).as_posix()],
                }
            ],
        )
        rejected = run(
            CHECKER,
            "check",
            "--root",
            str(root),
            "--manifest",
            str(references),
            "--runtime-manifest",
            str(runtime),
        )
        assert rejected.returncode == 2, rejected.stdout + rejected.stderr
        assert "runtime manifest cannot manage Markdown" in rejected.stderr


def test_tree_file_symlink_cannot_escape_root() -> None:
    for manifest_kind in ("reference", "runtime"):
        for escaped_role in ("source", "target"):
            with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
                root = Path(tmp)
                outside_file = Path(outside) / "one.md"
                write(outside_file, "outside\n")

                if manifest_kind == "reference":
                    source_dir = root / "skills/a/references/cards"
                    target_dir = root / "skills/b/references/cards"
                else:
                    source_dir = root / "skills/a/scripts/cards"
                    target_dir = root / "skills/b/scripts/cards"
                source_dir.mkdir(parents=True)
                target_dir.mkdir(parents=True)
                write(source_dir / "one.md", "outside\n")
                write(target_dir / "one.md", "outside\n")
                escaped = (source_dir if escaped_role == "source" else target_dir) / "one.md"
                escaped.unlink()
                try:
                    escaped.symlink_to(outside_file)
                except (NotImplementedError, OSError):
                    # Some Windows runners do not grant symlink creation. The
                    # same actual-CLI cases still run on symlink-capable lanes.
                    return

                tree_name = f"{manifest_kind}-{escaped_role}-escape"
                tree: dict[str, object] = {
                    "name": tree_name,
                    "source": str(source_dir.relative_to(root)),
                    "targets": [str(target_dir.relative_to(root))],
                    "files": ["one.md"],
                }
                if manifest_kind == "reference":
                    references = root / "shared-references.json"
                    references.write_text(
                        json.dumps(
                            {"version": 1, "groups": [], "tree_groups": [tree]}
                        ),
                        encoding="utf-8",
                    )
                    result = run(
                        CHECKER,
                        "check",
                        "--root",
                        str(root),
                        "--manifest",
                        str(references),
                    )
                else:
                    write(root / "skills/r/references/guide.md", "reference\n")
                    write(root / "skills/s/references/guide.md", "reference\n")
                    references = root / "shared-references.json"
                    references.write_text(
                        json.dumps(
                            {
                                "version": 1,
                                "groups": [
                                    {
                                        "name": "reference-only",
                                        "source": "skills/r/references/guide.md",
                                        "targets": ["skills/s/references/guide.md"],
                                    }
                                ],
                            }
                        ),
                        encoding="utf-8",
                    )
                    runtime = runtime_manifest(root, [], [tree])
                    result = run(
                        CHECKER,
                        "check",
                        "--root",
                        str(root),
                        "--manifest",
                        str(references),
                        "--runtime-manifest",
                        str(runtime),
                    )

                assert result.returncode == 2, result.stdout + result.stderr
                assert "escapes repository root" in result.stderr
                assert tree_name in result.stderr


def test_undeclared_reference_symlink_cannot_escape_root() -> None:
    for scan_mode in ("fallback", "git"):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            outside_file = Path(outside) / "canary.md"
            canary = b"outside canary must remain unchanged\n"
            outside_file.write_bytes(canary)

            write(root / "skills/a/references/guide.md", "source\n")
            write(root / "skills/b/references/guide.md", "source\n")
            references = root / "shared-references.json"
            references.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "groups": [
                            {
                                "name": "declared",
                                "source": "skills/a/references/guide.md",
                                "targets": ["skills/b/references/guide.md"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            escaped = root / "skills/undeclared/references/escape.md"
            escaped.parent.mkdir(parents=True)
            try:
                escaped.symlink_to(outside_file)
            except (NotImplementedError, OSError):
                return

            if scan_mode == "git":
                initialized = subprocess.run(
                    ["git", "init", "--quiet"],
                    cwd=root,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                assert initialized.returncode == 0, initialized.stderr

            result = run(
                CHECKER,
                "check",
                "--root",
                str(root),
                "--manifest",
                str(references),
            )
            assert result.returncode == 2, result.stdout + result.stderr
            assert "MANIFEST ERROR:" in result.stderr
            assert "discovered reference" in result.stderr
            assert "skills/undeclared/references/escape.md" in result.stderr
            assert "escapes repository root" in result.stderr
            assert "Traceback" not in result.stderr
            assert outside_file.read_bytes() == canary


def test_agent_reference_reachability() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        base = root / "skills/story-setup/references"
        write(
            base / "templates/agents/story-architect.md",
            "read story-setup/references/agent-references/agent-reference-profiles.md\n",
        )
        write(
            base / "agent-references/agent-reference-profiles.md",
            """# Profile contract

## Common
| file | condition |
|---|---|
| [index.md](index.md) | always |

## Long profile
| file | condition |
|---|---|
| [long-guide.md](long-guide.md) | long |

## Short profile
| file | condition |
|---|---|
| [short-guide.md](short-guide.md) | short |
""",
        )
        write(
            base / "agent-references/index.md",
            "[detail](details/detail.md)\n",
        )
        write(base / "agent-references/details/detail.md", "reachable\n")
        write(base / "agent-references/long-guide.md", "long\n")
        write(base / "agent-references/short-guide.md", "short\n")
        result = run(CONSUMERS, "--root", str(root))
        assert result.returncode == 0, result.stdout + result.stderr

        # Exercise the static guard's public CLI against deployed artifacts.
        # This validates source policy, not model reference-reading behavior.
        write(base / "agent-references/genre-prose-cards/都市.md", "card\n")
        write(base / "agent-references/index.md", "[detail](details/detail.md)\n[card](genre-prose-cards/都市.md)\n")
        writer = base / "templates/agents/narrative-writer.md"
        canonical = "story-setup/references/agent-references/"
        valid = [
            "读 正文.md 和 设定/角色/{name}.md，不读 my-index.md。项目研究记录在 research/index.md。",
            f"读 `{canonical}index.md` 与 `{canonical}details/detail.md`。",
            f"[index.md]({canonical}index.md#规则)",
            f"{{项目根}}/.claude/skills/{canonical}index.md",
            f"读 `{canonical}genre-prose-cards/{{题材}}.md`。",
            f"{{项目根}}/.claude/skills/{canonical}{{文件名}}",
            "[index.md](https://example.invalid/index.md) 和 https://example.invalid/index.md",
            "See https://example.invalid/agent-references/external-only.md",
            "[index.md](https://example.invalid/agent-references/external-only.md)",
        ]
        for snippet in valid:
            write(writer, "# Writer\n" + snippet + "\n")
            result = run(CONSUMERS, "--root", str(root))
            assert result.returncode == 0, (snippet, result.stdout, result.stderr)

        for snippet, line in [
            ("读 `index.md`。", 2),
            ("参照（index.md）。", 2),
            ("`agent-references/index.md`", 2),
            ("`references/agent-references/index.md`", 2),
            ("Read('details/detail.md')", 2),
            ("```text\nindex.md\n```", 3),
            ("读 genre-prose-cards/{题材}.md", 2),
            ("[索引](index.md)", 2),
        ]:
            write(writer, "# Writer\n" + snippet + "\n")
            result = run(CONSUMERS, "--root", str(root))
            assert result.returncode == 1, (snippet, result.stdout, result.stderr)
            assert "INVALID AGENT REFERENCE PREFIX" in result.stdout, result.stdout
            assert f"templates/agents/narrative-writer.md:{line}:" in result.stdout, result.stdout
            assert canonical in result.stdout, result.stdout

        write(writer, f"read {canonical}missing.md\n")
        result = run(CONSUMERS, "--root", str(root))
        assert result.returncode == 1, result.stdout + result.stderr
        assert "MISSING DEPLOYED AGENT REFERENCES" in result.stdout, result.stdout
        writer.unlink()

        write(base / "agent-references/orphan.md", "orphan\n")
        result = run(CONSUMERS, "--root", str(root))
        assert result.returncode == 1
        assert "orphan.md" in result.stdout


def test_reference_similarity_declarations() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        lines = [f"shared governance sentence number {index:02d}" for index in range(15)]
        write(root / "skills/a/references/guide.md", "\n".join(lines) + "\n")
        write(
            root / "skills/b/references/derived.md",
            "\n".join(lines[:-1] + ["derived consumer sentence differs here"]) + "\n",
        )
        config = root / "shared-references.json"
        config.write_text('{"version": 1, "groups": [], "tree_groups": []}', encoding="utf-8")
        result = run(SIMILARITY, "--root", str(root), "--manifest", str(config))
        assert result.returncode == 1
        assert "UNDECLARED NEAR-IDENTICAL" in result.stdout

        config.write_text(
            json.dumps(
                {
                    "version": 1,
                    "groups": [],
                    "tree_groups": [],
                    "derived_groups": [
                        {
                            "name": "guide-derivative",
                            "reason": "different consumer contract",
                            "members": [
                                "skills/a/references/guide.md",
                                "skills/b/references/derived.md",
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        result = run(SIMILARITY, "--root", str(root), "--manifest", str(config))
        assert result.returncode == 0, result.stdout + result.stderr


def test_short_analysis_scope() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        skill = root / "skills/story-short-analyze"
        write(
            skill / "SKILL.md",
            "\n".join(f"read references/{name}" for name in (
                "analysis-short-genres.md",
                "analysis-short-patterns.md",
                "analysis-short-mechanics.md",
                "analysis-short-suspense.md",
                "analysis-short-hooks.md",
            )),
        )
        for name in (
            "analysis-short-genres.md",
            "analysis-short-patterns.md",
            "analysis-short-mechanics.md",
            "analysis-short-suspense.md",
            "analysis-short-hooks.md",
        ):
            write(skill / "references" / name, "# 源文观察\n\n按位置报告证据与作用。\n")

        result = run(SHORT_ANALYSIS, "--root", str(root))
        assert result.returncode == 0, result.stdout + result.stderr

        write(
            skill / "references/analysis-short-patterns.md",
            "# 源文观察\n\n每章必备一种爽点，推荐结构为 40%。\n",
        )
        result = run(SHORT_ANALYSIS, "--root", str(root))
        assert result.returncode == 1
        assert "long-form playbook token" in result.stdout
        assert "prescribed percentage" in result.stdout


def main() -> int:
    test_reference_manifest()
    test_cross_manifest_ownership()
    test_manifest_domains()
    test_tree_file_symlink_cannot_escape_root()
    test_undeclared_reference_symlink_cannot_escape_root()
    test_agent_reference_reachability()
    test_reference_similarity_declarations()
    test_short_analysis_scope()
    print("PASS: shared reference manifest and deployed consumer guards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
