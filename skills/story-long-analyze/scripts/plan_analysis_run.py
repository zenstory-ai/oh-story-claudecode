#!/usr/bin/env python3
"""Build a no-overlap execution plan for story-long-analyze.

The plan separates chapters backed by existing analysis artifacts from chapters
that still require one raw-text semantic read. It never reads novel prose.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Iterable

from inspect_existing_assets import compact_ranges, inspect


DEFAULT_MAX_BLOCK_CHARS = 25_000
DEFAULT_MAX_BLOCK_CHAPTERS = 10
DEFAULT_REUSE_BATCH_CHARS = 60_000
DEFAULT_REUSE_BATCH_CHAPTERS = 20


class PlanError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def load_index(path: Path) -> tuple[dict[int, dict[str, str]], str | None]:
    if not path.is_file():
        raise PlanError("chapter_index_required", f"机械索引不存在：{path}")
    rows: dict[int, dict[str, str]] = {}
    source_hashes: set[str] = set()
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"chapter", "char_count", "source_locator", "status", "source_sha256"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise PlanError("chapter_index_invalid", "机械索引缺列：" + ", ".join(sorted(missing)))
            for row_number, row in enumerate(reader, start=2):
                try:
                    chapter = int(row["chapter"])
                    count = int(row["char_count"])
                except (TypeError, ValueError) as exc:
                    raise PlanError("chapter_index_invalid", f"机械索引第 {row_number} 行数字无效") from exc
                if chapter in rows or count < 0:
                    raise PlanError("chapter_index_invalid", f"机械索引第 {row_number} 行重复或字数无效")
                rows[chapter] = row
                if row.get("source_sha256"):
                    source_hashes.add(row["source_sha256"].lower())
    except (OSError, UnicodeError, csv.Error) as exc:
        if isinstance(exc, PlanError):
            raise
        raise PlanError("chapter_index_unreadable", str(exc)) from exc
    chapters = sorted(rows)
    if not chapters or chapters != list(range(1, max(chapters) + 1)):
        raise PlanError("chapter_index_invalid", "机械索引章号必须从 1 连续排列")
    if len(source_hashes) > 1:
        raise PlanError("chapter_index_invalid", "机械索引包含多个原文 hash")
    return rows, next(iter(source_hashes), None)


def flush_raw_block(
    blocks: list[dict[str, object]],
    chapters: list[int],
    rows: dict[int, dict[str, str]],
    max_chars: int,
) -> None:
    if not chapters:
        return
    first = rows[chapters[0]]
    last = rows[chapters[-1]]
    char_count = sum(int(rows[chapter]["char_count"]) for chapter in chapters)
    blocks.append(
        {
            "id": f"RAW-{len(blocks) + 1:03d}",
            "start": chapters[0],
            "end": chapters[-1],
            "chapters": len(chapters),
            "char_count": char_count,
            "oversized_single_chapter": len(chapters) == 1 and char_count > max_chars,
            "source_start": first["source_locator"],
            "source_end": last["source_locator"],
            "input_kind": "raw-original",
        }
    )


def build_raw_blocks(
    chapters: Iterable[int],
    rows: dict[int, dict[str, str]],
    max_chapters: int,
    max_chars: int,
    forced_break_after: set[int] | None = None,
) -> tuple[list[dict[str, object]], list[int]]:
    blocks: list[dict[str, object]] = []
    unavailable: list[int] = []
    current: list[int] = []
    current_chars = 0
    forced_break_after = forced_break_after or set()
    for chapter in sorted(set(chapters)):
        row = rows[chapter]
        if row.get("status", "").lower() == "empty":
            flush_raw_block(blocks, current, rows, max_chars)
            current = []
            current_chars = 0
            unavailable.append(chapter)
            continue
        count = int(row["char_count"])
        is_gap = bool(current and chapter != current[-1] + 1)
        exceeds = bool(current and (len(current) >= max_chapters or current_chars + count > max_chars))
        if is_gap or exceeds:
            flush_raw_block(blocks, current, rows, max_chars)
            current = []
            current_chars = 0
        current.append(chapter)
        current_chars += count
        if chapter in forced_break_after:
            flush_raw_block(blocks, current, rows, max_chars)
            current = []
            current_chars = 0
    flush_raw_block(blocks, current, rows, max_chars)
    return blocks, unavailable


def load_forced_breaks(root: Path, source_hash: str | None) -> set[int]:
    """Keep previously-created retry splits when a run plan is regenerated."""
    path = root / "_analysis_cache" / "batch-checkpoints.json"
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return set()
    ledger_hash = payload.get("source_sha256")
    if source_hash and ledger_hash and str(ledger_hash).lower() != source_hash.lower():
        return set()
    result: set[int] = set()
    for value in payload.get("forced_break_after", []):
        try:
            chapter = int(value)
        except (TypeError, ValueError):
            continue
        if chapter > 0:
            result.add(chapter)
    return result


def build_reuse_batches(
    root: Path,
    assets: dict[str, object],
    include_chapters: set[int] | None = None,
) -> list[dict[str, object]]:
    source_info = assets["chapter_sources"]
    kinds: dict[int, str] = {int(key): value for key, value in source_info["preferred_by_chapter"].items()}
    paths: dict[int, str] = {int(key): value for key, value in source_info["preferred_paths"].items()}
    batches: list[dict[str, object]] = []
    current: list[int] = []
    current_kind: str | None = None
    current_paths: list[str] = []
    current_bytes = 0

    def flush() -> None:
        nonlocal current, current_kind, current_paths, current_bytes
        if not current:
            return
        batches.append(
            {
                "id": f"REUSE-{len(batches) + 1:03d}",
                "start": current[0],
                "end": current[-1],
                "chapters": len(current),
                "source_kind": current_kind,
                "source_files": current_paths.copy(),
                "source_bytes": current_bytes,
                "input_kind": "existing-results",
            }
        )
        current = []
        current_kind = None
        current_paths = []
        current_bytes = 0

    for chapter in sorted(kinds):
        if include_chapters is not None and chapter not in include_chapters:
            continue
        kind = kinds[chapter]
        path = paths[chapter]
        absolute = root / Path(path)
        size = absolute.stat().st_size if absolute.is_file() else 0
        new_path = path not in current_paths
        next_bytes = current_bytes + (size if new_path else 0)
        split = bool(
            current
            and (
                chapter != current[-1] + 1
                or kind != current_kind
                or len(current) >= DEFAULT_REUSE_BATCH_CHAPTERS
                or next_bytes > DEFAULT_REUSE_BATCH_CHARS
            )
        )
        if split:
            flush()
            new_path = True
            next_bytes = size
        if not current:
            current_kind = kind
        current.append(chapter)
        if new_path:
            current_paths.append(path)
            current_bytes = next_bytes
    flush()
    return batches


def verified_raw_batch_caches(
    root: Path,
    source_hash: str | None,
) -> tuple[set[int], list[dict[str, object]]]:
    """Find committed raw batches whose receipt and every output still match."""
    receipt_dir = root / "_analysis_cache" / "receipts"
    if not source_hash or not receipt_dir.is_dir():
        return set(), []
    chapters: set[int] = set()
    records: list[dict[str, object]] = []
    for path in sorted(receipt_dir.glob("*.json")):
        try:
            receipt = json.loads(path.read_text(encoding="utf-8-sig"))
            start, end = (int(value) for value in receipt["chapter_range"])
            outputs = receipt["outputs"]
            if (
                receipt.get("status") != "success"
                or receipt.get("input_kind") != "raw-original"
                or str(receipt.get("source_sha256", "")).lower() != source_hash.lower()
                or start < 1
                or end < start
                or not isinstance(outputs, dict)
            ):
                continue
            valid = True
            cache_files: list[str] = []
            for relative, expected_hash in outputs.items():
                output = (root / str(relative)).resolve()
                try:
                    output.relative_to(root)
                except ValueError:
                    valid = False
                    break
                if not output.is_file() or hashlib.sha256(output.read_bytes()).hexdigest() != expected_hash:
                    valid = False
                    break
                if str(relative).startswith("_analysis_cache/批次-"):
                    cache_files.append(str(relative))
            if not valid or not cache_files:
                continue
        except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
        current = set(range(start, end + 1))
        if chapters & current:
            continue
        chapters.update(current)
        records.append(
            {
                "batch_id": receipt.get("batch_id", path.stem),
                "start": start,
                "end": end,
                "cache_files": cache_files,
                "receipt": path.relative_to(root).as_posix(),
                "action": "reuse_verified_batch_cache_without_model_call",
            }
        )
    return chapters, records


def chapters_in_raw_blocks(blocks: Iterable[dict[str, object]]) -> set[int]:
    result: set[int] = set()
    for block in blocks:
        result.update(range(int(block["start"]), int(block["end"]) + 1))
    return result


def build_plan(args: argparse.Namespace) -> dict[str, object]:
    root = args.root.resolve()
    assets = inspect(root, args.expected_chapters)
    index_path = args.index.resolve() if args.index else root / "chapter_index.csv"
    needs_index = args.intent == "reanalyze" or assets["recommended_path"] in {"new_analysis", "continue_partial"}

    rows: dict[int, dict[str, str]] = {}
    index_hash: str | None = None
    if needs_index:
        rows, index_hash = load_index(index_path)

    expected = int(assets["expected_chapters"] or (max(rows) if rows else 0))
    if expected < 1:
        raise PlanError("chapter_total_unknown", "无法确认总章数；新书或部分成果必须先建立全书机械索引")
    if rows and max(rows) != expected:
        raise PlanError("chapter_total_mismatch", f"成果总章数 {expected} 与机械索引 {max(rows)} 不一致")
    asset_hash = assets.get("source_hash")
    if asset_hash and index_hash and asset_hash.lower() != index_hash.lower() and args.intent != "reanalyze":
        raise PlanError("existing_assets_source_mismatch", "已有成果与当前原文 hash 不同，不能静默复用")

    all_chapters = set(range(1, expected + 1))
    existing = set(int(value) for value in assets["completed_semantic_chapters"])
    full_result = bool(assets["full_result_available"])
    verified_chapters, verified_batches = verified_raw_batch_caches(root, index_hash or asset_hash)
    verified_chapters &= existing
    verified_batches = [
        batch
        for batch in verified_batches
        if set(range(int(batch["start"]), int(batch["end"]) + 1)).issubset(verified_chapters)
    ]
    if args.intent == "reanalyze":
        verified_chapters = set()
        verified_batches = []

    if args.intent == "reanalyze":
        mode = "reanalyze_all"
        reused = set()
        golden_read = set(range(1, min(3, expected) + 1))
        raw_needed = all_chapters - golden_read
        reuse_batches: list[dict[str, object]] = []
    elif full_result and args.intent == "auto":
        mode = "direct_use"
        reused = existing
        golden_read = set()
        raw_needed = set()
        reuse_batches = []
    elif full_result and args.intent == "enhance":
        mode = "enhance_complete"
        reused = existing
        golden_read = set()
        raw_needed = set()
        reuse_batches = build_reuse_batches(root, assets, existing - verified_chapters)
    elif existing:
        mode = "resume_partial"
        reused = existing
        golden_read = {chapter for chapter in range(1, min(3, expected) + 1) if chapter not in existing}
        raw_needed = all_chapters - existing - golden_read
        reuse_batches = build_reuse_batches(root, assets, existing - verified_chapters)
    else:
        mode = "new_analysis"
        reused = set()
        golden_read = set(range(1, min(3, expected) + 1))
        raw_needed = all_chapters - golden_read
        reuse_batches = []

    pause_after_stage1 = (
        mode != "direct_use"
        and not args.full_run
        and (
            bool(golden_read)
            or (mode == "resume_partial" and assets.get("final_state") == "paused_after_stage1")
        )
    )
    raw_blocks: list[dict[str, object]] = []
    unavailable: list[int] = []
    if raw_needed:
        if not rows:
            raise PlanError("chapter_index_required", "存在未拆章节，必须先建立全书机械索引")
        raw_blocks, unavailable = build_raw_blocks(
            raw_needed,
            rows,
            args.max_block_chapters,
            args.max_block_chars,
            load_forced_breaks(root, index_hash),
        )

    raw_chapters = chapters_in_raw_blocks(raw_blocks)
    if raw_chapters & reused:
        raise PlanError("plan_overlap", "已有成果章节被错误安排为原文语义读取")
    if raw_chapters & golden_read:
        raise PlanError("plan_overlap", "黄金三章与连续块发生重叠")
    if args.intent != "reanalyze" and mode != "new_analysis" and not reused.issubset(existing):
        raise PlanError("plan_invalid", "复用范围包含未验证成果")

    covered_after_run = reused | golden_read | raw_chapters
    unresolved = sorted(all_chapters - covered_after_run)
    if unavailable:
        unresolved = sorted(set(unresolved) | set(unavailable))
    secondary_existing = reused if mode == "direct_use" else reused - verified_chapters

    return {
        "schema_version": 1,
        "root": str(root),
        "intent": args.intent,
        "mode": mode,
        "full_run": args.full_run,
        "pause_after_stage1": pause_after_stage1,
        "stage1_gate": {
            "golden_three_required": bool(golden_read),
            "preview_required": bool(golden_read),
            "state_after_preview": "paused_after_stage1" if pause_after_stage1 else "continue_stage2",
            "resume_rule": "rerun this planner with --full-run; keep verified Stage 1 files and start at the first pending Stage 2 batch",
        },
        "expected_chapters": expected,
        "source_sha256": index_hash or asset_hash,
        "asset_classification": assets["classification"],
        "full_result_available": full_result,
        "routing": {
            "existing_results": {
                "count": len(secondary_existing),
                "ranges": compact_ranges(secondary_existing),
                "action": "direct_use" if mode == "direct_use" else "secondary_extract_without_original",
            },
            "golden_three_original_read": {
                "count": len(golden_read),
                "ranges": compact_ranges(golden_read),
            },
            "raw_original_read": {
                "count": len(raw_chapters),
                "ranges": compact_ranges(raw_chapters),
                "blocks": raw_blocks,
                "rule": "each chapter belongs to exactly one non-overlapping block; one model call emits compact chapter facts and block observations",
            },
            "unavailable": {"count": len(unresolved), "ranges": compact_ranges(unresolved)},
        },
        "existing_result_batches": reuse_batches,
        "verified_batch_caches": verified_batches,
        "execution_order": (
            ["return_existing_results"]
            if mode == "direct_use"
            else [
                (
                    "reuse_complete_results_without_mechanical_index"
                    if mode == "enhance_complete"
                    else "build_or_verify_full_mechanical_index"
                ),
                "read_missing_golden_chapters_once" if golden_read else "reuse_existing_golden_results",
                "pause_for_confirmation" if pause_after_stage1 else "continue_without_pause",
                "secondary_extract_existing_results" if reuse_batches else "no_existing_result_extraction",
                "reuse_verified_batch_caches" if verified_batches else "no_verified_batch_caches",
                "read_each_raw_block_once" if raw_blocks else "no_raw_block_read",
                "merge_plot_points_and_generate_current_outputs",
            ]
        ),
        "checkpoint_contract": {
            "ledger": "_analysis_cache/batch-checkpoints.json",
            "receipts": "_analysis_cache/receipts/{batch_id}.json",
            "stage_receipts": "_analysis_cache/stage-receipts/{stage}.json",
            "retry_rule": "retry only the failed batch; split a failed raw block and retain every verified sibling batch",
        },
        "guards": {
            "per_chapter_model_calls": False,
            "raw_block_overlap": False,
            "reread_existing_original": False,
            "stage_3_to_6_fulltext_reads": False,
            "aggregation_model_passes": "one main merge plus at most one evidence-targeted verification",
            "explicit_reanalysis_ignores_old_results": args.intent == "reanalyze",
        },
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", type=Path, required=True, help="拆文库/{书名} 目录")
    result.add_argument("--index", type=Path, help="机械索引路径；默认 root/chapter_index.csv")
    result.add_argument("--expected-chapters", type=int)
    result.add_argument(
        "--intent",
        choices=("auto", "enhance", "reanalyze"),
        default="auto",
        help="auto=完整成果直接用；enhance=只从完整旧成果二次提取；reanalyze=忽略旧成果",
    )
    result.add_argument("--full-run", action="store_true", help="黄金三章后不暂停")
    result.add_argument("--max-block-chapters", type=int, default=DEFAULT_MAX_BLOCK_CHAPTERS)
    result.add_argument("--max-block-chars", type=int, default=DEFAULT_MAX_BLOCK_CHARS)
    result.add_argument("--output", type=Path, help="可选：原子写入运行计划 JSON")
    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args()
    if not 1 <= args.max_block_chapters <= 10:
        print(json.dumps({"error": "invalid_block_limit", "detail": "max-block-chapters 必须在 1-10"}, ensure_ascii=False))
        return 2
    if args.max_block_chars < 1:
        print(json.dumps({"error": "invalid_block_limit", "detail": "max-block-chars 必须大于 0"}, ensure_ascii=False))
        return 2
    try:
        payload = build_plan(args)
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            atomic_write(args.output.resolve(), rendered.encode("utf-8"))
    except PlanError as error:
        print(json.dumps({"error": error.code, "detail": error.detail}, ensure_ascii=False))
        return 2
    except (OSError, UnicodeError) as error:
        print(json.dumps({"error": "io_error", "detail": str(error)}, ensure_ascii=False))
        return 1
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
