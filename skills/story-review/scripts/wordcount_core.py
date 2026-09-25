#!/usr/bin/env python3
"""Small deterministic wordcount core shared by storyctl and tracking."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


WORDCOUNT_SCHEMA = "story-wordcount-result/v1"
MEASUREMENT_SCHEMA = "story-wordcount-measurement/v1"
CHECKPOINT_SCHEMA = "story-wordcount-checkpoint/v1"
METRIC = "visible_chars_v1"
RESOLUTIONS = frozenset({"within_user_band", "accepted_current_length"})

_WHITE_SPACE_CODEPOINTS = frozenset(
    [*range(0x0009, 0x000E)]
    + [
        0x0020, 0x0085, 0x00A0, 0x1680, *range(0x2000, 0x200B),
        0x2028, 0x2029, 0x202F, 0x205F, 0x3000,
    ]
)
_FRONTMATTER_KEY_RE = re.compile(r"^[A-Za-z_\u3400-\u9FFF][^:\n]{0,80}:[ \t]*(?:.*)$")
_LEADING_BLANK_RE = re.compile(r"^[\u0009\u0020\u3000]*$")
_ATX_HEADING_RE = re.compile(r"^[\u0009\u0020]{0,3}#{1,6}[\u0009\u0020]+\S")
_POSITIVE_INTEGER_RE = re.compile(r"^[1-9]\d*$")
_TARGET_LINE_RE = re.compile(r"^[ \t>*-]*字数目标[ \t]*[:：][ \t]*([1-9]\d*)[ \t]*(?:字)?[ \t]*$", re.MULTILINE)
_METRIC_LINE_RE = re.compile(r"^[ \t>*-]*字数口径[ \t]*[:：][ \t]*([A-Za-z0-9_-]+)[ \t]*$", re.MULTILINE)


class WordcountError(ValueError):
    """Expected deterministic wordcount contract failure."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise WordcountError(message)


def normalize_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def strip_recognizable_frontmatter(value: str) -> str:
    lines = value.split("\n")
    if not lines or lines[0] != "---":
        return value
    closing = next((index for index in range(1, min(len(lines), 201)) if lines[index] in {"---", "..."}), -1)
    if closing < 2 or not any(_FRONTMATTER_KEY_RE.match(line) for line in lines[1:closing]):
        return value
    return "\n".join(lines[closing + 1 :])


def visible_body(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("body must be a string")
    text = normalize_newlines(value)
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = strip_recognizable_frontmatter(text).split("\n")
    while lines and _LEADING_BLANK_RE.match(lines[0]):
        lines.pop(0)
    if lines and _ATX_HEADING_RE.match(lines[0]):
        lines.pop(0)
    return "\n".join(lines)


def count_visible_chars(value: str) -> int:
    return sum(ord(character) not in _WHITE_SPACE_CODEPOINTS for character in visible_body(value))


def parse_target(value: Any) -> int:
    raw = str(value if value is not None else "")
    if not _POSITIVE_INTEGER_RE.fullmatch(raw):
        raise WordcountError("target must be a positive integer")
    target = int(raw)
    require(target <= 9_007_199_254_740_991, "target exceeds Number.MAX_SAFE_INTEGER")
    return target


def compute_wordcount_bands(value: Any) -> dict[str, dict[str, int]]:
    target = parse_target(value)
    return {
        "internal": {"min": (target * 88 + 99) // 100, "max": target * 112 // 100},
        "user": {"min": (target * 85 + 99) // 100, "max": target * 115 // 100},
    }


def invalid_wordcount_result(
    reason: str, *, chapter: Any = None, case_id: Any = None,
    target: int | None = None, actual: int | None = None,
) -> dict[str, Any]:
    return {
        "schema": WORDCOUNT_SCHEMA, "metric": METRIC, "chapter": chapter, "case_id": case_id,
        "target": target, "actual": actual, "internal_band": None, "user_band": None,
        "signed_error_pct": None, "absolute_error_pct": None,
        "status": "invalid", "invalid_reason": reason,
    }


def measure_wordcount(value: str, *, chapter: Any = None, case_id: Any = None) -> dict[str, Any]:
    try:
        actual = count_visible_chars(value)
    except (TypeError, ValueError):
        return {
            "schema": MEASUREMENT_SCHEMA, "metric": METRIC, "chapter": chapter,
            "case_id": case_id, "actual": None, "status": "invalid", "invalid_reason": "INVALID_BODY",
        }
    return {
        "schema": MEASUREMENT_SCHEMA, "metric": METRIC, "chapter": chapter,
        "case_id": case_id, "actual": actual, "status": "measured", "invalid_reason": None,
    }


def evaluate_wordcount(
    value: str, target_value: Any, *, chapter: Any = None, case_id: Any = None,
) -> dict[str, Any]:
    try:
        target = parse_target(target_value)
    except (TypeError, ValueError):
        return invalid_wordcount_result("INVALID_TARGET", chapter=chapter, case_id=case_id)
    try:
        actual = count_visible_chars(value)
    except (TypeError, ValueError):
        return invalid_wordcount_result("INVALID_BODY", chapter=chapter, case_id=case_id, target=target)
    if actual == 0:
        return invalid_wordcount_result("EMPTY_BODY", chapter=chapter, case_id=case_id, target=target, actual=actual)
    bands = compute_wordcount_bands(target)
    internal_pass = bands["internal"]["min"] <= actual <= bands["internal"]["max"]
    user_pass = bands["user"]["min"] <= actual <= bands["user"]["max"]
    status = "internal_pass" if internal_pass else (
        "borderline" if user_pass else ("under" if actual < bands["user"]["min"] else "over")
    )
    signed_error = (actual - target) / target
    return {
        "schema": WORDCOUNT_SCHEMA, "metric": METRIC, "chapter": chapter, "case_id": case_id,
        "target": target, "actual": actual,
        "internal_band": {**bands["internal"], "status": "pass" if internal_pass else "fail"},
        "user_band": {**bands["user"], "status": "pass" if user_pass else "fail"},
        "signed_error_pct": signed_error, "absolute_error_pct": abs(signed_error),
        "status": status, "invalid_reason": None,
    }


def checkpoint_wordcount(
    value: str, target_value: Any, *, chapter: Any = None, case_id: Any = None,
) -> dict[str, Any]:
    target = parse_target(target_value)
    actual = count_visible_chars(value)
    user = compute_wordcount_bands(target)["user"]
    return {
        "schema": CHECKPOINT_SCHEMA, "metric": METRIC, "chapter": chapter, "case_id": case_id,
        "target": target, "actual": actual, "user_band": user,
        "remaining_user_range": {
            "min": max(0, user["min"] - actual),
            "max": max(0, user["max"] - actual),
        },
    }


def target_from_outline(value: str) -> int:
    text = normalize_newlines(value)
    if text.startswith("\ufeff"):
        text = text[1:]
    targets = list(dict.fromkeys(_TARGET_LINE_RE.findall(text)))
    metrics = list(dict.fromkeys(_METRIC_LINE_RE.findall(text)))
    require(len(targets) == 1, "字数目标 must appear exactly once with one value")
    require(metrics == [METRIC], f"字数口径 must appear exactly once as {METRIC}")
    return parse_target(targets[0])


def _chapter_number_from_name(name: str, *, outline: bool) -> int | None:
    # 改稿流程把原文备份为 第N章_章名_原稿_{日期}.md，与 hooks 一样不把它当本章正文。
    if not outline and "_原稿_" in name:
        return None
    pattern = r"^细纲_第0*(\d+)章.*\.md$" if outline else r"^第0*(\d+)章(?:[_\- 　].*)?\.md$"
    match = re.match(pattern, name)
    return int(match.group(1)) if match else None


def find_chapter_file(directory: Path, chapter: int, *, outline: bool) -> Path:
    require(isinstance(chapter, int) and not isinstance(chapter, bool) and chapter >= 1, "chapter must be >= 1")
    require(directory.is_dir(), f"chapter directory is missing: {directory}")
    matches = sorted(
        path for path in directory.iterdir()
        if path.is_file() and _chapter_number_from_name(path.name, outline=outline) == chapter
    )
    label = "outline" if outline else "body"
    require(len(matches) == 1, f"chapter {chapter} must have exactly one {label} file")
    return matches[0]


def build_project_wordcount_record(project: Path, chapter: int, *, resolution: str) -> dict[str, Any]:
    require(resolution in RESOLUTIONS, f"unsupported wordcount resolution: {resolution}")
    root = project.resolve()
    outline_path = find_chapter_file(root / "大纲", chapter, outline=True)
    body_path = find_chapter_file(root / "正文", chapter, outline=False)
    try:
        target = target_from_outline(outline_path.read_text(encoding="utf-8"))
        body_bytes = body_path.read_bytes()
        body = body_bytes.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise WordcountError(f"unable to read chapter files: {exc}") from exc
    result = evaluate_wordcount(body, target, chapter=chapter)
    require(result["status"] != "invalid", f"invalid chapter wordcount: {result['invalid_reason']}")
    in_user_band = result["status"] in {"internal_pass", "borderline"}
    require(
        (resolution == "within_user_band" and in_user_band)
        or (resolution == "accepted_current_length" and not in_user_band),
        "wordcount resolution does not match the current length",
    )
    return {
        "metric": METRIC,
        "target": result["target"],
        "actual": result["actual"],
        "status": result["status"],
        "resolution": resolution,
        "body_sha256": hashlib.sha256(body_bytes).hexdigest(),
    }


def normalize_wordcount_record(value: object) -> dict[str, Any]:
    require(isinstance(value, dict), "wordcount record must be an object")
    require(
        set(value) == {"metric", "target", "actual", "status", "resolution", "body_sha256"},
        "wordcount record fields are invalid",
    )
    require(value.get("metric") == METRIC, "wordcount metric is unsupported")
    target = parse_target(value.get("target"))
    actual = value.get("actual")
    require(isinstance(actual, int) and not isinstance(actual, bool) and actual >= 1, "wordcount actual is invalid")
    expected = evaluate_wordcount("字" * actual, target)
    require(value.get("status") == expected["status"], "wordcount status does not match target and actual")
    resolution = value.get("resolution")
    require(resolution in RESOLUTIONS, "wordcount resolution is unsupported")
    in_user_band = expected["status"] in {"internal_pass", "borderline"}
    require((resolution == "within_user_band") == in_user_band, "wordcount resolution does not match status")
    digest = value.get("body_sha256")
    require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is not None, "body_sha256 is invalid")
    return dict(value)


def validate_current_wordcount_record(project: Path, chapter: int, value: object) -> dict[str, Any]:
    record = normalize_wordcount_record(value)
    current = build_project_wordcount_record(project, chapter, resolution=record["resolution"])
    require(record == current, "wordcount record is stale for the current body or target")
    return record
