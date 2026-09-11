#!/usr/bin/env python3
"""Inspect reusable long-analysis assets without changing user files.

The upstream directory contract is checked first. A complete upstream family
is selected as a whole; otherwise a complete compact chapter-card family is
selected as a whole. Chapter-level gap filling is used only when neither family
is complete.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Iterable


SUMMARY_RE = re.compile(r"^第0*(\d+)章_摘要\.md$")
GOLDEN_RE = re.compile(r"^第0*(\d+)章_深度拆解\.md$")
CARD_ROW_RE = re.compile(r"^\|\s*(?:第\s*)?0*(\d+)(?:\s*章)?\s*\|")
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


def known_card_directories(root: Path) -> list[Path]:
    candidates = (root / "章节卡", root / "v2" / "章节卡", root / "V2" / "章节卡")
    result: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if path.is_dir():
            resolved = path.resolve()
            if resolved not in seen:
                result.append(path)
                seen.add(resolved)
    return result


def collect_chapter_cards(root: Path) -> tuple[list[int], dict[int, Path], list[str], list[Path]]:
    chapters: list[int] = []
    sources: dict[int, Path] = {}
    duplicates: list[str] = []
    files: list[Path] = []
    for directory in known_card_directories(root):
        for path in sorted(directory.glob("*.md")):
            text = read_text(path)
            if text is None:
                continue
            found = False
            for line in text.splitlines():
                match = CARD_ROW_RE.match(line)
                if not match:
                    continue
                found = True
                chapter = int(match.group(1))
                if chapter in sources:
                    duplicates.append(f"第{chapter}章：{sources[chapter].as_posix()} / {path.as_posix()}")
                    continue
                chapters.append(chapter)
                sources[chapter] = path
            if found:
                files.append(path)
    return sorted(set(chapters)), sources, duplicates, files


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


def inspect(root: Path, expected_override: int | None) -> dict[str, object]:
    root = root.resolve()
    schema, progress_total, final_state = read_progress(root / "_progress.md")
    index_chapters, index_errors = read_index_chapters(root / "chapter_index.csv")

    summaries, summary_sources, duplicate_summaries = collect_numbered_files(root / "章节", SUMMARY_RE)
    golden, golden_sources, duplicate_golden = collect_numbered_files(root / "章节", GOLDEN_RE)
    card_chapters, card_sources, duplicate_cards, card_files = collect_chapter_cards(root)

    # Build the union first. After total coverage is known, prefer one complete
    # source family; only partial families are combined chapter by chapter.
    standard_paths: dict[int, str] = {}
    standard_kinds: dict[int, str] = {}
    preferred_paths: dict[int, str] = {}
    preferred_kinds: dict[int, str] = {}
    for chapter, path in summary_sources.items():
        standard_paths[chapter] = relative(root, path)
        standard_kinds[chapter] = "upstream_summary"
    for chapter, path in golden_sources.items():
        if chapter not in standard_paths:
            standard_paths[chapter] = relative(root, path)
            standard_kinds[chapter] = "golden_analysis"
    preferred_paths.update(standard_paths)
    preferred_kinds.update(standard_kinds)
    for chapter, path in card_sources.items():
        if chapter not in preferred_paths:
            preferred_paths[chapter] = relative(root, path)
            preferred_kinds[chapter] = "compact_chapter_card"

    v2_root = root / "v2"
    if not v2_root.is_dir():
        v2_root = root / "V2"
    alt_schema, alt_progress_total, alt_final_state = read_progress(v2_root / "_progress.md")

    expected = expected_override
    expected_source = "argument" if expected is not None else None
    if expected is None and index_chapters and not index_errors:
        expected = max(index_chapters)
        expected_source = "chapter_index.csv"
    if expected is None and progress_total is not None and final_state in {"completed", "completed_with_errors"}:
        expected = progress_total
        expected_source = "_progress.md"
    if expected is None and alt_progress_total is not None and alt_final_state in {"completed", "completed_with_errors"}:
        expected = alt_progress_total
        expected_source = f"{v2_root.name}/_progress.md"
    if expected is None:
        expected, source = read_declared_total((root / "拆文报告.md", root / "概要.md", root / "快速预览.md"))
        expected_source = Path(source).name if source else None
    if expected is None and progress_total is not None:
        expected = progress_total
        expected_source = "_progress.md"
    if expected is None and alt_progress_total is not None:
        expected = alt_progress_total
        expected_source = f"{v2_root.name}/_progress.md"
    if expected is None:
        expected, source = read_declared_total(
            (v2_root / "输入报告.md", v2_root / "全局建模.md", v2_root / "快速预览.md")
        )
        expected_source = relative(root, Path(source)) if source else None

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
        "batch_cache": (
            any_nonempty((root / "_analysis_cache").glob("批次-*.md"))
            or any_nonempty((root / "_analysis_cache").glob("复用提取-*.md"))
        )
        if (root / "_analysis_cache").is_dir()
        else False,
        "chapter_index": nonempty(root / "chapter_index.csv"),
        "compact_chapter_cards": bool(card_files),
        "compact_global_model": nonempty(v2_root / "全局建模.md"),
        "compact_commercial_analysis": nonempty(v2_root / "商业分析.md"),
    }

    has_any = bool(union_semantic_set) or any(assets.values()) or any(primary.values()) or nonempty(root / "_progress.md")
    semantic_coverage_complete = bool(union_semantic_set) and (
        (expected is not None and not missing_semantic and not out_of_range_semantic)
        or (expected is None and final_state in {"completed", "completed_with_errors"})
        or (expected is None and alt_final_state in {"completed", "completed_with_errors"})
    )
    summary_coverage_complete = (
        bool(summaries) and expected is not None and not missing_summaries and not out_of_range_summaries
    )
    card_set = set(card_sources)
    card_coverage_complete = bool(card_set) and expected is not None and card_set == expected_set
    standard_set = set(standard_paths)
    standard_coverage_complete = bool(standard_set) and expected is not None and standard_set == expected_set
    legacy_core = assets["report"] and summary_coverage_complete and (assets["storyline"] or assets["plot_units"])
    compact_core = (
        assets["compact_chapter_cards"]
        and assets["compact_global_model"]
        and alt_final_state in {"completed", "completed_with_errors"}
        and card_coverage_complete
    )
    current_contract_complete = (
        schema == 2
        and final_state == "completed"
        and all(primary.values())
        and assets["report"]
        and (assets["storyline"] or assets["plot_units"])
        and standard_coverage_complete
    )

    if standard_coverage_complete:
        source_selection = "complete_upstream_family"
        preferred_paths = standard_paths
        preferred_kinds = standard_kinds
    elif compact_core:
        source_selection = "complete_compact_family"
        preferred_paths = {chapter: relative(root, path) for chapter, path in card_sources.items()}
        preferred_kinds = {chapter: "compact_chapter_card" for chapter in card_sources}
    else:
        source_selection = "partial_families_upstream_first_gap_fill"

    if expected:
        preferred_paths = {chapter: path for chapter, path in preferred_paths.items() if chapter in expected_set}
        preferred_kinds = {chapter: kind for chapter, kind in preferred_kinds.items() if chapter in expected_set}
    semantic_set = set(preferred_paths)

    full_result_available = current_contract_complete or compact_core or (schema != 2 and legacy_core)
    available_source_kinds: set[str] = set()
    if summaries:
        available_source_kinds.add("upstream_summary")
    if golden:
        available_source_kinds.add("golden_analysis")
    if card_chapters:
        available_source_kinds.add("compact_chapter_card")
    current_markers = schema == 2 or assets["batch_cache"] or any(primary.values())
    mixed_sources = (
        "compact_chapter_card" in available_source_kinds
        and bool(available_source_kinds - {"compact_chapter_card"})
    ) or (schema != 2 and current_markers and legacy_core)

    if not has_any:
        classification = "empty"
        recommended_path = "new_analysis"
    elif current_contract_complete:
        classification = "current_complete"
        recommended_path = "direct_use"
    elif compact_core or (schema != 2 and legacy_core):
        classification = "legacy_complete"
        recommended_path = "direct_use"
    elif schema == 2:
        classification = "current_incomplete"
        recommended_path = "continue_partial" if expected and missing_semantic else "enhance_existing"
    elif semantic_coverage_complete:
        classification = "partial_or_mixed"
        recommended_path = "enhance_existing"
    else:
        classification = "partial_or_mixed"
        recommended_path = "continue_partial" if expected and missing_semantic else "enhance_existing"

    conflicts = list(index_errors)
    conflicts.extend(f"重复摘要：{item}" for item in duplicate_summaries)
    conflicts.extend(f"重复黄金三章：{item}" for item in duplicate_golden)
    conflicts.extend(f"重复章节卡：{item}" for item in duplicate_cards)
    if schema == 2 and final_state == "completed" and not current_contract_complete:
        conflicts.append("进度标记 completed，但当前主产物或上游逐章覆盖不完整")
    if schema == 2 and final_state == "completed_with_errors":
        conflicts.append("进度标记 completed_with_errors，需按失败与待核记录确认可用范围")
    if index_chapters and expected and max(index_chapters) != expected:
        conflicts.append("机械索引章数与期望章数不一致")

    source_hash_paths = (
        (v2_root / "_progress.md", v2_root / "输入报告.md", root / "_progress.md")
        if compact_core and not current_contract_complete
        else (root / "_progress.md", v2_root / "_progress.md", v2_root / "输入报告.md")
    )
    source_hash, source_hash_path = read_source_hash(source_hash_paths)

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
            "priority": ["upstream_summary", "golden_analysis", "compact_chapter_card"],
            "selection_strategy": source_selection,
            "upstream_summary": {"chapters": summaries, "ranges": compact_ranges(summaries)},
            "golden_analysis": {"chapters": golden, "ranges": compact_ranges(golden)},
            "compact_chapter_card": {
                "chapters": card_chapters,
                "ranges": compact_ranges(card_chapters),
                "files": [relative(root, path) for path in card_files],
                "schema_version": alt_schema,
                "final_state": alt_final_state,
            },
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
        "provenance_requires_review": mixed_sources or (has_any and schema is None and not compact_core),
        "conflicts": conflicts,
        "notes": [
            "本检查只扫描传入书目目录中的上游标准路径和已知章节卡路径，不扫描其他项目或磁盘。",
            "运行路由必须使用 completed_semantic_chapters；缺少逐章摘要文件不等于缺少语义成果。",
            "direct_use 表示默认直接复用；只有用户明确要求增强时才二次提取已有成果。",
            "explicit reanalysis 必须忽略全部旧语义成果，并按新书流程重新执行。",
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
    for key in ("upstream_summary", "golden_analysis", "compact_chapter_card"):
        entry = dict(source_info[key])
        entry["count"] = len(entry.pop("chapters"))
        source_info[key] = entry
    result["chapter_sources"] = source_info
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="拆文库/{书名} 目录")
    parser.add_argument("--expected-chapters", type=int, help="已知总章数；省略时按标准路径优先推断")
    parser.add_argument("--compact", action="store_true", help="省略逐章数组，输出适合运行路由读取的范围摘要")
    args = parser.parse_args()
    if args.expected_chapters is not None and args.expected_chapters < 1:
        parser.error("--expected-chapters 必须大于 0")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    payload = inspect(args.root, args.expected_chapters)
    if args.compact:
        payload = compact_payload(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
