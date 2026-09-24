#!/usr/bin/env python3
"""Measure, checkpoint, check, and commit long-form story chapters."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


def _load_local_module(name: str, filename: str) -> Any:
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"TOOL_UNAVAILABLE: {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = _load_local_module("story_wordcount_core", "wordcount_core.py")
for _name in dir(core):
    if not _name.startswith("_"):
        globals()[_name] = getattr(core, _name)

CHAPTER_CHECK_SCHEMA = "story-chapter-check/v1"
CHAPTER_ERROR_SCHEMA = "story-chapter-error/v1"
# 书内工作目录：分组 segment、writer prompt 留档、逐章事务 JSON 的唯一落点。
# 与 build_writer_prompt.py 同一口径；提交成功后整目录删除，失败时原样保留供重跑。
WORK_ROOT = (".story", "work")


class CliArgumentError(ValueError):
    pass


class StructuredArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliArgumentError(message)


def _tracking_module() -> Any:
    return _load_local_module("story_tracking_for_storyctl", "tracking_commit.py")


def _tracking_call(function: Any, *args: Any) -> Any:
    try:
        return function(*args)
    except Exception as exc:
        if exc.__class__.__name__ == "TrackingError":
            raise WordcountError(str(exc)) from exc
        raise


def _json_line(payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    # Windows runners may expose a cp1252 console even when callers explicitly
    # consume UTF-8.  Write protocol output as bytes so JSON never depends on
    # the host console code page.
    sys.stdout.buffer.write(rendered.encode("utf-8"))
    sys.stdout.buffer.flush()


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WordcountError(f"unable to read {label}: {exc}") from exc
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def chapter_work_dir(project: Path, chapter: int) -> Path:
    width = max(3, len(str(chapter)))
    return project.resolve().joinpath(*WORK_ROOT, f"第{chapter:0{width}d}章")


def _remove_chapter_work_dir(project: Path, chapter: int) -> str | None:
    """Delete this chapter's scratch directory after a successful commit.

    Only the per-chapter directory is removed; `.story/work` and `.story` are
    pruned only when empty, so book-level author memory under `.story/` stays.
    """
    path = chapter_work_dir(project, chapter)
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        return None
    for parent in (path.parent, path.parent.parent):
        try:
            parent.rmdir()
        except OSError:
            break
    return "/".join((*WORK_ROOT, path.name))


def _project_files(project: Path, chapter: int) -> tuple[Path, Path, int]:
    root = project.resolve()
    outline = find_chapter_file(root / "大纲", chapter, outline=True)
    body = find_chapter_file(root / "正文", chapter, outline=False)
    try:
        target = target_from_outline(outline.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise WordcountError(f"unable to read outline: {exc}") from exc
    return outline, body, target


def _json_findings(output: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(output or "{}")
    except json.JSONDecodeError:
        return []
    findings = value.get("findings", []) if isinstance(value, dict) else []
    return findings if isinstance(findings, list) else []


def check_blocking_quality(outline: Path, body: Path) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        return {
            "status": "fail",
            "blocking_findings": [{"type": "TOOL_UNAVAILABLE", "message": "node is required for quality checks"}],
            "advisories": [],
        }
    root = Path(__file__).parent
    blocking: list[dict[str, Any]] = []
    advisories: list[dict[str, Any]] = []
    for name, script in (
        ("ai-pattern", "check-ai-patterns.js"),
        ("degeneration", "check-degeneration.js"),
    ):
        path = root / script
        if not path.is_file():
            blocking.append({"type": "TOOL_UNAVAILABLE", "message": f"missing {script}"})
            continue
        completed = subprocess.run(
            [node, str(path), "--check", "--json", "--fail-on=blocking", str(body)],
            text=True, encoding="utf-8", capture_output=True, check=False,
        )
        findings = _json_findings(completed.stdout)
        for finding in findings:
            row = {"source": name, **finding}
            (blocking if finding.get("severity") == "blocking" else advisories).append(row)
        if completed.returncode not in {0, 1}:
            blocking.append({"type": "TOOL_ERROR", "source": name, "message": completed.stderr.strip()})

    punctuation = root / "normalize-punctuation.js"
    if not punctuation.is_file():
        blocking.append({"type": "TOOL_UNAVAILABLE", "message": "missing normalize-punctuation.js"})
    else:
        completed = subprocess.run(
            [node, str(punctuation), "--check", str(body)],
            text=True, encoding="utf-8", capture_output=True, check=False,
        )
        if completed.returncode != 0:
            blocking.append(
                {"type": "PUNCTUATION_NOT_NORMALIZED", "message": (completed.stdout or completed.stderr).strip()}
            )

    outline_copy = root / "check-outline-copy.js"
    if not outline_copy.is_file():
        blocking.append({"type": "TOOL_UNAVAILABLE", "message": "missing check-outline-copy.js"})
    else:
        completed = subprocess.run(
            [node, str(outline_copy), "--outline", str(outline), str(body)],
            text=True, encoding="utf-8", capture_output=True, check=False,
        )
        if completed.returncode != 0:
            advisories.append(
                {"source": "outline-copy", "type": "OUTLINE_COPY_REVIEW", "message": completed.stdout.strip()}
            )
    return {
        "status": "fail" if blocking else "pass",
        "blocking_findings": blocking,
        "advisories": advisories,
    }


def chapter_check(project: Path, chapter: int) -> dict[str, Any]:
    outline, body_path, target = _project_files(project, chapter)
    try:
        body = body_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WordcountError(f"unable to read body: {exc}") from exc
    length = evaluate_wordcount(body, target, chapter=chapter)
    quality = check_blocking_quality(outline, body_path)
    length_ok = length["status"] in {"internal_pass", "borderline"}
    if quality["status"] != "pass" or length["status"] == "invalid":
        actions: list[str] = []
    elif length_ok:
        actions = ["commit"]
    elif length["status"] == "over":
        actions = ["compress-once", "accept-current-length", "revise-outline-or-target", "discard"]
    else:
        actions = ["accept-current-length", "revise-outline-or-target", "discard"]
    tracking = _tracking_module()
    state = _tracking_call(tracking.load_state, project)
    compression = None
    if length["status"] == "over" and quality["status"] == "pass":
        actual = length["actual"]
        compression = {
            "mode": "single_pass_remove_only",
            "remove_to_internal_band": {
                "min": actual - length["internal_band"]["max"],
                "max": actual - length["internal_band"]["min"],
            },
            "remove_to_user_band": {
                "min": actual - length["user_band"]["max"],
                "max": actual - length["user_band"]["min"],
            },
        }
    return {
        "schema": CHAPTER_CHECK_SCHEMA,
        "chapter": chapter,
        "length": length,
        "quality": quality,
        "compression": compression,
        "state_revision": state["state_revision"],
        "tracking_committed": state["last_committed_chapter"] >= chapter,
        "next_chapter_started": state["last_committed_chapter"] > chapter,
        "available_actions": actions,
    }


def chapter_commit(project: Path, chapter: int, input_path: Path, *, accept_current_length: bool) -> dict[str, Any]:
    checked = chapter_check(project, chapter)
    require(checked["quality"]["status"] == "pass", "blocking quality findings must be fixed before commit")
    length_status = checked["length"]["status"]
    in_user_band = length_status in {"internal_pass", "borderline"}
    if accept_current_length:
        require(length_status in {"under", "over"}, "accept-current-length requires a valid out-of-band chapter")
        resolution = "accepted_current_length"
    else:
        require(in_user_band, "chapter length is outside the user band; use accept-current-length or revise it")
        resolution = "within_user_band"
    document = _read_json_object(input_path, "tracking transaction")
    require(document.get("chapter") == chapter, "tracking transaction chapter does not match command")
    require("wordcount" not in document, "tracking transaction must not provide wordcount")
    document["wordcount"] = build_project_wordcount_record(project, chapter, resolution=resolution)
    tracking = _tracking_module()
    state = _tracking_call(tracking.apply_transaction, project, document)
    checked["tracking_committed"] = state["last_committed_chapter"] >= chapter
    checked["next_chapter_started"] = state["last_committed_chapter"] > chapter
    checked["wordcount"] = state["wordcount_records"].get(str(chapter))
    # The commit is already durable; a cleanup failure is reported, never turned into a failed commit.
    try:
        checked["work_dir_removed"] = _remove_chapter_work_dir(project, chapter)
    except OSError as exc:
        checked["work_dir_removed"] = None
        checked["work_dir_cleanup_error"] = str(exc)
    return checked


def _build_parser() -> StructuredArgumentParser:
    parser = StructuredArgumentParser(prog="storyctl.py")
    commands = parser.add_subparsers(dest="command", required=True)
    wordcount = commands.add_parser("wordcount")
    wordcount_commands = wordcount.add_subparsers(dest="wordcount_command", required=True)
    for command in ("measure", "check", "checkpoint"):
        subparser = wordcount_commands.add_parser(command)
        subparser.add_argument("--file", required=True)
        subparser.add_argument("--chapter")
        subparser.add_argument("--case-id")
        if command != "measure":
            subparser.add_argument("--target", required=True)
    chapter = commands.add_parser("chapter")
    chapter_commands = chapter.add_subparsers(dest="chapter_command", required=True)
    for command in ("check", "commit", "accept-current-length"):
        subparser = chapter_commands.add_parser(command)
        subparser.add_argument("--project", type=Path, required=True)
        subparser.add_argument("--chapter", type=int, required=True)
        if command != "check":
            subparser.add_argument("--input", type=Path, required=True)
    return parser


def _wordcount_command(args: argparse.Namespace) -> int:
    try:
        body = Path(args.file).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        result = (
            {"schema": MEASUREMENT_SCHEMA, "metric": METRIC, "chapter": args.chapter, "case_id": args.case_id,
             "actual": None, "status": "invalid", "invalid_reason": "INVALID_FILE"}
            if args.wordcount_command == "measure"
            else invalid_wordcount_result("INVALID_FILE", chapter=args.chapter, case_id=args.case_id)
        )
        _json_line(result)
        return 2
    if args.wordcount_command == "measure":
        result = measure_wordcount(body, chapter=args.chapter, case_id=args.case_id)
    elif args.wordcount_command == "checkpoint":
        try:
            result = checkpoint_wordcount(body, args.target, chapter=args.chapter, case_id=args.case_id)
        except WordcountError:
            result = invalid_wordcount_result("INVALID_TARGET", chapter=args.chapter, case_id=args.case_id)
    else:
        result = evaluate_wordcount(body, args.target, chapter=args.chapter, case_id=args.case_id)
    _json_line(result)
    return 2 if result.get("status") == "invalid" else 0


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(argv) if argv is not None else sys.argv[1:]
    try:
        args = _build_parser().parse_args(raw)
    except CliArgumentError as exc:
        payload = (
            {"schema": CHAPTER_ERROR_SCHEMA, "error_code": "INVALID_ARGUMENT", "message": str(exc)}
            if raw[:1] == ["chapter"] else invalid_wordcount_result("INVALID_ARGUMENT", case_id=str(exc))
        )
        _json_line(payload)
        return 2
    if args.command == "wordcount":
        return _wordcount_command(args)
    try:
        if args.chapter_command == "check":
            result = chapter_check(args.project, args.chapter)
        else:
            result = chapter_commit(
                args.project, args.chapter, args.input,
                accept_current_length=args.chapter_command == "accept-current-length",
            )
    except (WordcountError, OSError, UnicodeError) as exc:
        _json_line({"schema": CHAPTER_ERROR_SCHEMA, "error_code": "CHECK_FAILED", "message": str(exc)})
        return 2
    _json_line(result)
    return 2 if result["quality"]["status"] != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())
