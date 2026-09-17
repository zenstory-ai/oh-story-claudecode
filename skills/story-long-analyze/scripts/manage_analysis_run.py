#!/usr/bin/env python3
"""Plan, commit, split, recover, and migrate long-analysis batches.

Runtime state lives only in the managed block of ``_progress.md``. Plans are
printed as JSON and are never persisted. Batch caches are complete recovery
evidence, not a second state database.
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
import uuid
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
PROJECTION_RE = re.compile(
    r"<!--\s*story-long-analyze:projection\s+runtime=single-state-v1\s+source=([^\s]+)\s+"
    r"chapter_sha256=([0-9a-f]{64})\s+batch=([^\s]+)\s*-->"
)
COMPACT_FIELDS = (
    "概要", "因果", "关键行动", "局面结果", "涉及人物", "信息变化", "状态变化",
    "三维节奏", "章尾钩子", "证据", "情节点类型", "情节点标题", "主题标签", "基调",
)
THEMES = ("爱情", "亲情", "友情", "权力", "金钱", "成长", "复仇", "悬念", "搞笑", "热血", "日常", "其他")
TONES = ("紧张", "轻松", "悲伤", "热血", "爽", "甜", "温馨", "恐怖", "压抑", "其他")
POINT_TYPES = ("转折点", "信息揭示", "冲突", "解决", "铺垫", "行动", "对话", "状态变化")
MAX_CHAPTERS = 10
MAX_CHARS = 25_000


class RunError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


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
    return {"request": {}, "batches": {}, "stages": {}}


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
        if line.strip() == "## 本次请求":
            section = "request"
            continue
        if line.strip() == "### 批次状态":
            section = "batches"
            continue
        if section == "request" and line.startswith("- ") and "：" in line:
            key, value = [item.strip() for item in line[2:].split("：", 1)]
            state["request"][key] = value
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
                "request_id": "" if len(cells) < 8 or cells[7] == "-" else cells[7],
            }
        elif section == "stages" and cells and cells[0] not in {"阶段", "---"} and len(cells) >= 3:
            state["stages"][cells[0]] = {"status": cells[1], "output": "" if cells[2] == "-" else cells[2]}
    return state, raw


def render_state(state: Dict[str, Any], newline: str) -> str:
    request = state.get("request", {})
    lines = [STATE_START, "## 长篇拆文运行状态", "", "## 本次请求",
             "- 意图：%s" % request.get("意图", "-") ,
             "- 请求ID：%s" % request.get("请求ID", "-"),
             "- 请求范围：%s" % request.get("请求范围", "-"),
             "- 本次状态：%s" % request.get("本次状态", "-"),
             "", "### 批次状态",
             "| 批次ID | 章节范围 | 输入 | 原文范围hash | 状态 | 父批次 | 缓存 | 请求ID |",
             "|---|---|---|---|---|---|---|---|"]
    batches = list(state["batches"].values())
    batches.sort(key=lambda row: (row["start"], row["end"], row["batch_id"]))
    for row in batches:
        lines.append("| %s | %s-%s | %s | %s | %s | %s | %s | %s |" % (
            row["batch_id"], row["start"], row["end"], row["input_kind"],
            row["range_sha256"], row["status"], row.get("parent") or "-", row.get("cache") or "-",
            row.get("request_id") or "-"))
    lines.extend(["", "### 阶段状态", "| 阶段 | 状态 | 产物 |", "|---|---|---|"])
    for stage in sorted(state["stages"]):
        row = state["stages"][stage]
        lines.append("| %s | %s | %s |" % (stage, row["status"], row.get("output") or "-"))
    lines.append(STATE_END)
    return newline.join(lines)


def write_state(progress: Path, state: Dict[str, Any]) -> bool:
    raw = progress.read_bytes() if progress.is_file() else b""
    text, bom, newline = decode_progress(raw)
    block = render_state(state, newline)
    pattern = re.compile(re.escape(STATE_START) + r".*?" + re.escape(STATE_END), re.DOTALL)
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
    if row.get("request_id") and metadata.get("request_id", "") != row.get("request_id"):
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


def stale_projection_chapters(root: Path, rows: Sequence[Dict[str, Any]], state: Dict[str, Any]) -> Set[int]:
    hashes = {row["chapter"]: row["chapter_sha256"] for row in rows}
    stale = set()
    for chapter, current_hash in hashes.items():
        path = summary_path(root, chapter)
        if not path.is_file():
            continue
        try:
            marker = PROJECTION_RE.search(path.read_text(encoding="utf-8-sig")[:1200])
        except (OSError, UnicodeError):
            continue
        if marker and marker.group(2) != current_hash:
            covered_by_current_commit = any(
                row.get("input_kind") == "raw-original"
                and row["start"] <= chapter <= row["end"]
                and completed_batch(root, row, rows)
                for row in state["batches"].values()
            )
            if not covered_by_current_commit:
                stale.add(chapter)
    return stale


def source_change_chapters(root: Path, rows: Sequence[Dict[str, Any]], state: Dict[str, Any]) -> Set[int]:
    """Return localized rebuild changes not yet covered by a current RAW batch."""
    previous_path = root / "_analysis_cache" / "chapter_index.previous.csv"
    if not previous_path.is_file():
        return set()
    try:
        previous = read_index(root, previous_path)
    except RunError:
        return set()
    previous_by_chapter = {row["chapter"]: row for row in previous}
    changed = {
        row["chapter"] for row in rows
        if row["chapter"] not in previous_by_chapter
        or previous_by_chapter[row["chapter"]].get("chapter_sha256") != row.get("chapter_sha256")
    }
    covered = set()
    for batch in state["batches"].values():
        if batch.get("input_kind") != "raw-original" or not completed_batch(root, batch, rows):
            continue
        covered.update(range(batch["start"], batch["end"] + 1))
    return changed - covered


def invalid_batch_targets(root: Path, rows: Optional[Sequence[Dict[str, Any]]],
                          state: Dict[str, Any]) -> Tuple[Set[int], Set[int]]:
    raw = set()
    reuse = set()
    historical_indexes = None  # type: Optional[List[List[Dict[str, Any]]]]
    for batch in state["batches"].values():
        if batch.get("status") not in {"completed", "success"} or completed_batch(root, batch, rows):
            continue
        chapters = set(range(batch["start"], batch["end"] + 1))
        if batch.get("input_kind") == "raw-original":
            targets = chapters
            if rows is not None:
                if historical_indexes is None:
                    historical_indexes = []
                    cache_dir = root / "_analysis_cache"
                    paths = [cache_dir / "chapter_index.previous.csv"]
                    paths.extend(sorted((cache_dir / "legacy").glob("chapter_index.*.csv")))
                    for path in paths:
                        try:
                            historical_indexes.append(read_index(root, path))
                        except RunError:
                            continue
                current_hashes = {row["chapter"]: row["chapter_sha256"] for row in rows}
                for previous in historical_indexes:
                    try:
                        if not completed_batch(root, batch, previous):
                            continue
                    except RunError:
                        continue
                    # A complete old cache still proves its unchanged chapters.
                    # Use the full change boundary, not only changes awaiting
                    # repair: an empty remainder must never invalidate the parent.
                    targets = {
                        row["chapter"] for row in previous
                        if row["chapter"] in chapters
                        and row["chapter_sha256"] != current_hashes.get(row["chapter"])
                    }
                    break
            raw.update(targets)
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
    request_id = args.request_id
    if args.intent == "reanalyze" and not request_id:
        request_id = "reanalyze-" + uuid.uuid4().hex[:16]
    recoverable_caches, cache_covered = add_recoverable_caches(root, state, index_rows)
    expected = report.get("expected_chapters") or (len(index_rows) if index_rows else None)
    if not expected:
        raise RunError("expected_chapters_unknown", "build the chapter index or pass --expected-chapters")
    semantic = set(report["completed_semantic_chapters"])
    summaries = set(report["completed_summary_chapters"])
    all_chapters = set(range(1, int(expected) + 1))
    source_changes = source_change_chapters(root, index_rows, state) if index_rows else set()
    stale = stale_projection_chapters(root, index_rows, state) if index_rows else set()
    stale |= source_changes
    invalid_raw, invalid_reuse = invalid_batch_targets(root, index_rows, state)

    raw_targets = set()  # type: Set[int]
    reuse_targets = set()  # type: Set[int]
    if args.intent == "reanalyze":
        raw_targets = all_chapters
    elif args.intent == "enhance":
        raw_targets = (all_chapters - semantic) | stale | invalid_raw
        reuse_targets = (semantic - raw_targets) | invalid_reuse
    else:
        raw_targets = (all_chapters - semantic) | stale | invalid_raw
        reuse_targets = ((semantic - summaries) | invalid_reuse) - raw_targets
    if args.intent != "reanalyze":
        raw_targets -= cache_covered
        reuse_targets -= cache_covered
    else:
        recoverable_caches = []
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
        and (args.intent != "reanalyze" or row.get("request_id") == request_id)
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
        same_request = args.intent != "reanalyze" or prior and prior.get("request_id") == request_id
        if prior and same_request and completed_batch(root, prior, index_rows):
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
        })
    required_stages = list(report.get("stage_repairs", []))
    if args.intent == "reanalyze":
        required_stages = ["stage1", "stage2", "stage3", "stage4", "stage5", "stage6"]
    elif source_changes:
        required_stages = sorted(set(required_stages + ["stage2", "stage3", "stage4", "stage5", "stage6"]))
    elif batches or recoverable_caches:
        required_stages = sorted(set(required_stages + ["stage2"]))
    return {
        "ok": True, "root": str(root), "intent": args.intent, "request_id": request_id,
        "classification": report["classification"], "recommended_path": report["recommended_path"],
        "mixed_sources": report["mixed_sources"], "batches": batches,
        "recoverable_caches": recoverable_caches,
        "summary_gaps": sorted(all_chapters - summaries), "stale_projection_chapters": sorted(stale),
        "source_changed_chapters": sorted(source_changes),
        "read_counts": {"raw_chapters": raw_reads, "existing_result_files": result_reads},
        "required_stages": required_stages,
        "state_written": False,
    }


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


def parse_model_output(text: str, start: int, end: int, input_kind: str) -> Dict[int, Dict[str, str]]:
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
    records = {}  # type: Dict[int, Dict[str, str]]
    for match in CHAPTER_BLOCK_RE.finditer(text):
        chapter = int(match.group(1))
        body = match.group(2).strip()
        if not re.search(r"(?m)^##\s+第%s章(?:\s+.*)?$" % chapter, body):
            raise RunError("chapter_schema_incomplete", "chapter %s heading missing" % chapter)
        records[chapter] = {name: compact_field(body, name) for name in COMPACT_FIELDS}
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


def map_enum(value: str, allowed: Sequence[str], aliases: Dict[str, str]) -> str:
    for item in allowed:
        if item != "其他" and item in value:
            return item
    for needle, target in aliases.items():
        if needle in value:
            return target
    return "其他" if "其他" in allowed else allowed[-1]


def render_summary(chapter: int, fields: Dict[str, str], source_kind: str,
                   chapter_hash: str, batch_id: str) -> bytes:
    theme = map_enum(fields["主题标签"], THEMES, {"恋": "爱情", "权谋": "权力", "政治": "权力", "幽默": "搞笑"})
    tone = map_enum(fields["基调"], TONES, {"悲痛": "悲伤", "伤感": "悲伤", "痛快": "爽", "惊悚": "恐怖"})
    point_type = map_enum(fields["情节点类型"], POINT_TYPES, {
        "揭示": "信息揭示", "转折": "转折点", "变化": "状态变化",
        "动作": "行动", "交谈": "对话", "化解": "解决", "": "行动",
    })
    text = (
        "<!-- story-long-analyze:projection runtime=single-state-v1 source=%s chapter_sha256=%s batch=%s -->\n"
        "## 第%s章\n\n**概要**：%s\n\n**关键事件**：\n1. %s\n\n"
        "**因果**：%s\n\n**局面结果**：%s\n\n**涉及**：%s\n\n"
        "**信息变化**：%s\n\n**状态变化**：%s\n\n**三维节奏**：%s\n\n"
        "**章尾钩子**：%s\n\n**证据**：%s\n\n**情节点**：\n\n"
        "P1 **%s**：类型%s | %s | 涉及%s | 证据%s\n主题标签%s | 基调：%s\n"
    ) % (
        source_kind, chapter_hash, batch_id, chapter, fields["概要"], fields["关键行动"],
        fields["因果"], fields["局面结果"], fields["涉及人物"], fields["信息变化"],
        fields["状态变化"], fields["三维节奏"], fields["章尾钩子"], fields["证据"],
        fields["情节点标题"], point_type, fields["局面结果"], fields["涉及人物"], fields["证据"],
        theme, tone,
    )
    return text.encode("utf-8")


def render_cache(batch_id: str, start: int, end: int, input_kind: str,
                 range_hash: str, source_files: Sequence[str], model_output: str,
                 projection_schema: str = "compact-v2", request_id: str = "",
                 request_intent: str = "continue") -> bytes:
    text = (
        "%s\n# 批次 %s\n- batch_id: %s\n- chapters: %s-%s\n- input_kind: %s\n"
        "- range_sha256: %s\n- projection_schema: %s\n- request_id: %s\n- request_intent: %s\n"
        "- source_files: %s\n%s\n%s\n%s\n%s\n"
    ) % (CACHE_START, batch_id, batch_id, start, end, input_kind, range_hash,
           projection_schema, request_id or "-", request_intent,
           json.dumps(list(source_files), ensure_ascii=False), MODEL_START,
           normalized(model_output).strip(), MODEL_END, CACHE_END)
    return text.encode("utf-8")


def parse_cache(path: Path) -> Dict[str, Any]:
    text = normalized(path.read_text(encoding="utf-8-sig"))
    if not text.rstrip().endswith(CACHE_END):
        raise RunError("cache_incomplete", str(path))
    metadata = {}
    for key in ("batch_id", "chapters", "input_kind", "range_sha256", "projection_schema"):
        match = re.search(r"(?m)^- %s:\s*(.+)$" % key, text)
        if not match:
            raise RunError("cache_invalid", "missing %s" % key)
        metadata[key] = match.group(1).strip()
    for key in ("request_id", "request_intent"):
        match = re.search(r"(?m)^- %s:\s*(.+)$" % key, text)
        metadata[key] = "" if not match or match.group(1).strip() == "-" else match.group(1).strip()
    start, end = [int(value) for value in metadata["chapters"].split("-", 1)]
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
    for chapter, fields in sorted(records.items()):
        path = summary_path(root, chapter)
        if path.exists():
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
    source_changes = source_change_chapters(root, index_rows, state) if input_kind == "raw-original" and index_rows else set()
    state["batches"][batch_id] = {
        "batch_id": batch_id, "start": start, "end": end, "input_kind": input_kind,
        "range_sha256": current_hash, "status": "completed", "parent": "",
        "cache": cache.relative_to(root).as_posix(),
        "request_id": metadata.get("request_id", ""),
    }
    request_id = metadata.get("request_id", "")
    request_intent = metadata.get("request_intent", "continue") or "continue"
    if request_id:
        state["request"] = {
            "意图": request_intent,
            "请求ID": request_id,
            "请求范围": "第%s-%s章" % (start, end),
            "本次状态": "pending",
        }
    if input_kind == "raw-original" and source_changes & set(range(start, end + 1)):
        for stage in ("stage3", "stage4", "stage5", "stage6"):
            state["stages"][stage] = {"status": "pending", "output": "source_changed"}
    changed = write_state(root / "_progress.md", state)
    return {"batch_id": batch_id, "created_summaries": created, "progress_updated": changed}


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
    if args.intent == "reanalyze" and not args.request_id:
        raise RunError("request_id_required", "reanalyze commit must use the request_id printed by plan")
    current_hash = range_sha256(index_rows, start, end) if input_kind == "raw-original" else "existing-results"
    if input_kind == "raw-original" and not args.range_sha256:
        raise RunError("range_hash_required", "pass the value printed by plan")
    if args.range_sha256 and args.range_sha256 != current_hash:
        raise RunError("range_hash_mismatch", args.batch_id)
    # Parsing above validates the whole result before the first write.
    path = cache_path(root, args.batch_id)
    data = render_cache(args.batch_id, start, end, input_kind, current_hash,
                        source_files_from_args(args.source_file), text,
                        request_id=args.request_id or "", request_intent=args.intent)
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
    repaired = []
    skipped = []
    errors = []
    for path in paths:
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
        "request_id": args.request_id or "",
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
                "parent": args.batch_id, "cache": "", "request_id": args.request_id or "",
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


def migrate_command(args: argparse.Namespace) -> Dict[str, Any]:
    root = require_root(args.root)
    index_rows = None
    index_warning = None
    if (args.index or root / "chapter_index.csv").is_file():
        try:
            index_rows = read_index(root, args.index)
        except RunError as exc:
            # A six-script index predates chapter_sha256. Receipt/output hashes
            # can still prove historical completeness; a later rebuild will
            # establish current range hashes.
            index_warning = {"error": exc.code, "detail": exc.detail}
    receipts_dir = root / "_analysis_cache" / "receipts"
    migrated = []
    unverified = []
    verified_old_paths = set()
    state, _ = load_state(root / "_progress.md")
    for receipt_path in sorted(receipts_dir.glob("*.json")) if receipts_dir.is_dir() else []:
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
            start, end = [int(value) for value in receipt["chapter_range"]]
            old_outputs = receipt.get("outputs", {})
            candidates = [root / name for name in old_outputs if name.startswith("_analysis_cache/") and name.endswith(".md")]
            old_cache = next((path for path in candidates if path.is_file() and sha256(path.read_bytes()) == old_outputs[path.relative_to(root).as_posix()]), None)
            if receipt.get("status") != "success" or old_cache is None:
                raise ValueError("receipt_or_cache_not_verified")
            verified_old_paths.add(old_cache.resolve())
            input_kind = receipt.get("input_kind", "raw-original")
            prefix = "RAW" if input_kind == "raw-original" else "REUSE"
            batch_id = "%s-%s-%s" % (prefix, start, end)
            if input_kind == "raw-original" and index_rows:
                source_hashes = {str(row.get("source_sha256", "")) for row in index_rows}
                receipt_source = str(receipt.get("source_sha256", ""))
                if len(source_hashes) == 1 and receipt_source not in source_hashes:
                    raise ValueError("receipt_source_hash_mismatch")
                current_hash = range_sha256(index_rows, start, end)
            else:
                current_hash = "historical-verified-by-receipt"
            migrated_kind = "migrated-legacy"
            compat = root / "_analysis_cache" / ("迁移-%s.md" % batch_id)
            data = render_cache(batch_id, start, end, migrated_kind, current_hash,
                                [old_cache.relative_to(root).as_posix(), receipt_path.relative_to(root).as_posix()],
                                old_cache.read_text(encoding="utf-8-sig"), "legacy-compatible")
            if not compat.exists():
                atomic_write(compat, data)
            if all(summary_path(root, chapter).is_file() for chapter in range(start, end + 1)):
                state["batches"][batch_id] = {
                    "batch_id": batch_id, "start": start, "end": end, "input_kind": migrated_kind,
                    "range_sha256": current_hash, "status": "completed", "parent": "",
                    "cache": compat.relative_to(root).as_posix(),
                }
            migrated.append({"batch_id": batch_id, "cache": compat.relative_to(root).as_posix()})
        except (OSError, UnicodeError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            unverified.append({"receipt": receipt_path.relative_to(root).as_posix(), "reason": str(exc)})
    cache_dir = root / "_analysis_cache"
    historical_candidates = []
    if cache_dir.is_dir():
        historical_candidates.extend(cache_dir.glob("批次-*.md"))
        historical_candidates.extend(cache_dir.glob("复用提取-*.md"))
    for old_cache in sorted(set(historical_candidates)):
        if old_cache.resolve() in verified_old_paths or re.fullmatch(r"批次-(?:RAW|REUSE)-\d+-\d+", old_cache.stem):
            continue
        unverified.append({"cache": old_cache.relative_to(root).as_posix(),
                           "reason": "no_verified_receipt; kept as historical evidence"})
    if migrated:
        write_state(root / "_progress.md", state)
    return {"ok": True, "migrated": migrated, "historical_unverified": unverified,
            "index_warning": index_warning,
            "legacy_files_deleted": False}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="print a read-only in-memory plan")
    plan.add_argument("--root", required=True, type=Path)
    plan.add_argument("--index", type=Path)
    plan.add_argument("--expected-chapters", type=int)
    plan.add_argument("--intent", choices=("continue", "enhance", "reanalyze"), default="continue")
    plan.add_argument("--request-id", help="stable ID for resuming one explicit reanalysis request")
    plan.set_defaults(handler=plan_command)
    commit = sub.add_parser("commit", help="validate and atomically commit one batch")
    commit.add_argument("--root", required=True, type=Path)
    commit.add_argument("--input", required=True, type=Path)
    commit.add_argument("--batch-id", required=True)
    commit.add_argument("--range-sha256")
    commit.add_argument("--index", type=Path)
    commit.add_argument("--source-file", action="append")
    commit.add_argument("--intent", choices=("continue", "enhance", "reanalyze"), default="continue")
    commit.add_argument("--request-id", help="request_id printed by plan; required for reanalyze")
    commit.set_defaults(handler=commit_command)
    split = sub.add_parser("split", help="persist a failed batch split")
    split.add_argument("--root", required=True, type=Path)
    split.add_argument("--batch-id", required=True)
    split.add_argument("--at", type=int)
    split.add_argument("--index", type=Path)
    split.add_argument("--request-id")
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
    migrate = sub.add_parser("migrate-legacy", help="migrate verified six-script recovery evidence")
    migrate.add_argument("--root", required=True, type=Path)
    migrate.add_argument("--index", type=Path)
    migrate.set_defaults(handler=migrate_command)
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args()
    try:
        payload = args.handler(args)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if payload.get("ok", True) else 2
    except (OSError, UnicodeError, RunError) as exc:
        print(json.dumps({"ok": False, "error": getattr(exc, "code", "io_error"),
                          "detail": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
