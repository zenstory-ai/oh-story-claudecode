#!/usr/bin/env python3
"""Inspect reusable long-analysis assets without changing user files.

Only the upstream directory contract is recognized: ``章节/第N章_摘要.md``,
golden-three-chapter analyses, and the aggregate files. Missing chapters are
reported exactly so a run only fills gaps.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Iterable


SUMMARY_RE = re.compile(r"^第0*(\d+)章_摘要\.md$")
GOLDEN_RE = re.compile(r"^第0*(\d+)章_深度拆解\.md$")
SCHEMA_RE = re.compile(r"schema_version\s*[：:]\s*v?(\d+)", re.IGNORECASE)
TOTAL_RE = re.compile(r"总章数\s*(?:[：:]|\|)\s*(\d+)")
TOTAL_FALLBACK_RE = re.compile(r"总章数\s+(\d+)\s*章?")
TABLE_CHAPTER_TOTAL_RE = re.compile(r"\|\s*章节数\s*\|\s*(\d+)\s*(?:章)?\s*\|")
COVERAGE_TOTAL_RE = re.compile(
    r"(?:输入覆盖\s*[：:]\s*全文|精读覆盖\s*[：:]\s*第\s*1\s*[—–-]\s*)(\d+)\s*章"
)
FINAL_RE = re.compile(r"(?:最终状态|当前状态)\s*[：:]\s*([a-z0-9_]+)", re.IGNORECASE)
SOURCE_HASH_RE = re.compile(
    r"(?:输入版本|SHA-256|source_sha256)\s*(?:[：:]|\|)\s*([0-9a-f]{64})", re.IGNORECASE
)
PROJECTION_RE = re.compile(
    r"<!--\s*story-long-analyze:projection\s+runtime=(?P<runtime>[^\s]+)\s+"
    r"source=(?P<source>[^\s]+)(?:\s+[^>]*?)?\s*-->"
)
STATE_START = "<!-- story-long-analyze:runtime-state:start -->"
STATE_END = "<!-- story-long-analyze:runtime-state:end -->"
# v0.7.x wrote a 「章节边界」 table (章号 | 标题 | 起始行 | 字数) into _progress.md.
BOUNDARY_HEADING_RE = re.compile(r"^#{1,6}\s*章节边界")
TITLE_LABEL_RE = re.compile(
    r"^\s*(?:第(?P<number>[〇零一二三四五六七八九十百千万两0-9]+)章|第[〇零一二三四五六七八九十百千万两0-9]+[卷回节]"
    r"|卷[〇零一二三四五六七八九十百千万两0-9]+|Chapter\s*(?P<english>[0-9]+)|(?P<numeric>[0-9]+)[.、](?![0-9])"
    r"|(?P<special>楔子|序章|引子|前言|后记|尾声|番外[〇零一二三四五六七八九十百千万两0-9]*))",
    re.IGNORECASE,
)
# Author notes appended to a heading, e.g. 「（求收藏）」「【二合一】」.
TITLE_NOTE_RE = re.compile(r"[(\[【〔〖][^()\[\]【】〔〕〖〗]*[)\]】〕〗]\s*$")
TITLE_NOISE_RE = re.compile(r"[\s\-—:：、.,;!?\"“”'‘’《》「」『』()\[\]【】〔〕〖〗]+")


def nonempty(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def any_nonempty(paths: Iterable[Path]) -> bool:
    return any(nonempty(path) for path in paths)


def read_text(path: Path) -> str | None:
    if not nonempty(path):
        return None
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return None


def read_progress(path: Path) -> tuple[int | None, int | None, str | None]:
    text = read_text(path)
    if text is None:
        return None, None, "unreadable" if path.exists() else None
    schema_match = SCHEMA_RE.search(text)
    total_match = TOTAL_RE.search(text) or COVERAGE_TOTAL_RE.search(text)
    final_match = FINAL_RE.search(text)
    return (
        int(schema_match.group(1)) if schema_match else None,
        int(total_match.group(1)) if total_match else None,
        final_match.group(1).lower() if final_match else None,
    )


def read_declared_total(paths: Iterable[Path]) -> tuple[int | None, str | None]:
    for path in paths:
        text = read_text(path)
        if text is None:
            continue
        match = TOTAL_RE.search(text) or TOTAL_FALLBACK_RE.search(text) or TABLE_CHAPTER_TOTAL_RE.search(text)
        if match and int(match.group(1)) > 0:
            return int(match.group(1)), path.as_posix()
    return None, None


def read_source_hash(paths: Iterable[Path]) -> tuple[str | None, str | None]:
    for path in paths:
        text = read_text(path)
        if text is None:
            continue
        match = SOURCE_HASH_RE.search(text)
        if match:
            return match.group(1).lower(), path.as_posix()
    return None, None


def read_index_chapters(path: Path) -> tuple[list[int], list[str]]:
    if not nonempty(path):
        return [], []
    errors: list[str] = []
    chapters: list[int] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"chapter", "char_count", "source_locator", "status", "source_sha256"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                return [], ["chapter_index.csv 缺列：" + ", ".join(sorted(missing))]
            for row_number, row in enumerate(reader, start=2):
                try:
                    chapters.append(int(row["chapter"]))
                except (TypeError, ValueError):
                    errors.append(f"chapter_index.csv 第 {row_number} 行章号无效")
    except (OSError, UnicodeError, csv.Error) as exc:
        return [], [f"chapter_index.csv 不可读：{exc}"]
    if len(chapters) != len(set(chapters)):
        errors.append("chapter_index.csv 存在重复章号")
    unique = sorted(set(chapters))
    if unique and unique != list(range(1, max(unique) + 1)):
        errors.append("chapter_index.csv 章号不连续")
    return unique, errors


def read_index_identities(path: Path) -> list[dict[str, str]]:
    if not nonempty(path):
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except (OSError, UnicodeError, csv.Error):
        return []


def read_managed_stages(text: str | None) -> tuple[bool, dict[str, dict[str, str]]]:
    if not text or text.count(STATE_START) != 1 or text.count(STATE_END) != 1:
        return False, {}
    match = re.search(re.escape(STATE_START) + r"(.*?)" + re.escape(STATE_END), text, re.DOTALL)
    if not match:
        return False, {}
    stages: dict[str, dict[str, str]] = {}
    section = None
    for line in match.group(1).splitlines():
        if line.strip() == "### 阶段状态":
            section = "stages"
            continue
        if line.startswith("### "):
            section = None
            continue
        if section != "stages" or not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0] not in {"阶段", "---"}:
            stages[cells[0].lower()] = {"status": cells[1].lower(), "output": cells[2]}
    return True, stages


def collect_numbered_files(
    directory: Path, pattern: re.Pattern[str]
) -> tuple[list[int], dict[int, Path], list[str]]:
    chapters: list[int] = []
    sources: dict[int, Path] = {}
    duplicates: list[str] = []
    if not directory.is_dir():
        return chapters, sources, duplicates
    for path in sorted(directory.iterdir()):
        match = pattern.match(path.name)
        if not match or not nonempty(path):
            continue
        chapter = int(match.group(1))
        if chapter in sources:
            duplicates.append(f"第{chapter}章：{sources[chapter].as_posix()} / {path.as_posix()}")
            continue
        chapters.append(chapter)
        sources[chapter] = path
    return sorted(chapters), sources, duplicates


def compact_ranges(chapters: Iterable[int]) -> list[str]:
    values = sorted(set(chapters))
    if not values:
        return []
    ranges: list[str] = []
    start = previous = values[0]
    for chapter in values[1:]:
        if chapter == previous + 1:
            previous = chapter
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = chapter
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ranges


def relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def summary_kind(path: Path) -> str:
    text = read_text(path) or ""
    return "three_script_projection" if PROJECTION_RE.search(text[:1000]) else "upstream_summary"


def read_legacy_boundaries(text: str | None) -> list[dict[str, object]]:
    """Rows of the v0.7.x 「章节边界」 table: old chapter number, title, start line."""
    if not text:
        return []
    rows: list[dict[str, object]] = []
    in_section = False
    header: list[str] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if in_section and rows:
                break
            in_section = bool(BOUNDARY_HEADING_RE.match(stripped))
            header = None
            continue
        if not in_section or not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if header is None:
            if "章号" in cells:
                header = cells
            continue
        if not "".join(cells).strip("-: "):
            continue
        record = dict(zip(header, cells))
        number = re.search(r"\d+", record.get("章号", ""))
        start = re.search(r"\d+", record.get("起始行", ""))
        if not number:
            continue
        rows.append({
            "chapter": int(number.group(0)),
            "title": record.get("标题", ""),
            "start_line": int(start.group(0)) if start else None,
        })
    return rows


def title_parts(title: str) -> tuple[str, str, str]:
    """(label, strict key, loose key) of a heading; loose drops trailing author notes."""
    text = unicodedata.normalize("NFKC", str(title or "")).strip()
    label = ""
    for _ in range(3):
        match = TITLE_LABEL_RE.match(text)
        if not match or not match.group(0).strip():
            break
        for group in ("number", "english", "numeric", "special"):
            if match.group(group):
                label = match.group(group)
        text = text[match.end():]
    strict = TITLE_NOISE_RE.sub("", text)
    loose = text
    while TITLE_NOTE_RE.search(loose):
        loose = TITLE_NOTE_RE.sub("", loose)
    return label, strict, TITLE_NOISE_RE.sub("", loose) or strict


def label_matches(label: str, row: dict[str, object]) -> bool:
    source = str(row.get("source_chapter", "")).strip()
    if not label or not source:
        return False
    if label == source:
        return True
    try:
        from build_chapter_index import parse_number
        return source.isdigit() and parse_number(label) == int(source)
    except ValueError:
        return False


def title_candidates(title: str, index_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Index rows whose title agrees with an old table title, best tier first."""
    label, strict, loose = title_parts(title)
    if strict:
        keys = [(row, title_parts(str(row.get("title", "")))) for row in index_rows]
        for tier in (
            [row for row, (_, row_strict, _) in keys if row_strict == strict],
            [row for row, (_, _, row_loose) in keys
             if row_loose and (row_loose == loose or row_loose in loose or loose in row_loose)],
        ):
            if tier:
                return tier
    # Retitled or title-less headings still carry their chapter number.
    return [row for row in index_rows if label_matches(label, row)]


def map_legacy_row(old: dict[str, object], index_rows: list[dict[str, object]]) -> int | None:
    """Index chapter an old boundary row points at.

    A start line that is exactly a chapter's heading line decides on its own.
    Otherwise the title picks the chapter (nearest to the old start line when
    several match); a title-less row falls back to the chapter holding the line.
    """
    start = old.get("start_line")
    if isinstance(start, int):
        for row in index_rows:
            if int(row["start_line"]) == start:
                return int(row["chapter"])
    matches = title_candidates(str(old.get("title", "")), index_rows)
    if not isinstance(start, int):
        return int(matches[0]["chapter"]) if len(matches) == 1 else None
    if not matches and not any(title_parts(str(old.get("title", "")))[:2]):
        matches = [row for row in index_rows if int(row["start_line"]) <= start <= int(row["end_line"])]

    def distance(row: dict[str, object]) -> int:
        first, last = int(row["start_line"]), int(row["end_line"])
        return 0 if first <= start <= last else min(abs(start - first), abs(start - last))

    ranked = sorted(matches, key=distance)
    if not ranked or (len(ranked) > 1 and distance(ranked[0]) == distance(ranked[1])):
        return None
    return int(ranked[0]["chapter"])


def leading_special_labels(index_rows: list[dict[str, object]]) -> list[str]:
    """Prologue-like chapters (楔子、序章、第0章…) before the first numbered chapter."""
    labels: list[str] = []
    for row in index_rows:
        source = str(row.get("source_chapter", "")).strip()
        if source.isdigit() and int(source) >= 1:
            break
        labels.append("第0章" if source == "0" else source)
    return labels


def mapping_author_message(detail: str, labels: list[str], done: str) -> str:
    """One plain-language stop message with the author's choices (no field names)."""
    if labels:
        prologue = "、".join("「%s」" % label for label in labels)
        return (
            "先停一下：%s。这次重新识别章节时，开头的%s被算成了单独一章，"
            "照这样续拆，旧文件会整体错开一章——%s没人拆、有的章被拆两遍。请选一种："
            "① 按旧章号继续（推荐，旧拆文当时没把%s算作一章时选这个）：%s并进第一章，"
            "已拆好的%s原样复用，%s不单独拆；"
            "② %s单独算一章：这本书已有的拆文结果全部挪进备份目录（不删除），按新章号重拆；"
            "③ 换一个新目录，整本重新拆。"
            % (detail, prologue, prologue, prologue, prologue, done, prologue, prologue)
        )
    return (
        "先停一下：%s，没法确认已拆好的%s各对应哪一章。请选一种："
        "① 换一个新目录，整本重新拆（推荐）；② 如果原文换过版本或被改过，换回拆文时用的那份原文再续拆。"
        % (detail, done)
    )


def legacy_mapping_check(root: Path, index_rows: list[dict[str, object]]) -> dict[str, object] | None:
    """Stop when files numbered by an older run no longer match the chapter index.

    Old summaries always predate the index. Golden-chapter analyses count as old
    when ``_progress.md`` comes from v0.7.x (a 「章节边界」 table or no runtime
    block); this run's Stage 1 writes them against the index. The old boundary
    table, when present, decides; otherwise a source that does not start at
    chapter one is ambiguous.
    """
    if not index_rows:
        return None
    progress_text = read_text(root / "_progress.md")
    boundaries = read_legacy_boundaries(progress_text)
    legacy_progress = progress_text is not None and (bool(boundaries) or STATE_START not in progress_text)
    _, summary_sources, _ = collect_numbered_files(root / "章节", SUMMARY_RE)
    old_chapters = {chapter for chapter, path in summary_sources.items() if summary_kind(path) == "upstream_summary"}
    old_kinds = ["逐章摘要"] if old_chapters else []
    if legacy_progress:
        golden, _, _ = collect_numbered_files(root / "章节", GOLDEN_RE)
        if golden:
            old_chapters.update(golden)
            old_kinds.insert(0, "开头三章拆解")
    if not old_chapters:
        return None
    rows = sorted(index_rows, key=lambda row: int(row["chapter"]))
    labels = leading_special_labels(rows)
    done = "、".join(old_kinds)
    if boundaries:
        by_old = {int(row["chapter"]): row for row in boundaries}
        # Chapters the old run appended after its table stay on the same numbering
        # as long as every chapter the table does cover lines up.
        checked = sorted(chapter for chapter in old_chapters if chapter <= max(by_old)) or sorted(old_chapters)
        shifted = []
        unknown = []
        for chapter in checked:
            old = by_old.get(chapter)
            mapped = map_legacy_row(old, rows) if old else None
            if mapped is None:
                unknown.append(chapter)
            elif mapped != chapter:
                shifted.append((chapter, mapped))
        if not shifted and not unknown:
            return None
        if shifted:
            old_number, new_number = shifted[0]
            title = next((str(row.get("title", "")) for row in rows if int(row["chapter"]) == new_number), "")
            detail = "旧拆文的第%s章「%s」，在这次的章节表里是第%s章" % (old_number, title, new_number)
        else:
            detail = "旧进度里的章节表和原文对不上（第%s章找不到）" % compact_ranges(unknown)[0]
        code = "legacy_boundary_shift" if shifted else "legacy_boundary_unmatched"
    else:
        first_source = str(rows[0].get("source_chapter", "")).strip()
        if first_source.isdigit() and int(first_source) == 1:
            return None
        detail = "原文开头是「%s」，而旧拆文没有留下能核对章号的章节表" % (first_source or "未知")
        code = "legacy_identity_unverifiable"
    return {
        "code": code,
        "conflict": "旧拆文章号与当前索引不一致：" + detail,
        "author_message": mapping_author_message(detail, labels, done),
        "fold_prologue_available": bool(labels),
        "legacy_chapters": sorted(old_chapters),
    }


def inspect(root: Path, expected_override: int | None) -> dict[str, object]:
    root = root.resolve()
    schema, progress_total, final_state = read_progress(root / "_progress.md")
    progress_text = read_text(root / "_progress.md")
    index_chapters, index_errors = read_index_chapters(root / "chapter_index.csv")
    index_identities = read_index_identities(root / "chapter_index.csv")
    managed_state_present, managed_stages = read_managed_stages(progress_text)

    summaries, summary_sources, duplicate_summaries = collect_numbered_files(root / "章节", SUMMARY_RE)
    golden, golden_sources, duplicate_golden = collect_numbered_files(root / "章节", GOLDEN_RE)

    preferred_paths: dict[int, str] = {}
    preferred_kinds: dict[int, str] = {}
    for chapter, path in summary_sources.items():
        preferred_paths[chapter] = relative(root, path)
        preferred_kinds[chapter] = summary_kind(path)
    for chapter, path in golden_sources.items():
        if chapter not in preferred_paths:
            preferred_paths[chapter] = relative(root, path)
            preferred_kinds[chapter] = "golden_analysis"

    expected = expected_override
    expected_source = "argument" if expected is not None else None
    if expected is None and index_chapters and not index_errors:
        expected = max(index_chapters)
        expected_source = "chapter_index.csv"
    if expected is None and progress_total is not None and final_state in {"completed", "completed_with_errors"}:
        expected = progress_total
        expected_source = "_progress.md"
    if expected is None:
        expected, source = read_declared_total((root / "拆文报告.md", root / "概要.md", root / "快速预览.md"))
        expected_source = Path(source).name if source else None
    if expected is None and progress_total is not None:
        expected = progress_total
        expected_source = "_progress.md"

    expected_set = set(range(1, expected + 1)) if expected else set()
    union_semantic_set = set(preferred_paths)
    missing_semantic = sorted(expected_set - union_semantic_set)
    out_of_range_semantic = sorted(union_semantic_set - expected_set) if expected else []
    missing_summaries = sorted(expected_set - set(summaries))
    out_of_range_summaries = sorted(set(summaries) - expected_set) if expected else []

    primary = {
        "emotion_module": nonempty(root / "剧情" / "情绪模块.md"),
        "rhythm": nonempty(root / "剧情" / "节奏.md"),
    }
    plot_dir = root / "剧情"
    assets = {
        "report": nonempty(root / "拆文报告.md"),
        "style": nonempty(root / "文风.md"),
        "storyline": nonempty(plot_dir / "故事线.md"),
        "plot_units": any_nonempty(
            path
            for path in plot_dir.glob("*.md")
            if path.name not in {"README.md", "故事线.md", "节奏.md", "情绪模块.md", "散落情节.md"}
        )
        if plot_dir.is_dir()
        else False,
        "characters": any_nonempty((root / "角色").glob("*.md")) if (root / "角色").is_dir() else False,
        "settings": any_nonempty((root / "设定").rglob("*.md")) if (root / "设定").is_dir() else False,
        "batch_cache": any_nonempty((root / "_analysis_cache").glob("批次-*.md"))
        if (root / "_analysis_cache").is_dir()
        else False,
        "chapter_index": nonempty(root / "chapter_index.csv"),
    }

    has_any = bool(union_semantic_set) or any(assets.values()) or any(primary.values()) or nonempty(root / "_progress.md")
    semantic_coverage_complete = bool(union_semantic_set) and (
        (expected is not None and not missing_semantic and not out_of_range_semantic)
        or (expected is None and final_state in {"completed", "completed_with_errors"})
    )
    summary_coverage_complete = (
        bool(summaries) and expected is not None and not missing_summaries and not out_of_range_summaries
    )
    standard_coverage_complete = bool(union_semantic_set) and expected is not None and union_semantic_set == expected_set
    legacy_core = assets["report"] and summary_coverage_complete and (assets["storyline"] or assets["plot_units"])
    managed_pipeline_complete = all(
        managed_stages.get(stage, {}).get("status") == "completed"
        for stage in ("stage1", "stage2", "stage3", "stage4", "stage5", "stage6")
    )
    usable_upstream_complete = (
        all(primary.values())
        and assets["report"]
        and standard_coverage_complete
        and (
            managed_pipeline_complete
            or (
                final_state in {"completed", "completed_with_errors"}
                and (assets["storyline"] or assets["plot_units"])
            )
        )
    )

    if expected:
        preferred_paths = {chapter: path for chapter, path in preferred_paths.items() if chapter in expected_set}
        preferred_kinds = {chapter: kind for chapter, kind in preferred_kinds.items() if chapter in expected_set}
    semantic_set = set(preferred_paths)

    full_result_available = usable_upstream_complete or legacy_core
    mixed_sources = len(set(preferred_kinds.values())) > 1

    # Files numbered by an older run can drift from the index; this run's golden
    # analyses and projections are written against it.
    mapping_conflicts: list[str] = []
    mapping_blocked_chapters: list[int] = []
    mapping = legacy_mapping_check(root, index_identities) if index_identities else None
    if mapping:
        mapping_blocked_chapters = sorted(expected_set or set(index_chapters))
        mapping_conflicts.append(str(mapping["conflict"]))

    stage_repairs: list[str] = []
    if semantic_coverage_complete:
        legacy_completed = final_state in {"completed", "completed_with_errors"}
        if not primary["emotion_module"]:
            stage_repairs.append("stage3_emotion")
        if not primary["rhythm"]:
            stage_repairs.append("stage3_rhythm")
        if not legacy_completed and (not assets["characters"] or not assets["settings"]):
            stage_repairs.append("stage4")
        if not assets["report"]:
            stage_repairs.append("stage5")
        if not assets["style"]:
            stage_repairs.append("stage6_style")
        for stage in ("stage3", "stage4", "stage5", "stage6"):
            row = managed_stages.get(stage)
            if row and row.get("status") != "completed" and stage not in stage_repairs:
                stage_repairs.append(stage)
            elif managed_state_present and not legacy_completed and row is None:
                # New three-script runs require a completed stage row even when
                # a file was manually placed before the interruption.
                if stage not in stage_repairs and not any(item.startswith(stage + "_") for item in stage_repairs):
                    stage_repairs.append(stage)

    if not has_any:
        classification = "empty"
        recommended_path = "new_analysis"
    elif usable_upstream_complete:
        classification = "current_complete"
        recommended_path = "repair_stages" if stage_repairs else "direct_use"
    elif legacy_core:
        classification = "legacy_complete"
        recommended_path = "repair_stages" if stage_repairs else "direct_use"
    elif semantic_coverage_complete:
        classification = "partial_or_mixed"
        recommended_path = "repair_stages" if stage_repairs else "enhance_existing"
    else:
        classification = "partial_or_mixed"
        recommended_path = "continue_partial" if expected and missing_semantic else "enhance_existing"

    conflicts = list(index_errors)
    conflicts.extend(f"重复摘要：{item}" for item in duplicate_summaries)
    conflicts.extend(f"重复黄金三章：{item}" for item in duplicate_golden)
    conflicts.extend(mapping_conflicts)
    if final_state == "completed" and not usable_upstream_complete:
        conflicts.append("进度标记 completed，但当前主产物或上游逐章覆盖不完整")
    if final_state == "completed_with_errors" and not semantic_coverage_complete:
        conflicts.append("进度标记 completed_with_errors，需按失败与待核记录确认可用范围")
    if index_chapters and expected and max(index_chapters) != expected:
        conflicts.append("机械索引章数与期望章数不一致")

    source_hash, source_hash_path = read_source_hash((root / "_progress.md",))

    return {
        "root": str(root),
        "classification": classification,
        "recommended_path": recommended_path,
        "schema_version": schema,
        "final_state": final_state,
        "expected_chapters": expected,
        "expected_chapters_source": expected_source,
        # Original keys remain for callers that need the upstream interface itself.
        "completed_summary_chapters": summaries,
        "missing_summary_chapters": missing_summaries,
        "out_of_range_summary_chapters": out_of_range_summaries,
        # Runtime routing must use the selected semantic family below, never summary filenames alone.
        "completed_semantic_chapters": sorted(semantic_set),
        "missing_semantic_chapters": missing_semantic,
        "out_of_range_semantic_chapters": out_of_range_semantic,
        "semantic_coverage_complete": semantic_coverage_complete,
        "full_result_available": full_result_available,
        "chapter_sources": {
            "priority": ["upstream_summary", "three_script_projection", "golden_analysis"],
            "upstream_summary": {"chapters": summaries, "ranges": compact_ranges(summaries)},
            "golden_analysis": {"chapters": golden, "ranges": compact_ranges(golden)},
            "preferred_by_chapter": {str(chapter): preferred_kinds[chapter] for chapter in sorted(preferred_kinds)},
            "preferred_paths": {str(chapter): preferred_paths[chapter] for chapter in sorted(preferred_paths)},
        },
        "source_hash": source_hash,
        "source_hash_source": source_hash_path,
        "primary_artifacts": primary,
        "reusable_assets": assets,
        "legacy_capabilities": {
            "benchmark_reference": full_result_available or assets["report"] or assets["plot_units"] or bool(semantic_set),
            "import_facts": bool(semantic_set),
            "writing_style_reference": assets["style"],
        },
        "current_capabilities": {
            "emotion_module_recall": primary["emotion_module"],
            "rhythm_reference_recall": primary["rhythm"],
            "source_location": assets["chapter_index"],
        },
        "mixed_sources": mixed_sources,
        "stage_repairs": stage_repairs,
        "managed_stage_status": managed_stages,
        "chapter_mapping_conflicts": mapping_conflicts,
        "chapter_mapping_blocked_chapters": mapping_blocked_chapters,
        "chapter_mapping_author_message": mapping["author_message"] if mapping else None,
        "provenance_requires_review": mixed_sources or (has_any and schema is None),
        "conflicts": conflicts,
        "notes": [
            "本检查只扫描传入书目目录中的上游标准路径，不扫描其他项目或磁盘。",
            "运行路由必须使用 completed_semantic_chapters；缺少逐章摘要文件不等于缺少语义成果。",
            "direct_use 表示默认直接复用；只有用户明确要求增强时才二次提取已有成果。",
            "整本重拆换一个新目录；本检查不提供就地重拆入口。",
        ],
    }


def compact_payload(payload: dict[str, object]) -> dict[str, object]:
    """Remove per-chapter arrays from the human/model-facing inspection view."""
    result = dict(payload)
    semantic = result.pop("completed_semantic_chapters")
    missing = result.pop("missing_semantic_chapters")
    result["semantic_coverage"] = {
        "completed_count": len(semantic),
        "completed_ranges": compact_ranges(semantic),
        "missing_count": len(missing),
        "missing_ranges": compact_ranges(missing),
    }
    result.pop("completed_summary_chapters", None)
    result.pop("missing_summary_chapters", None)
    result.pop("out_of_range_summary_chapters", None)
    result.pop("out_of_range_semantic_chapters", None)
    source_info = dict(result["chapter_sources"])
    source_info.pop("preferred_by_chapter", None)
    source_info.pop("preferred_paths", None)
    for key in ("upstream_summary", "golden_analysis"):
        entry = dict(source_info[key])
        entry["count"] = len(entry.pop("chapters"))
        source_info[key] = entry
    result["chapter_sources"] = source_info
    return result


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="拆文库/{书名} 目录")
    parser.add_argument("--expected-chapters", type=int, help="已知总章数；省略时按标准路径优先推断")
    parser.add_argument("--compact", action="store_true", help="省略逐章数组，输出适合运行路由读取的范围摘要")
    args = parser.parse_args()
    if args.expected_chapters is not None and args.expected_chapters < 1:
        parser.error("--expected-chapters 必须大于 0")
    try:
        if not args.root.exists():
            raise ValueError("root_not_found:%s" % args.root)
        if not args.root.is_dir():
            raise ValueError("root_is_not_directory:%s" % args.root)
        # Force a directory read here so an unreadable path fails before it can
        # be mistaken for an empty new-analysis project.
        next(args.root.iterdir(), None)
        payload = inspect(args.root, args.expected_chapters)
        if args.compact:
            payload = compact_payload(payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
