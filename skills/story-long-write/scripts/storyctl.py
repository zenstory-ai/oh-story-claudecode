#!/usr/bin/env python3
"""Measure, checkpoint, check, and commit long-form story chapters."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
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


def _project_files(
    project: Path, chapter: int, author_range: Any = None,
) -> tuple[Path, Path, int, dict[str, int] | None]:
    return read_project_chapter(project, chapter, author_range)


def _json_findings(output: str) -> list[dict[str, Any]] | None:
    """检测器 --json 输出里的 findings；输出不是预期 JSON 时返回 None（按工具故障处理，不当作无问题）。"""
    try:
        value = json.loads(output)
    except json.JSONDecodeError:
        return None
    findings = value.get("findings") if isinstance(value, dict) else None
    if not isinstance(findings, list) or not all(isinstance(row, dict) for row in findings):
        return None
    return findings


NODE_REQUIRED = (
    "质量检查（AI 句式、退化、标点、细纲照搬）要用 Node.js 运行，本机找不到 node。"
    "安装 Node.js 18 或更高版本并确认 `node --version` 可用后重跑本命令；装好之前本章不能提交。"
)


def _semantic_advisories(advisories: list[dict[str, Any]]) -> int:
    # check-ai-patterns 给每条 finding 标 review=semantic|mechanical，退化检测器的在入口统一标 mechanical；
    # 其余来源没标的按语义类算，宁多勿漏。
    return sum(1 for row in advisories if row.get("review") != "mechanical")


# 与 hooks（JS core DESLOP_SKIP_MARKER / codex py / bash guard）同一语法：注释内只认 ASCII 空格/Tab，
# 冒号全角半角都认；裸写不在注释里的不算。
DESLOP_SKIP = re.compile(r"<!--[ \t]*去味[ \t]*(：|:)[ \t]*跳过[ \t]*-->")


def deslop_skipped(body: Path) -> bool:
    """作者显式说本章不去味时，标题行下的 <!-- 去味:跳过 --> 豁免 AI 句式；与 hooks 同一个首 6 行窗口。"""
    head = re.split(r"\r?\n", body.read_text(encoding="utf-8-sig"))[:6]
    return bool(DESLOP_SKIP.search("\n".join(head)))


def check_blocking_quality(outline: Path, body: Path) -> dict[str, Any]:
    """Run the deterministic prose checks.

    status: pass（无 blocking）/ fail（有 blocking 正文问题）/ unavailable（检测工具缺失或崩溃，
    不是正文问题，见 tool_errors）。
    """
    node = shutil.which("node")
    if node is None:
        return {
            "status": "unavailable",
            "blocking_findings": [],
            "advisories": [],
            "semantic_advisories": 0,
            "tool_errors": [{"type": "TOOL_UNAVAILABLE", "tool": "node", "message": NODE_REQUIRED}],
        }
    root = Path(__file__).parent
    exempt = deslop_skipped(body)
    blocking: list[dict[str, Any]] = []
    advisories: list[dict[str, Any]] = []
    tool_errors: list[dict[str, Any]] = []
    for name, script in (
        ("ai-pattern", "check-ai-patterns.js"),
        ("degeneration", "check-degeneration.js"),
    ):
        path = root / script
        if not path.is_file():
            tool_errors.append({"type": "TOOL_UNAVAILABLE", "tool": script, "message": f"missing {script}"})
            continue
        completed = subprocess.run(
            [node, str(path), "--check", "--json", "--fail-on=blocking", str(body)],
            text=True, encoding="utf-8", capture_output=True, check=False,
        )
        findings = _json_findings(completed.stdout)
        if findings is None or completed.returncode not in {0, 1}:
            tool_errors.append({"type": "TOOL_ERROR", "tool": script, "source": name,
                                "message": completed.stderr.strip() or f"{script} exited {completed.returncode} without JSON findings"})
            continue
        for finding in findings:
            row = {"source": name, **finding}
            if name == "degeneration":
                # 退化类（复读、截断、拒绝语、工程词）不是 AI 味，不计入触发去 AI 味审查的语义条数。
                row.setdefault("review", "mechanical")
            if exempt and name == "ai-pattern" and finding.get("severity") == "blocking":
                # 豁免只管 AI 句式；退化类（复读、截断、拒绝语、工程词）照常必须修。
                advisories.append({**row, "severity": "advisory", "exempted": "去味:跳过"})
                continue
            (blocking if finding.get("severity") == "blocking" else advisories).append(row)

    punctuation = root / "normalize-punctuation.js"
    if not punctuation.is_file():
        tool_errors.append({"type": "TOOL_UNAVAILABLE", "tool": punctuation.name,
                            "message": "missing normalize-punctuation.js"})
    else:
        completed = subprocess.run(
            [node, str(punctuation), "--check", str(body)],
            text=True, encoding="utf-8", capture_output=True, check=False,
        )
        if completed.returncode == 1:
            blocking.append(
                {"type": "PUNCTUATION_NOT_NORMALIZED", "message": (completed.stdout or completed.stderr).strip()}
            )
        elif completed.returncode != 0:
            tool_errors.append({"type": "TOOL_ERROR", "tool": punctuation.name,
                                "message": completed.stderr.strip() or f"exited {completed.returncode}"})

    outline_copy = root / "check-outline-copy.js"
    if not outline_copy.is_file():
        tool_errors.append({"type": "TOOL_UNAVAILABLE", "tool": outline_copy.name,
                            "message": "missing check-outline-copy.js"})
    else:
        completed = subprocess.run(
            [node, str(outline_copy), "--outline", str(outline), str(body)],
            text=True, encoding="utf-8", capture_output=True, check=False,
        )
        if completed.returncode != 0:
            advisories.append(
                {"source": "outline-copy", "type": "OUTLINE_COPY_REVIEW", "review": "semantic",
                 "message": completed.stdout.strip()}
            )
    return {
        "status": "unavailable" if tool_errors else ("fail" if blocking else "pass"),
        "blocking_findings": blocking,
        "advisories": advisories,
        "semantic_advisories": _semantic_advisories(advisories),
        "tool_errors": tool_errors,
    }


# chapter check 顶层 status 与退出码：一眼分清「能提交」「要作者定」「正文要改」「工具坏了」。
CHECK_EXIT_CODES = {"ready": 0, "needs_decision": 0, "blocked": 1, "invalid": 1, "tool_unavailable": 3}
ERROR_EXIT_CODES = {"TOOL_UNAVAILABLE": 3}
ACCEPT_FLOOR_RATIO = 0.5
BASELINE_FILE = "over_length_baseline.json"


class ChapterRefused(WordcountError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _check_status(length: dict[str, Any], quality: dict[str, Any]) -> str:
    if quality["status"] == "unavailable":
        return "tool_unavailable"
    if quality["status"] != "pass":
        return "blocked"
    if length["status"] == "invalid":
        return "invalid"
    return "ready" if length["status"] in {"internal_pass", "borderline"} else "needs_decision"


def _body_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_over_baseline(project: Path, chapter: int, body_path: Path, actual: int) -> None:
    """第一次看到 over 时记下原稿指纹：接受超长前要证明那一次净删压缩真的做过。"""
    path = chapter_work_dir(project, chapter) / BASELINE_FILE
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        previous = None
    # 已有基线且这次更短：是压缩后的复检，保留基线；更长则是重写出的新稿，重新记。
    if isinstance(previous, dict) and isinstance(previous.get("actual"), int) and actual <= previous["actual"]:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"body_sha256": _body_digest(body_path), "actual": actual}), encoding="utf-8")


def chapter_check(project: Path, chapter: int, author_range: Any = None) -> dict[str, Any]:
    outline, body_path, target, effective_range = _project_files(project, chapter, author_range)
    try:
        body = body_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise WordcountError(f"unable to read body: {exc}") from exc
    length = evaluate_wordcount(body, target, chapter=chapter, author_range=effective_range)
    quality = check_blocking_quality(outline, body_path)
    status = _check_status(length, quality)
    if status == "ready":
        actions = ["commit"]
    elif status != "needs_decision":
        actions: list[str] = []
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
        _record_over_baseline(project, chapter, body_path, actual)
    return {
        "schema": CHAPTER_CHECK_SCHEMA,
        "status": status,
        "chapter": chapter,
        "length": length,
        "quality": quality,
        "compression": compression,
        "state_revision": state["state_revision"],
        "tracking_committed": state["last_committed_chapter"] >= chapter,
        "next_chapter_started": state["last_committed_chapter"] > chapter,
        "available_actions": actions,
    }


def fix_punctuation(project: Path, chapter: int, author_range: Any = None) -> bool:
    """Run the deterministic punctuation normalizer on the chapter body in place.

    Folding it into `chapter check --fix-punctuation` lets the parent flow close a
    chapter with one call instead of running each cleanup script separately.
    """
    _, body, _, _ = _project_files(project, chapter, author_range)
    node = shutil.which("node")
    script = Path(__file__).with_name("normalize-punctuation.js")
    if node is None or not script.is_file():
        return False  # chapter check reports the missing tool in quality.tool_errors
    before = body.read_bytes()
    subprocess.run([node, str(script), str(body)], text=True, encoding="utf-8",
                   capture_output=True, check=False)
    return body.read_bytes() != before


def _require_acceptable_length(
    project: Path, chapter: int, checked: dict[str, Any], *, force: bool, author_range: Any = None,
) -> None:
    """接受当前长度的两道底线：欠长不低于目标一半；超长先做过一次净删压缩（删掉原稿到作者范围上限
    差额的至少一半）。作者明确拍板用 --force 越过。"""
    if force:
        return
    length = checked["length"]
    if length["status"] == "under" and length["actual"] < length["target"] * ACCEPT_FLOOR_RATIO:
        raise ChapterRefused(
            "BELOW_ACCEPT_FLOOR",
            f"本章 {length['actual']} 字，不到字数目标 {length['target']} 的一半，不能直接按当前长度接受；"
            "先补细纲或改字数目标，作者明确要这个长度时加 --force",
        )
    if length["status"] == "over":
        path = chapter_work_dir(project, chapter) / BASELINE_FILE
        try:
            baseline = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            baseline = None
        _, body_path, _, _ = _project_files(project, chapter, author_range)
        valid = isinstance(baseline, dict) and isinstance(baseline.get("actual"), int)
        # 压缩要真删：至少删掉原稿到作者字数范围上限差额的一半（至少 1 字），删一两个字不算做过。
        ceiling = None
        if valid:
            gap = baseline["actual"] - length["user_band"]["max"]
            ceiling = baseline["actual"] - max(1, (gap + 1) // 2)
        compressed = (
            valid
            and baseline.get("body_sha256") != _body_digest(body_path)
            and length["actual"] <= ceiling
        )
        if not compressed:
            detail = (f"（原稿 {baseline['actual']} 字，压缩后要不超过 {ceiling} 字，现在 {length['actual']} 字）"
                      if valid else "")
            raise ChapterRefused(
                "COMPRESSION_REQUIRED",
                f"超长章节先按 compress-once 做一次净删压缩并重跑 chapter check{detail}，仍超长再接受当前长度；"
                "作者明确不压缩时加 --force",
            )


def chapter_commit(
    project: Path, chapter: int, input_path: Path, *, accept_current_length: bool,
    author_range: Any = None, force: bool = False,
) -> dict[str, Any]:
    checked = chapter_check(project, chapter, author_range)
    if checked["status"] == "tool_unavailable":
        raise ChapterRefused(
            "TOOL_UNAVAILABLE",
            "；".join(item["message"] for item in checked["quality"]["tool_errors"]) or NODE_REQUIRED,
        )
    if checked["quality"]["status"] != "pass":
        raise ChapterRefused("QUALITY_BLOCKED", "blocking quality findings must be fixed before commit")
    length_status = checked["length"]["status"]
    in_user_band = length_status in {"internal_pass", "borderline"}
    if accept_current_length:
        require(length_status in {"under", "over"}, "accept-current-length requires a valid out-of-band chapter")
        _require_acceptable_length(project, chapter, checked, force=force, author_range=author_range)
        resolution = "accepted_current_length"
    else:
        if not in_user_band:
            raise ChapterRefused(
                "LENGTH_OUT_OF_BAND",
                "chapter length is outside the user band; use accept-current-length or revise it",
            )
        resolution = "within_user_band"
    document = _read_json_object(input_path, "tracking transaction")
    require(document.get("chapter") == chapter, "tracking transaction chapter does not match command")
    require("wordcount" not in document, "tracking transaction must not provide wordcount")
    document["wordcount"] = build_project_wordcount_record(
        project, chapter, resolution=resolution, author_range=author_range,
    )
    tracking = _tracking_module()
    state = _tracking_call(tracking.apply_transaction, project, document)
    checked["tracking_committed"] = state["last_committed_chapter"] >= chapter
    checked["next_chapter_started"] = state["last_committed_chapter"] > chapter
    checked["wordcount"] = state["wordcount_records"].get(str(chapter))
    checked["mode"] = document.get("mode")
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
            subparser.add_argument("--target", required=command == "check")
            _add_range_arguments(subparser)
        if command == "checkpoint":
            subparser.add_argument("--project", type=Path,
                                   help="书目录：与 --chapter 一起从细纲读字数目标（未给 --target 时）和「字数范围」")
    chapter = commands.add_parser("chapter")
    chapter_commands = chapter.add_subparsers(dest="chapter_command", required=True)
    for command in ("check", "commit", "accept-current-length"):
        subparser = chapter_commands.add_parser(command)
        subparser.add_argument("--project", type=Path, required=True)
        subparser.add_argument("--chapter", type=int, required=True)
        _add_range_arguments(subparser)
        if command != "check":
            subparser.add_argument("--input", type=Path, required=True)
        else:
            subparser.add_argument("--fix-punctuation", action="store_true",
                                   help="先就地整理正文标点，再做检查")
        if command == "accept-current-length":
            subparser.add_argument("--force", action="store_true",
                                   help="作者明确拍板：越过欠长一半下限与超长先压缩一次的要求")
    return parser


def _add_range_arguments(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument("--min-chars", type=int, help="作者本轮给定的字数下限（须与 --max-chars 同给），优先于细纲字数范围与默认 ±15%%")
    subparser.add_argument("--max-chars", type=int, help="作者本轮给定的字数上限")


def _cli_author_range(args: argparse.Namespace) -> dict[str, int] | None:
    low, high = getattr(args, "min_chars", None), getattr(args, "max_chars", None)
    if low is None and high is None:
        return None
    if low is None or high is None:
        raise CliArgumentError("--min-chars and --max-chars must be given together")
    try:
        return normalize_author_range({"min": low, "max": high})
    except WordcountError as exc:
        raise CliArgumentError(str(exc)) from exc


def _wordcount_command(args: argparse.Namespace, author_range: dict[str, int] | None) -> int:
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
        target = args.target
        if args.project is not None:
            # 与 chapter check 同一优先级：命令行上下限 > 细纲「字数范围」 > 默认带。
            try:
                chapter = int(args.chapter or "")
                _, outline = read_chapter_outline(args.project, chapter)
                if target is None:
                    target = target_from_outline(outline)
                author_range = effective_author_range(outline, author_range)
            except (ValueError, WordcountError):
                _json_line(invalid_wordcount_result("INVALID_OUTLINE", chapter=args.chapter, case_id=args.case_id))
                return 2
        if target is None:
            _json_line(invalid_wordcount_result("INVALID_ARGUMENT", chapter=args.chapter, case_id="--target or --project is required"))
            return 2
        try:
            result = checkpoint_wordcount(
                body, target, chapter=args.chapter, case_id=args.case_id, author_range=author_range,
            )
        except WordcountError:
            result = invalid_wordcount_result("INVALID_TARGET", chapter=args.chapter, case_id=args.case_id)
    else:
        result = evaluate_wordcount(
            body, args.target, chapter=args.chapter, case_id=args.case_id, author_range=author_range,
        )
    _json_line(result)
    return 2 if result.get("status") == "invalid" else 0


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(argv) if argv is not None else sys.argv[1:]
    try:
        args = _build_parser().parse_args(raw)
        author_range = _cli_author_range(args)
    except CliArgumentError as exc:
        payload = (
            {"schema": CHAPTER_ERROR_SCHEMA, "status": "error", "error_code": "INVALID_ARGUMENT", "message": str(exc)}
            if raw[:1] == ["chapter"] else invalid_wordcount_result("INVALID_ARGUMENT", case_id=str(exc))
        )
        _json_line(payload)
        return 2
    if args.command == "wordcount":
        return _wordcount_command(args, author_range)
    try:
        if args.chapter_command == "check":
            fixed = fix_punctuation(args.project, args.chapter, author_range) if args.fix_punctuation else None
            result = chapter_check(args.project, args.chapter, author_range)
            if fixed is not None:
                result["punctuation_fixed"] = fixed
        else:
            result = chapter_commit(
                args.project, args.chapter, args.input,
                accept_current_length=args.chapter_command == "accept-current-length",
                author_range=author_range, force=getattr(args, "force", False),
            )
    except (WordcountError, OSError, UnicodeError) as exc:
        code = exc.code if isinstance(exc, ChapterRefused) else "CHECK_FAILED"
        _json_line({"schema": CHAPTER_ERROR_SCHEMA, "status": "error", "error_code": code, "message": str(exc)})
        return ERROR_EXIT_CODES.get(code, 2)
    _json_line(result)
    if args.chapter_command != "check":
        return 0
    return CHECK_EXIT_CODES[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
