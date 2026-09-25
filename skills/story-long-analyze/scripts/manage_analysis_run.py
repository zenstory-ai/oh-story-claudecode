#!/usr/bin/env python3
"""Plan, commit, split, and recover long-analysis batches.

Runtime state lives only in the managed block of ``_progress.md``. Plans are
printed as JSON and are never persisted. Batch caches are complete recovery
evidence, not a second state database. An existing chapter summary is never
overwritten: to redo a chapter, delete its summary and plan again.
"""

from __future__ import annotations

import argparse
import codecs
import csv
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from inspect_existing_assets import inspect


STATE_START = "<!-- story-long-analyze:runtime-state:start -->"
STATE_END = "<!-- story-long-analyze:runtime-state:end -->"
CACHE_START = "<!-- story-long-analyze:cache:start -->"
CACHE_END = "<!-- story-long-analyze:cache:end -->"
MODEL_START = "<!-- MODEL_OUTPUT_START -->"
MODEL_END = "<!-- MODEL_OUTPUT_END -->"
CHAPTER_TOKEN_RE = re.compile(r"<!--\s*CHAPTER_(START|END):(\d+)\s*-->")
CHAPTER_BLOCK_RE = re.compile(
    r"<!--\s*CHAPTER_START:(\d+)\s*-->\s*(.*?)\s*<!--\s*CHAPTER_END:\1\s*-->", re.DOTALL
)
BATCH_ID_RE = re.compile(r"^(RAW|REUSE)-(\d+)-(\d+)$")
COMPACT_FIELDS = (
    "概要", "因果", "关键行动", "局面结果", "涉及人物", "信息变化", "状态变化",
    "三维节奏", "章尾钩子", "证据",
)
POINT_HEADER_RE = re.compile(r"^P(\d+)\s+\*\*(.+?)\*\*\s*[：:]\s*(.+)$")
POINT_TAG_RE = re.compile(r"^主题标签\s*[：:]?\s*([^|｜]*?)\s*[|｜]\s*基调\s*[：:]?\s*(.*?)\s*$")
THEMES = ("爱情", "亲情", "友情", "权力", "金钱", "成长", "复仇", "悬念", "搞笑", "热血", "日常", "其他")
TONES = ("紧张", "轻松", "悲伤", "热血", "爽", "甜", "温馨", "恐怖", "压抑", "其他")
POINT_TYPES = ("转折点", "信息揭示", "冲突", "解决", "铺垫", "行动", "对话", "状态变化")
THEME_ALIASES = {"恋爱": "爱情", "权谋": "权力", "政治": "权力", "幽默": "搞笑"}
TONE_ALIASES = {"悲痛": "悲伤", "伤感": "悲伤", "悲愤": "悲伤", "痛快": "爽", "解气": "爽", "惊悚": "恐怖",
                "恐惧": "恐怖", "危险": "紧张", "危急": "紧张", "绝望": "压抑", "无力": "压抑", "释然": "轻松"}
POINT_ALIASES = {"揭示": "信息揭示", "转折": "转折点", "变化": "状态变化", "动作": "行动",
                 "交谈": "对话", "化解": "解决"}
MIN_PLOT_POINTS = 10
MAX_PLOT_POINTS = 30
MAX_CHAPTERS = 3
MAX_CHARS = 25_000
# Stage 3-6 each run once over complete Stage 2 output; their rows decide 最终状态.
FINAL_STAGES = ("stage3", "stage4", "stage5", "stage6")
LEGACY_FINAL_RE = re.compile(r"(?m)^([ \t]*(?:[-*][ \t]*)?最终状态[ \t]*[：:][ \t]*)([A-Za-z0-9_]+)")


class RunError(ValueError):
    def __init__(self, code: str, detail: str, author_message: Optional[str] = None) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.author_message = author_message


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalized(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".%s." % path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, str(path))
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def require_root(root: Path) -> Path:
    root = root.resolve()
    if not root.exists():
        raise RunError("root_not_found", str(root))
    if not root.is_dir():
        raise RunError("root_is_not_directory", str(root))
    try:
        next(root.iterdir(), None)
    except OSError as exc:
        raise RunError("root_unreadable", str(exc)) from exc
    return root


def read_index(root: Path, index_arg: Optional[Path] = None) -> List[Dict[str, Any]]:
    path = (index_arg.resolve() if index_arg else root / "chapter_index.csv")
    if not path.is_file():
        raise RunError("chapter_index_required", str(path))
    rows = []  # type: List[Dict[str, Any]]
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"chapter", "start_line", "end_line", "char_count", "source_locator", "chapter_sha256"}
            missing = required - set(reader.fieldnames or ())
            if missing:
                raise RunError("chapter_index_invalid", "missing columns: %s" % ", ".join(sorted(missing)))
            for raw in reader:
                row = dict(raw)
                try:
                    row["chapter"] = int(row["chapter"])
                    row["start_line"] = int(row["start_line"])
                    row["end_line"] = int(row["end_line"])
                    row["char_count"] = int(row["char_count"])
                except (TypeError, ValueError) as exc:
                    raise RunError("chapter_index_invalid", "numeric column invalid") from exc
                if not re.fullmatch(r"[0-9a-f]{64}", str(row["chapter_sha256"])):
                    raise RunError("chapter_index_invalid", "chapter_sha256 invalid")
                rows.append(row)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise RunError("chapter_index_unreadable", str(exc)) from exc
    if [row["chapter"] for row in rows] != list(range(1, len(rows) + 1)):
        raise RunError("chapter_index_invalid", "chapter ids must be continuous from 1")
    return rows


def range_sha256(rows: Sequence[Dict[str, Any]], start: int, end: int) -> str:
    selected = [row for row in rows if start <= row["chapter"] <= end]
    if [row["chapter"] for row in selected] != list(range(start, end + 1)):
        raise RunError("range_not_in_index", "%s-%s" % (start, end))
    payload = "range-v1\n" + "".join(
        "%s:%s\n" % (row["chapter"], row["chapter_sha256"]) for row in selected
    )
    return sha256(payload.encode("ascii"))


def decode_progress(raw: bytes) -> Tuple[str, bool, str]:
    bom = raw.startswith(codecs.BOM_UTF8)
    text = raw.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"
    return text, bom, newline


def empty_state() -> Dict[str, Any]:
    return {"batches": {}, "stages": {}}


def table_cells(line: str) -> List[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def load_state(progress: Path) -> Tuple[Dict[str, Any], bytes]:
    raw = progress.read_bytes() if progress.is_file() else b""
    text, _, _ = decode_progress(raw)
    state = empty_state()
    start_count = text.count(STATE_START)
    end_count = text.count(STATE_END)
    if start_count != end_count or start_count > 1:
        raise RunError(
            "progress_state_block_invalid",
            "expected zero or one complete managed state block; found start=%s end=%s"
            % (start_count, end_count),
        )
    match = re.search(re.escape(STATE_START) + r"(.*?)" + re.escape(STATE_END), text, re.DOTALL)
    if not match:
        return state, raw
    section = None
    for line in match.group(1).splitlines():
        if line.strip() == "### 批次状态":
            section = "batches"
            continue
        if line.strip() == "### 阶段状态":
            section = "stages"
            continue
        if not line.lstrip().startswith("|") or set(line.replace("|", "").replace("-", "").replace(":", "").strip()) == set():
            continue
        cells = table_cells(line)
        if section == "batches" and cells and cells[0] not in {"批次ID", "---"} and len(cells) >= 7:
            try:
                start, end = [int(value) for value in cells[1].split("-", 1)]
            except (ValueError, IndexError):
                continue
            state["batches"][cells[0]] = {
                "batch_id": cells[0], "start": start, "end": end, "input_kind": cells[2],
                "range_sha256": cells[3], "status": cells[4],
                "parent": "" if cells[5] == "-" else cells[5],
                "cache": "" if cells[6] == "-" else cells[6],
            }
        elif section == "stages" and cells and cells[0] not in {"阶段", "---"} and len(cells) >= 3:
            state["stages"][cells[0]] = {"status": cells[1], "output": "" if cells[2] == "-" else cells[2]}
    return state, raw


def final_status(stages: Dict[str, Dict[str, str]]) -> str:
    """Value for the ``最终状态`` line that session hooks read (Stage 3-6 rows)."""
    statuses = [stages.get(stage, {}).get("status") for stage in FINAL_STAGES]
    if all(status in {"completed", "completed_with_errors"} for status in statuses):
        return "completed_with_errors" if "completed_with_errors" in statuses else "completed"
    return "pending"


def render_state(state: Dict[str, Any], newline: str, final_line: bool = True) -> str:
    lines = [STATE_START, "## 长篇拆文运行状态", ""]
    if final_line and state["stages"]:
        lines.extend(["- 最终状态：%s" % final_status(state["stages"]), ""])
    lines.extend(["### 批次状态",
                  "| 批次ID | 章节范围 | 输入 | 原文范围hash | 状态 | 父批次 | 缓存 |",
                  "|---|---|---|---|---|---|---|"])
    batches = list(state["batches"].values())
    batches.sort(key=lambda row: (row["start"], row["end"], row["batch_id"]))
    for row in batches:
        lines.append("| %s | %s-%s | %s | %s | %s | %s | %s |" % (
            row["batch_id"], row["start"], row["end"], row["input_kind"],
            row["range_sha256"], row["status"], row.get("parent") or "-", row.get("cache") or "-"))
    lines.extend(["", "### 阶段状态", "| 阶段 | 状态 | 产物 |", "|---|---|---|"])
    for stage in sorted(state["stages"]):
        row = state["stages"][stage]
        lines.append("| %s | %s | %s |" % (stage, row["status"], row.get("output") or "-"))
    lines.append(STATE_END)
    return newline.join(lines)


def write_state(progress: Path, state: Dict[str, Any]) -> bool:
    raw = progress.read_bytes() if progress.is_file() else b""
    text, bom, newline = decode_progress(raw)
    pattern = re.compile(re.escape(STATE_START) + r".*?" + re.escape(STATE_END), re.DOTALL)
    # Hooks read the first 最终状态 in the file. A legacy project keeps its own
    # line as that single value; the runtime only promotes it once Stage 3-6
    # are all complete and never demotes it.
    existing = pattern.search(text)
    head = text[:existing.start()] if existing else text
    legacy = LEGACY_FINAL_RE.search(head)
    status = final_status(state["stages"])
    if legacy and status != "pending" and legacy.group(2) != status:
        head = head[:legacy.start(2)] + status + head[legacy.end(2):]
        text = head + (text[existing.start():] if existing else "")
    block = render_state(state, newline, final_line=legacy is None)
    if pattern.search(text):
        updated = pattern.sub(lambda _: block, text, count=1)
    else:
        if not text:
            text = "# 深度拆解进度" + newline + "- schema_version: 2" + newline
        separator = "" if text.endswith(newline + newline) else (newline if text.endswith(newline) else newline + newline)
        updated = text + separator + block + newline
    data = ((codecs.BOM_UTF8 if bom else b"") + updated.encode("utf-8"))
    if data == raw:
        return False
    atomic_write(progress, data)
    return True


def summary_path(root: Path, chapter: int) -> Path:
    return root / "章节" / ("第%s章_摘要.md" % chapter)


def cache_complete(path: Path) -> bool:
    try:
        text = normalized(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError):
        return False
    return text.rstrip().endswith(CACHE_END) and text.count(MODEL_START) == 1 and text.count(MODEL_END) == 1


def cache_path(root: Path, batch_id: str) -> Path:
    return root / "_analysis_cache" / ("批次-%s.md" % batch_id)


def completed_batch(root: Path, row: Dict[str, Any], rows: Optional[Sequence[Dict[str, Any]]]) -> bool:
    if row.get("status") not in {"completed", "success"} or not all(summary_path(root, chapter).is_file() for chapter in range(row["start"], row["end"] + 1)):
        return False
    path = root / row.get("cache", "") if row.get("cache") else cache_path(root, row["batch_id"])
    if not cache_complete(path):
        return False
    try:
        metadata = parse_cache(path)
    except (OSError, UnicodeError, RunError):
        return False
    if (metadata.get("batch_id"), metadata.get("start"), metadata.get("end")) != (
        row["batch_id"], row["start"], row["end"]
    ):
        return False
    if metadata.get("range_sha256") != row.get("range_sha256"):
        return False
    if row["input_kind"] == "raw-original":
        return rows is not None and row.get("range_sha256") == range_sha256(rows, row["start"], row["end"])
    return True


def compact_ranges(chapters: Iterable[int]) -> List[Tuple[int, int]]:
    values = sorted(set(chapters))
    if not values:
        return []
    result = []
    start = previous = values[0]
    for value in values[1:]:
        if value == previous + 1:
            previous = value
        else:
            result.append((start, previous))
            start = previous = value
    result.append((start, previous))
    return result


def chunk_range(start: int, end: int, index_by_chapter: Optional[Dict[int, Dict[str, Any]]]) -> List[Tuple[int, int]]:
    result = []
    current_start = start
    count = 0
    chars = 0
    previous = start - 1
    for chapter in range(start, end + 1):
        chapter_chars = index_by_chapter[chapter]["char_count"] if index_by_chapter else 0
        if count and (count + 1 > MAX_CHAPTERS or chars + chapter_chars > MAX_CHARS):
            result.append((current_start, previous))
            current_start = chapter
            count = 0
            chars = 0
        count += 1
        chars += chapter_chars
        previous = chapter
    result.append((current_start, previous))
    return result


def invalid_batch_targets(root: Path, rows: Optional[Sequence[Dict[str, Any]]],
                          state: Dict[str, Any]) -> Tuple[Set[int], Set[int]]:
    """Chapters of recorded batches that no longer verify (cache lost or source changed)."""
    raw = set()
    reuse = set()
    for batch in state["batches"].values():
        chapters = set(range(batch["start"], batch["end"] + 1))
        # Split children stay owed until committed, even when summaries exist.
        pending_child = batch.get("parent") and batch.get("status") == "planned"
        if not pending_child and (
            batch.get("status") not in {"completed", "success"} or completed_batch(root, batch, rows)
        ):
            continue
        if batch.get("input_kind") == "raw-original":
            raw.update(chapters)
        elif batch.get("input_kind") == "existing-results":
            reuse.update(chapters)
    return raw, reuse


def add_recoverable_caches(root: Path, state: Dict[str, Any],
                           rows: Optional[Sequence[Dict[str, Any]]]) -> Tuple[List[Dict[str, Any]], Set[int]]:
    """Use complete caches in this read-only plan without persisting recovery."""
    cache_dir = root / "_analysis_cache"
    recoverable = []
    covered = set()  # type: Set[int]
    for path in sorted(cache_dir.glob("批次-*.md")) if cache_dir.is_dir() else []:
        try:
            metadata = parse_cache(path)
            batch_id = metadata["batch_id"]
            input_kind, start, end = parse_batch_id(batch_id)
            if metadata["input_kind"] != input_kind:
                continue
            current_hash = metadata["range_sha256"]
            if input_kind == "raw-original":
                if rows is None or current_hash != range_sha256(rows, start, end):
                    continue
            records = parse_model_output(metadata["model_output"], start, end, input_kind)
            missing = [chapter for chapter in range(start, end + 1) if not summary_path(root, chapter).is_file()]
            if missing and not all(chapter in records for chapter in missing):
                continue
            covered.update(range(start, end + 1))
            current = state["batches"].get(batch_id)
            needs_state_repair = current is None or not completed_batch(root, current, rows)
            if missing or needs_state_repair:
                recoverable.append({"batch_id": batch_id, "cache": path.relative_to(root).as_posix(),
                                    "missing_summary_chapters": missing,
                                    "state_repair_required": needs_state_repair})
                if missing:
                    continue
            recovered = {
                "batch_id": batch_id, "start": start, "end": end, "input_kind": input_kind,
                "range_sha256": current_hash, "status": "completed", "parent": "",
                "cache": path.relative_to(root).as_posix(),
            }
            if current is None or not completed_batch(root, current, rows):
                state["batches"][batch_id] = recovered
        except (OSError, UnicodeError, RunError, ValueError):
            continue
    return recoverable, covered


def plan_command(args: argparse.Namespace) -> Dict[str, Any]:
    root = require_root(args.root)
    report = inspect(root, args.expected_chapters)
    state, _ = load_state(root / "_progress.md")
    index_rows = None  # type: Optional[List[Dict[str, Any]]]
    index_path = args.index.resolve() if args.index else root / "chapter_index.csv"
    if index_path.is_file():
        index_rows = read_index(root, index_path)
    recoverable_caches, cache_covered = add_recoverable_caches(root, state, index_rows)
    expected = report.get("expected_chapters") or (len(index_rows) if index_rows else None)
    if not expected:
        raise RunError("expected_chapters_unknown", "build the chapter index or pass --expected-chapters")
    semantic = set(report["completed_semantic_chapters"])
    summaries = set(report["completed_summary_chapters"])
    all_chapters = set(range(1, int(expected) + 1))
    invalid_raw, invalid_reuse = invalid_batch_targets(root, index_rows, state)

    raw_targets = (all_chapters - semantic) | invalid_raw
    if args.intent == "enhance":
        reuse_targets = (semantic - raw_targets) | invalid_reuse
    else:
        reuse_targets = ((semantic - summaries) | invalid_reuse) - raw_targets
    raw_targets -= cache_covered
    reuse_targets -= cache_covered
    if raw_targets and index_rows is None:
        raise RunError("chapter_index_required", "raw-original work remains")
    if index_rows is not None:
        absent = raw_targets - {row["chapter"] for row in index_rows}
        if absent:
            raise RunError("range_not_in_index", ",".join(map(str, sorted(absent))))
    mapping_blocked = set(report.get("chapter_mapping_blocked_chapters", []))
    if mapping_blocked & (raw_targets | reuse_targets):
        raise RunError(
            "chapter_mapping_ambiguous",
            "; ".join(report.get("chapter_mapping_conflicts", [])) or "legacy chapter identity is unresolved",
            report.get("chapter_mapping_author_message"),
        )

    selected = []  # type: List[Dict[str, Any]]
    index_by_chapter = {row["chapter"]: row for row in index_rows or []}
    preferred_paths = report["chapter_sources"]["preferred_paths"]
    for kind, targets in (("raw-original", raw_targets), ("existing-results", reuse_targets)):
        for range_start, range_end in compact_ranges(targets):
            for start, end in chunk_range(range_start, range_end, index_by_chapter if kind == "raw-original" else None):
                selected.append({"input_kind": kind, "start": start, "end": end})

    # Persisted split children replace any recombined parent range on later plans.
    split_children = [
        row for row in state["batches"].values()
        if row.get("parent") and row.get("status") != "superseded"
    ]
    for child in split_children:
        for item in list(selected):
            if item["input_kind"] == child["input_kind"] and item["start"] <= child["start"] and child["end"] <= item["end"]:
                selected.remove(item)
                if item["start"] < child["start"]:
                    selected.append({"input_kind": item["input_kind"], "start": item["start"], "end": child["start"] - 1})
                selected.append({"input_kind": child["input_kind"], "start": child["start"], "end": child["end"]})
                if child["end"] < item["end"]:
                    selected.append({"input_kind": item["input_kind"], "start": child["end"] + 1, "end": item["end"]})
                break

    batches = []
    raw_reads = 0
    result_reads = 0
    for item in sorted(selected, key=lambda value: (value["start"], value["end"], value["input_kind"])):
        prefix = "RAW" if item["input_kind"] == "raw-original" else "REUSE"
        batch_id = "%s-%s-%s" % (prefix, item["start"], item["end"])
        current_range_hash = range_sha256(index_rows, item["start"], item["end"]) if item["input_kind"] == "raw-original" else "existing-results"
        prior = state["batches"].get(batch_id)
        if prior and completed_batch(root, prior, index_rows):
            continue
        if item["input_kind"] == "raw-original":
            sources = [index_by_chapter[chapter]["source_locator"] for chapter in range(item["start"], item["end"] + 1)]
            raw_reads += len(sources)
        else:
            sources = sorted(set(preferred_paths.get(str(chapter), "") for chapter in range(item["start"], item["end"] + 1)) - {""})
            result_reads += len(sources)
        batches.append({
            "batch_id": batch_id, "chapter_range": [item["start"], item["end"]],
            "input_kind": item["input_kind"], "range_sha256": current_range_hash,
            "source_files": sources, "cache": "_analysis_cache/批次-%s.md" % batch_id,
            "chapter_chars": [index_by_chapter[chapter]["char_count"] for chapter in range(item["start"], item["end"] + 1)]
            if item["input_kind"] == "raw-original" else [],
        })
    required_stages = list(report.get("stage_repairs", []))
    if batches or recoverable_caches:
        required_stages = sorted(set(required_stages + ["stage2"]))
    summary_gaps = sorted(all_chapters - summaries)
    payload = {
        "ok": True, "root": str(root), "intent": args.intent,
        "classification": report["classification"], "recommended_path": report["recommended_path"],
        "mixed_sources": report["mixed_sources"], "batches": batches,
        "remaining_batches": len(batches),
        "recoverable_caches": recoverable_caches,
        "summary_gaps": summary_gaps,
        "read_counts": {"raw_chapters": raw_reads, "existing_result_files": result_reads},
        "required_stages": required_stages,
        "state_written": False,
    }
    if args.next is not None:
        if args.next < 0:
            raise RunError("invalid_next", str(args.next))
        # Dispatch one batch at a time without re-reading the whole remaining plan;
        # counts above still describe everything that is left.
        payload["batches"] = batches[:args.next]
        payload["summary_gaps"] = ["%s-%s" % pair if pair[0] != pair[1] else str(pair[0])
                                   for pair in compact_ranges(summary_gaps)]
    return payload


def parse_batch_id(batch_id: str) -> Tuple[str, int, int]:
    match = BATCH_ID_RE.fullmatch(batch_id)
    if not match:
        raise RunError("invalid_batch_id", batch_id)
    start, end = int(match.group(2)), int(match.group(3))
    if start < 1 or end < start:
        raise RunError("invalid_batch_range", batch_id)
    return ("raw-original" if match.group(1) == "RAW" else "existing-results", start, end)


def compact_field(body: str, name: str) -> str:
    match = re.search(r"(?m)^\*\*%s\*\*\s*[：:]\s*(\S.*)$" % re.escape(name), body)
    if not match:
        raise RunError("chapter_schema_incomplete", "missing field: %s" % name)
    value = match.group(1).strip()
    if "{" in value or "}" in value:
        raise RunError("template_placeholder", name)
    return value


def map_enum(value: str, allowed: Sequence[str], aliases: Dict[str, str], default: str = "其他") -> str:
    """Map one enum value; with several listed values, the first that maps wins."""
    for token in [value.strip()] + re.split(r"[、/，,；;\s]+", value.strip()):
        if token in allowed:
            return token
        if token in aliases:
            return aliases[token]
        for item in allowed:
            if item != "其他" and token.startswith(item):
                return item
    return default


def parse_plot_points(body: str, chapter: int, minimum: int) -> List[Dict[str, Any]]:
    """Parse the repeated ``P{n}`` blocks that follow ``**情节点**：``."""
    match = re.search(r"(?m)^\*\*情节点\*\*\s*[：:]\s*$", body)
    if not match:
        raise RunError("chapter_schema_incomplete", "chapter %s missing field: 情节点" % chapter)
    points = []  # type: List[Dict[str, Any]]
    for line in body[match.end():].split("\n"):
        stripped = line.strip()
        header = POINT_HEADER_RE.match(stripped)
        if header:
            segments = [item.strip() for item in re.split(r"[|｜]", header.group(3))]
            # Tolerate the tag written inline at the end of the P line.
            inline = POINT_TAG_RE.match(" | ".join(segments[-2:])) if len(segments) >= 3 else None
            rest = segments[1:-2] if inline else segments[1:]
            if not segments[0].startswith("类型") or not rest or not rest[0]:
                raise RunError("plot_point_invalid", "chapter %s P%s needs 类型 and 白描" % (chapter, header.group(1)))
            points.append({"number": int(header.group(1)), "title": header.group(2).strip(),
                           "type": segments[0][2:].lstrip(" ：:"), "rest": rest, "quote": [],
                           "tag": (inline.group(1), inline.group(2)) if inline else None})
            continue
        if not stripped or stripped == "---":
            continue
        if not points or points[-1]["tag"] is not None:
            raise RunError("plot_point_invalid", "chapter %s: unexpected line %r" % (chapter, stripped[:40]))
        tag = POINT_TAG_RE.match(stripped)
        if tag:
            points[-1]["tag"] = (tag.group(1), tag.group(2))
        else:
            points[-1]["quote"].append(stripped)
    if [point["number"] for point in points] != list(range(1, len(points) + 1)):
        raise RunError("plot_point_invalid", "chapter %s: points must be numbered P1..Pn" % chapter)
    if not minimum <= len(points) <= MAX_PLOT_POINTS:
        raise RunError("plot_point_count", "chapter %s has %s points; expected %s-%s"
                       % (chapter, len(points), minimum, MAX_PLOT_POINTS))
    for point in points:
        if point["tag"] is None:
            raise RunError("plot_point_invalid", "chapter %s P%s missing 主题标签/基调 line" % (chapter, point["number"]))
        text = "%s %s %s" % (point["title"], " ".join(point["rest"]), " ".join(point["quote"]))
        if "{" in text or "}" in text:
            raise RunError("template_placeholder", "chapter %s P%s" % (chapter, point["number"]))
    return points


def parse_model_output(text: str, start: int, end: int, input_kind: str) -> Dict[int, Dict[str, Any]]:
    text = normalized(text)
    if "BATCH_ERROR:" in text:
        raise RunError("extractor_reported_error", "model returned BATCH_ERROR")
    if any(marker in text for marker in (CACHE_START, CACHE_END, MODEL_START, MODEL_END)):
        raise RunError("reserved_marker_in_output", "model output contains a runtime cache marker")
    expected_tokens = [token for chapter in range(start, end + 1) for token in (("START", chapter), ("END", chapter))]
    actual_tokens = [(match.group(1), int(match.group(2))) for match in CHAPTER_TOKEN_RE.finditer(text)]
    if input_kind == "raw-original" and actual_tokens != expected_tokens:
        raise RunError("chapter_marker_mismatch", "expected %s; received %s" % (expected_tokens, actual_tokens))
    if actual_tokens and actual_tokens != expected_tokens:
        raise RunError("chapter_marker_mismatch", "expected %s; received %s" % (expected_tokens, actual_tokens))
    # Projections rebuilt from old results may hold fewer beats than a fresh reading.
    minimum = MIN_PLOT_POINTS if input_kind == "raw-original" else 1
    records = {}  # type: Dict[int, Dict[str, Any]]
    for match in CHAPTER_BLOCK_RE.finditer(text):
        chapter = int(match.group(1))
        body = match.group(2).strip()
        if not re.search(r"(?m)^##\s+第%s章(?:\s+.*)?$" % chapter, body):
            raise RunError("chapter_schema_incomplete", "chapter %s heading missing" % chapter)
        fields = {name: compact_field(body, name) for name in COMPACT_FIELDS}  # type: Dict[str, Any]
        fields["情节点"] = parse_plot_points(body, chapter, minimum)
        records[chapter] = fields
    if input_kind == "raw-original" and set(records) != set(range(start, end + 1)):
        raise RunError("chapter_block_missing", "%s-%s" % (start, end))
    if records and set(records) != set(range(start, end + 1)):
        raise RunError("chapter_block_missing", "partial reuse projection is not allowed")
    if not records and input_kind == "existing-results":
        marker = re.search(r"<!--\s*REUSED_CHAPTERS:(\d+)-(\d+)\s*-->", text)
        if not marker or (int(marker.group(1)), int(marker.group(2))) != (start, end):
            raise RunError("reused_range_mismatch", "%s-%s" % (start, end))
    if text.count("<!-- BATCH_OBSERVATIONS_START -->") != 1 or text.count("<!-- BATCH_OBSERVATIONS_END -->") != 1:
        raise RunError("batch_marker_mismatch", "one complete cross-chapter observation block is required")
    observation_start = text.index("<!-- BATCH_OBSERVATIONS_START -->")
    observation_end = text.index("<!-- BATCH_OBSERVATIONS_END -->")
    last_source_marker = max((match.end() for match in CHAPTER_TOKEN_RE.finditer(text)), default=0)
    reused_marker = re.search(r"<!--\s*REUSED_CHAPTERS:\d+-\d+\s*-->", text)
    if reused_marker:
        last_source_marker = max(last_source_marker, reused_marker.end())
    if observation_start < last_source_marker or observation_end <= observation_start:
        raise RunError("batch_marker_order", "cross-chapter observations must follow source coverage")
    return records


def render_plot_point(point: Dict[str, Any]) -> str:
    point_type = map_enum(point["type"], POINT_TYPES, POINT_ALIASES, default="行动")
    theme = map_enum(point["tag"][0], THEMES, THEME_ALIASES)
    tone = map_enum(point["tag"][1], TONES, TONE_ALIASES)
    lines = ["P%s **%s**：%s" % (point["number"], point["title"], " | ".join(["类型" + point_type] + point["rest"]))]
    lines.extend(point["quote"])
    lines.extend(["", "主题标签%s | 基调：%s" % (theme, tone)])
    return "\n".join(lines)


def render_summary(chapter: int, fields: Dict[str, Any], source_kind: str,
                   chapter_hash: str, batch_id: str) -> bytes:
    text = (
        "<!-- story-long-analyze:projection runtime=single-state-v1 source=%s chapter_sha256=%s batch=%s -->\n"
        "## 第%s章\n\n**概要**：%s\n\n**关键事件**：\n1. %s\n\n"
        "**因果**：%s\n\n**局面结果**：%s\n\n**涉及**：%s\n\n"
        "**信息变化**：%s\n\n**状态变化**：%s\n\n**三维节奏**：%s\n\n"
        "**章尾钩子**：%s\n\n**证据**：%s\n\n**情节点**：\n\n%s\n"
    ) % (
        source_kind, chapter_hash, batch_id, chapter, fields["概要"], fields["关键行动"],
        fields["因果"], fields["局面结果"], fields["涉及人物"], fields["信息变化"],
        fields["状态变化"], fields["三维节奏"], fields["章尾钩子"], fields["证据"],
        "\n\n---\n\n".join(render_plot_point(point) for point in fields["情节点"]),
    )
    return text.encode("utf-8")


def render_cache(batch_id: str, start: int, end: int, input_kind: str,
                 range_hash: str, source_files: Sequence[str], model_output: str,
                 projection_schema: str = "compact-v3") -> bytes:
    text = (
        "%s\n# 批次 %s\n- batch_id: %s\n- chapters: %s-%s\n- input_kind: %s\n"
        "- range_sha256: %s\n- projection_schema: %s\n"
        "- source_files: %s\n%s\n%s\n%s\n%s\n"
    ) % (CACHE_START, batch_id, batch_id, start, end, input_kind, range_hash, projection_schema,
           json.dumps(list(source_files), ensure_ascii=False), MODEL_START,
           normalized(model_output).strip(), MODEL_END, CACHE_END)
    return text.encode("utf-8")


def parse_cache(path: Path) -> Dict[str, Any]:
    text = normalized(path.read_text(encoding="utf-8-sig"))
    if not text.rstrip().endswith(CACHE_END):
        raise RunError("cache_incomplete", str(path))
    metadata = {}  # type: Dict[str, Any]
    for key in ("batch_id", "chapters", "input_kind", "range_sha256", "projection_schema"):
        match = re.search(r"(?m)^- %s:\s*(.+)$" % key, text)
        if not match:
            raise RunError("cache_invalid", "missing %s" % key)
        metadata[key] = match.group(1).strip()
    try:
        start, end = [int(value) for value in metadata["chapters"].split("-", 1)]
    except ValueError:
        raise RunError("cache_invalid", "chapters: %s" % metadata["chapters"])
    model_match = re.search(re.escape(MODEL_START) + r"\n(.*?)\n" + re.escape(MODEL_END), text, re.DOTALL)
    if not model_match:
        raise RunError("cache_invalid", "model output markers missing")
    metadata.update({"start": start, "end": end, "model_output": model_match.group(1)})
    return metadata


def source_files_from_args(values: Optional[Sequence[str]]) -> List[str]:
    return list(values or [])


def commit_from_cache(root: Path, metadata: Dict[str, Any], cache: Path,
                      index_rows: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, Any]:
    batch_id = metadata["batch_id"]
    input_kind, id_start, id_end = parse_batch_id(batch_id)
    start, end = metadata["start"], metadata["end"]
    if (start, end, input_kind) != (id_start, id_end, metadata["input_kind"]):
        raise RunError("cache_invalid", "batch metadata mismatch")
    if input_kind == "raw-original":
        if index_rows is None:
            raise RunError("chapter_index_required", batch_id)
        current_hash = range_sha256(index_rows, start, end)
        if metadata["range_sha256"] != current_hash:
            raise RunError("range_hash_mismatch", batch_id)
    else:
        current_hash = metadata["range_sha256"]
    records = parse_model_output(metadata["model_output"], start, end, input_kind)
    hashes = {row["chapter"]: row["chapter_sha256"] for row in index_rows or []}
    created = []
    kept = []
    for chapter, fields in sorted(records.items()):
        path = summary_path(root, chapter)
        if path.exists():
            kept.append(chapter)
            continue
        chapter_hash = hashes.get(chapter, "0" * 64)
        atomic_write(path, render_summary(chapter, fields, input_kind, chapter_hash, batch_id))
        created.append(path.relative_to(root).as_posix())
        failure_after = os.environ.get("STORY_ANALYZE_FAIL_AFTER_SUMMARIES")
        if failure_after and len(created) >= int(failure_after):
            raise OSError("injected_failure_after_%s_summaries" % failure_after)
    missing = [chapter for chapter in range(start, end + 1) if not summary_path(root, chapter).is_file()]
    if missing:
        raise RunError("summary_projection_missing", ",".join(map(str, missing)))
    state, _ = load_state(root / "_progress.md")
    state["batches"][batch_id] = {
        "batch_id": batch_id, "start": start, "end": end, "input_kind": input_kind,
        "range_sha256": current_hash, "status": "completed", "parent": "",
        "cache": cache.relative_to(root).as_posix(),
    }
    changed = write_state(root / "_progress.md", state)
    return {"batch_id": batch_id, "created_summaries": created,
            "kept_existing_summary_chapters": kept, "progress_updated": changed}


def commit_command(args: argparse.Namespace) -> Dict[str, Any]:
    root = require_root(args.root)
    input_kind, start, end = parse_batch_id(args.batch_id)
    if end - start + 1 > MAX_CHAPTERS:
        raise RunError("batch_too_large", "%s exceeds %s chapters" % (args.batch_id, MAX_CHAPTERS))
    text = args.input.read_text(encoding="utf-8-sig")
    records = parse_model_output(text, start, end, input_kind)
    index_rows = read_index(root, args.index) if input_kind == "raw-original" or (args.index or root / "chapter_index.csv").is_file() else None
    if input_kind == "raw-original" and end > start:
        total_chars = sum(row["char_count"] for row in index_rows if start <= row["chapter"] <= end)
        if total_chars > MAX_CHARS:
            raise RunError("batch_too_large", "%s exceeds %s characters" % (args.batch_id, MAX_CHARS))
    current_hash = range_sha256(index_rows, start, end) if input_kind == "raw-original" else "existing-results"
    if input_kind == "raw-original" and not args.range_sha256:
        raise RunError("range_hash_required", "pass the value printed by plan")
    if args.range_sha256 and args.range_sha256 != current_hash:
        raise RunError("range_hash_mismatch", args.batch_id)
    # Parsing above validates the whole result before the first write.
    path = cache_path(root, args.batch_id)
    data = render_cache(args.batch_id, start, end, input_kind, current_hash,
                        source_files_from_args(args.source_file), text)
    if not path.is_file() or path.read_bytes() != data:
        if path.is_file():
            old_data = path.read_bytes()
            history = root / "_analysis_cache" / "legacy" / (
                "%s.%s.md" % (path.stem, sha256(old_data)[:12])
            )
            if not history.exists():
                atomic_write(history, old_data)
        atomic_write(path, data)
    if os.environ.get("STORY_ANALYZE_FAIL_AFTER_CACHE") == "1":
        raise OSError("injected_failure_after_cache")
    metadata = parse_cache(path)
    result = commit_from_cache(root, metadata, path, index_rows)
    result.update({"ok": True, "cache": path.relative_to(root).as_posix(), "validated_chapters": sorted(records)})
    return result


def repair_command(args: argparse.Namespace) -> Dict[str, Any]:
    root = require_root(args.root)
    index_rows = read_index(root, args.index) if (args.index or root / "chapter_index.csv").is_file() else None
    paths = [cache_path(root, args.batch_id)] if args.batch_id else sorted((root / "_analysis_cache").glob("批次-*.md"))
    state, _ = load_state(root / "_progress.md")
    repaired = []
    skipped = []
    errors = []
    for path in paths:
        # A cache replaced by a split or by other committed batches is history, not a repair target.
        batch_id = path.stem[len("批次-"):]
        if BATCH_ID_RE.fullmatch(batch_id):
            _, start, end = parse_batch_id(batch_id)
            covered = set()
            for other in state["batches"].values():
                if other["batch_id"] != batch_id and completed_batch(root, other, index_rows):
                    covered.update(range(other["start"], other["end"] + 1))
            if state["batches"].get(batch_id, {}).get("status") == "superseded" or set(range(start, end + 1)) <= covered:
                skipped.append({"cache": path.relative_to(root).as_posix(), "reason": "superseded"})
                continue
        try:
            metadata = parse_cache(path)
            repaired.append(commit_from_cache(root, metadata, path, index_rows))
        except (OSError, UnicodeError, RunError) as exc:
            errors.append({"cache": path.as_posix(), "error": getattr(exc, "code", str(exc)), "detail": str(exc)})
    return {"ok": not errors, "repaired": repaired, "skipped": skipped, "errors": errors}


def split_command(args: argparse.Namespace) -> Dict[str, Any]:
    root = require_root(args.root)
    input_kind, start, end = parse_batch_id(args.batch_id)
    if start >= end:
        raise RunError("batch_not_splittable", args.batch_id)
    index_rows = read_index(root, args.index) if input_kind == "raw-original" else None
    split_at = args.at
    if split_at is None:
        if index_rows:
            counts = {row["chapter"]: row["char_count"] for row in index_rows}
            total = sum(counts[chapter] for chapter in range(start, end + 1))
            running = 0
            split_at = start
            for chapter in range(start, end):
                running += counts[chapter]
                split_at = chapter
                if running >= total / 2:
                    break
        else:
            split_at = (start + end) // 2
    if split_at < start or split_at >= end:
        raise RunError("invalid_split_point", str(split_at))
    state, _ = load_state(root / "_progress.md")
    parent_hash = range_sha256(index_rows, start, end) if index_rows else "existing-results"
    state["batches"][args.batch_id] = {
        "batch_id": args.batch_id, "start": start, "end": end, "input_kind": input_kind,
        "range_sha256": parent_hash, "status": "superseded", "parent": "", "cache": "",
    }
    prefix = "RAW" if input_kind == "raw-original" else "REUSE"
    children = []
    for child_start, child_end in ((start, split_at), (split_at + 1, end)):
        child_id = "%s-%s-%s" % (prefix, child_start, child_end)
        child_hash = range_sha256(index_rows, child_start, child_end) if index_rows else "existing-results"
        existing = state["batches"].get(child_id)
        if not existing or existing.get("status") not in {"completed", "success"}:
            state["batches"][child_id] = {
                "batch_id": child_id, "start": child_start, "end": child_end,
                "input_kind": input_kind, "range_sha256": child_hash, "status": "planned",
                "parent": args.batch_id, "cache": "",
            }
        children.append(child_id)
    write_state(root / "_progress.md", state)
    return {"ok": True, "parent": args.batch_id, "status": "superseded", "children": children}


def stage_required_outputs(root: Path, stage: str) -> List[str]:
    if stage == "stage1":
        expected = inspect(root, None).get("expected_chapters") or 3
        required = ["章节/第%s章_深度拆解.md" % chapter for chapter in range(1, min(3, int(expected)) + 1)]
        required.append("快速预览.md")
        return required
    if stage == "stage2":
        expected = inspect(root, None).get("expected_chapters")
        if not expected:
            raise RunError("expected_chapters_unknown", "Stage 2 completion requires a known chapter count")
        return ["章节/第%s章_摘要.md" % chapter for chapter in range(1, int(expected) + 1)]
    if stage == "stage3":
        return ["剧情/情绪模块.md", "剧情/节奏.md"]
    if stage == "stage4":
        character_files = sorted(path for path in (root / "角色").glob("*.md") if path.is_file() and path.stat().st_size)
        setting_files = sorted(path for path in (root / "设定").rglob("*.md") if path.is_file() and path.stat().st_size)
        missing = []
        if not character_files:
            missing.append("角色/*.md")
        if not setting_files:
            missing.append("设定/**/*.md")
        if missing:
            raise RunError("stage_output_missing", ",".join(missing))
        return [character_files[0].relative_to(root).as_posix(), setting_files[0].relative_to(root).as_posix()]
    if stage == "stage5":
        return ["拆文报告.md"]
    if stage == "stage6":
        return ["文风.md"]
    raise RunError("stage_unknown", stage)


def mark_stage_command(args: argparse.Namespace) -> Dict[str, Any]:
    root = require_root(args.root)
    if args.prepare:
        if args.stage != "stage5":
            raise RunError("prepare_stage_unsupported", args.stage)
        report = root / "拆文报告.md"
        backup = root / "_analysis_cache" / "legacy" / "拆文报告.md"
        created = False
        selected_backup = backup
        if report.is_file():
            report_data = report.read_bytes()
            if backup.exists() and backup.read_bytes() != report_data:
                selected_backup = backup.with_name("拆文报告.%s.md" % sha256(report_data)[:12])
            if not selected_backup.exists():
                atomic_write(selected_backup, report_data)
                created = True
        return {"ok": True, "stage": args.stage, "prepared": True,
                "legacy_report_backup": selected_backup.relative_to(root).as_posix() if selected_backup.is_file() else None,
                "backup_created": created, "progress_updated": False}
    required_outputs = stage_required_outputs(root, args.stage) if args.status == "completed" else []
    missing_required = [
        name for name in required_outputs
        if not (root / name).is_file() or (root / name).stat().st_size == 0
    ]
    if missing_required:
        raise RunError("stage_output_missing", ",".join(missing_required))
    output = args.output
    relative_output = ""
    if output:
        path = output if output.is_absolute() else root / output
        if args.status == "completed" and (not path.is_file() or path.stat().st_size == 0):
            raise RunError("stage_output_missing", str(path))
        try:
            relative_output = path.resolve().relative_to(root).as_posix()
        except ValueError:
            raise RunError("stage_output_outside_root", str(path))
    elif required_outputs:
        relative_output = ";".join(required_outputs)
    state, _ = load_state(root / "_progress.md")
    state["stages"][args.stage] = {"status": args.status, "output": relative_output}
    changed = write_state(root / "_progress.md", state)
    return {"ok": True, "stage": args.stage, "status": args.status, "progress_updated": changed}


OBS_START = "<!-- BATCH_OBSERVATIONS_START -->"
OBS_END = "<!-- BATCH_OBSERVATIONS_END -->"
# Labels as projected by render_summary (legacy summaries use the same labels).
SUMMARY_FIELDS = ("概要", "关键事件", "因果", "局面结果", "涉及", "信息变化", "状态变化",
                  "三维节奏", "章尾钩子", "证据")


def parse_chapter_window(value: Optional[str]) -> Optional[Tuple[int, int]]:
    if not value:
        return None
    match = re.fullmatch(r"(\d+)(?:-(\d+))?", value.strip())
    if not match:
        raise RunError("invalid_chapter_window", value)
    start = int(match.group(1))
    end = int(match.group(2) or start)
    if start < 1 or end < start:
        raise RunError("invalid_chapter_window", value)
    return start, end


def digest_caches(root: Path) -> List[Tuple[int, int, str, Path]]:
    """Complete caches of committed batches, falling back to every complete cache on disk."""
    state, _ = load_state(root / "_progress.md")
    chosen = {}  # type: Dict[str, Tuple[int, int, str, Path]]
    for row in state["batches"].values():
        if row.get("status") not in {"completed", "success"}:
            continue
        path = root / row["cache"] if row.get("cache") else cache_path(root, row["batch_id"])
        if cache_complete(path):
            chosen[row["batch_id"]] = (row["start"], row["end"], row["batch_id"], path)
    if not chosen:
        for path in sorted((root / "_analysis_cache").glob("批次-*.md")):
            try:
                _, start, end = parse_batch_id(path.stem[len("批次-"):])
            except RunError:
                continue
            if cache_complete(path):
                chosen[path.stem] = (start, end, path.stem[len("批次-"):], path)
    return sorted(chosen.values())


def summary_field(text: str, name: str) -> str:
    if name == "关键事件":
        match = re.search(r"(?ms)^\*\*关键事件\*\*\s*[：:]\s*\n(.*?)(?=^\*\*|\Z)", text)
        return " ".join(line.strip() for line in match.group(1).splitlines() if line.strip()) if match else ""
    match = re.search(r"(?m)^\*\*%s\*\*\s*[：:]\s*(\S.*)$" % re.escape(name), text)
    return match.group(1).strip() if match else ""


def summary_points(text: str, mode: str) -> List[str]:
    lines = text.split("\n")
    points = []  # type: List[str]
    for index, line in enumerate(lines):
        header = POINT_HEADER_RE.match(line.strip())
        if not header:
            continue
        segments = [item.strip() for item in re.split(r"[|｜]", header.group(3))]
        tone = ""
        for follow in lines[index + 1:index + 8]:
            tag = POINT_TAG_RE.match(follow.strip())
            if tag:
                tone = tag.group(2)
                break
            if POINT_HEADER_RE.match(follow.strip()):
                break
        point_type = segments[0][2:].lstrip(" ：:") if segments[0].startswith("类型") else segments[0]
        if mode == "brief":
            points.append("P%s %s｜%s｜%s" % (header.group(1), header.group(2).strip(), point_type, tone or "—"))
        else:
            points.append("%s ｜基调：%s" % (line.strip(), tone or "—"))
    return points


def digest_command(args: argparse.Namespace) -> Dict[str, Any]:
    root = require_root(args.root)
    window = parse_chapter_window(args.chapters)
    parts = []  # type: List[str]
    if args.part == "observations":
        for start, end, batch_id, path in digest_caches(root):
            if window and (end < window[0] or start > window[1]):
                continue
            model = parse_cache(path)["model_output"]
            if OBS_START not in model or OBS_END not in model:
                continue
            body = model.split(OBS_START, 1)[1].split(OBS_END, 1)[0].strip()
            body = re.sub(r"(?m)^##\s*跨章观察\s*\n", "", body).strip()
            parts.append("## %s（第%s-%s章）\n\n%s" % (batch_id, start, end, body))
    else:
        fields = [item.strip() for item in (args.fields or "").split(",") if item.strip()]
        unknown = [item for item in fields if item not in SUMMARY_FIELDS]
        if unknown:
            raise RunError("unknown_summary_field", ",".join(unknown))
        if not fields and args.points == "none":
            raise RunError("digest_empty_request", "pass --fields and/or --points")
        chapters = sorted(
            int(match.group(1)) for match in
            (re.fullmatch(r"第(\d+)章_摘要", path.stem) for path in (root / "章节").glob("第*章_摘要.md"))
            if match
        )
        for chapter in chapters:
            if window and not window[0] <= chapter <= window[1]:
                continue
            text = normalized(summary_path(root, chapter).read_text(encoding="utf-8-sig"))
            lines = ["### 第%s章" % chapter]
            lines.extend("- %s：%s" % (name, summary_field(text, name) or "未提供") for name in fields)
            if args.points != "none":
                lines.extend(summary_points(text, args.points))
            parts.append("\n".join(lines))
    if not parts:
        raise RunError("digest_nothing_found", "no committed batch caches or summaries in range")
    return {"ok": True, "text": "\n\n".join(parts) + "\n"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="print a read-only in-memory plan")
    plan.add_argument("--root", required=True, type=Path)
    plan.add_argument("--index", type=Path)
    plan.add_argument("--expected-chapters", type=int)
    plan.add_argument("--intent", choices=("continue", "enhance"), default="continue")
    plan.add_argument("--next", type=int, metavar="N",
                      help="only print the first N batches (0 = counts only); remaining_batches stays total")
    plan.set_defaults(handler=plan_command)
    commit = sub.add_parser("commit", help="validate and atomically commit one batch")
    commit.add_argument("--root", required=True, type=Path)
    commit.add_argument("--input", required=True, type=Path)
    commit.add_argument("--batch-id", required=True)
    commit.add_argument("--range-sha256")
    commit.add_argument("--index", type=Path)
    commit.add_argument("--source-file", action="append")
    commit.set_defaults(handler=commit_command)
    split = sub.add_parser("split", help="persist a failed batch split")
    split.add_argument("--root", required=True, type=Path)
    split.add_argument("--batch-id", required=True)
    split.add_argument("--at", type=int)
    split.add_argument("--index", type=Path)
    split.set_defaults(handler=split_command)
    repair = sub.add_parser("repair-progress", help="recover missing projections/state from complete caches")
    repair.add_argument("--root", required=True, type=Path)
    repair.add_argument("--batch-id")
    repair.add_argument("--index", type=Path)
    repair.set_defaults(handler=repair_command)
    stage = sub.add_parser("mark-stage", help="mark a stage after its output is present")
    stage.add_argument("--root", required=True, type=Path)
    stage.add_argument("--stage", required=True, choices=("stage1", "stage2", "stage3", "stage4", "stage5", "stage6"))
    stage.add_argument("--status", choices=("completed", "completed_with_errors"), default="completed")
    stage.add_argument("--output", type=Path)
    stage.add_argument("--prepare", action="store_true", help="before Stage 5, preserve the existing report")
    stage.set_defaults(handler=mark_stage_command)
    digest = sub.add_parser("digest", help="print Stage 3-5 reading material without whole-cache reads")
    digest.add_argument("--root", required=True, type=Path)
    digest.add_argument("--part", required=True, choices=("observations", "chapters"))
    digest.add_argument("--chapters", help="chapter window such as 1-40")
    digest.add_argument("--fields", help="comma-separated summary fields, e.g. 三维节奏,涉及,状态变化")
    digest.add_argument("--points", choices=("none", "brief", "full"), default="none")
    digest.set_defaults(handler=digest_command)
    return parser


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args()
    try:
        payload = args.handler(args)
        if args.command == "digest":
            sys.stdout.write(payload["text"])
            return 0
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if payload.get("ok", True) else 2
    except (OSError, UnicodeError, RunError) as exc:
        payload = {"ok": False, "error": getattr(exc, "code", "io_error"), "detail": str(exc)}
        if getattr(exc, "author_message", None):
            payload["author_message"] = exc.author_message
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
