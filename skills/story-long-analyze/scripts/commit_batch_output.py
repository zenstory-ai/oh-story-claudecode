#!/usr/bin/env python3
"""Validate and commit one story-long-analyze extraction batch.

The extractor is read-only.  This helper owns the deterministic split, conflict
check, receipt, and progress update so an interrupted batch can be resumed
without calling the model again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path


CHAPTER_TOKEN_RE = re.compile(r"<!--\s*CHAPTER_(START|END):(\d+)\s*-->")
REUSED_RANGE_RE = re.compile(r"<!--\s*REUSED_CHAPTERS:(\d+)-(\d+)\s*-->")
BATCH_START = "<!-- BATCH_OBSERVATIONS_START -->"
BATCH_END = "<!-- BATCH_OBSERVATIONS_END -->"
LEGACY_OBSERVATION_SECTION_ALIASES = (
    ("剧情点", "候选剧情单元"),
    ("客观事件",),
    ("信息披露",),
    ("关系变化",),
    ("三维节奏",),
    ("跨批状态",),
)
COMPACT_OBSERVATION_SECTION_ALIASES = (
    ("剧情点", "候选剧情单元"),
    ("关键事件与披露候选",),
    ("关系变化",),
    ("三维节奏",),
    ("跨批状态",),
)
COMPACT_CHAPTER_FIELDS = (
    "概要",
    "因果",
    "信息变化",
    "状态变化",
    "三维节奏",
    "章尾钩子",
    "证据",
)
MAX_COMPACT_CHAPTER_CHARS = 2_500


class BatchError(ValueError):
    """A user-fixable input or conflict error."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def normalized(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary_name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def has_sections(text: str, aliases: tuple[tuple[str, ...], ...]) -> bool:
    return all(
        any(re.search(rf"(?m)^###\s+{re.escape(name)}\s*$", text) for name in names)
        for names in aliases
    )


def parse_observations(text: str, minimum_offset: int = 0) -> tuple[str, str]:
    if text.count(BATCH_START) != 1 or text.count(BATCH_END) != 1:
        raise BatchError("batch_marker_mismatch", "exactly one batch observation block is required")
    observation_start = text.index(BATCH_START)
    observation_end = text.index(BATCH_END, observation_start)
    if observation_end <= observation_start or observation_start < minimum_offset:
        raise BatchError("batch_marker_order", "batch observations must follow the source coverage markers")
    observations = text[observation_start + len(BATCH_START) : observation_end].strip()
    if not re.search(r"(?m)^##\s+跨章观察\s*$", observations):
        raise BatchError("observation_schema_incomplete", "batch observation heading is missing")
    if has_sections(observations, COMPACT_OBSERVATION_SECTION_ALIASES):
        schema = "compact-v1"
    elif has_sections(observations, LEGACY_OBSERVATION_SECTION_ALIASES):
        schema = "legacy-v1"
    else:
        raise BatchError(
            "observation_schema_incomplete",
            "expected compact sections (剧情点、关键事件与披露候选、关系变化、三维节奏、跨批状态) "
            "or the legacy six-section schema",
        )
    return observations + "\n", schema


def compact_field(body: str, name: str) -> str:
    match = re.search(rf"(?m)^\*\*{re.escape(name)}\*\*\s*[：:]\s*(\S.*)$", body)
    if not match:
        raise BatchError("chapter_schema_incomplete", f"compact chapter missing: {name}")
    return match.group(1).strip()


def emotion_tone(rhythm: str) -> str:
    match = re.search(r"情绪(?:类型)?\s*[：:]?\s*([^｜|；;，,]+)", rhythm)
    if not match:
        return "其他"
    value = re.sub(r"[1-5](?:\s*/\s*5)?$", "", match.group(1)).strip()
    return value or "其他"


def render_compact_chapter(body: str, chapter: int) -> str:
    """Project compact model output into the labels used by current consumers."""
    heading = re.search(rf"(?m)^##\s+第{chapter}章(?:\s+.*)?$", body)
    if not heading:
        raise BatchError("chapter_schema_incomplete", f"chapter {chapter} missing: heading")
    fields = {name: compact_field(body, name) for name in COMPACT_CHAPTER_FIELDS}
    if len(body) > MAX_COMPACT_CHAPTER_CHARS:
        raise BatchError(
            "compact_chapter_too_verbose",
            f"chapter {chapter} has {len(body)} characters; compact limit is {MAX_COMPACT_CHAPTER_CHARS}",
        )
    tone = emotion_tone(fields["三维节奏"])
    return (
        f"{heading.group(0)}\n\n"
        f"**概要**：{fields['概要']}\n\n"
        "**关键事件**：\n"
        f"1. {fields['因果']}\n\n"
        f"**信息变化**：{fields['信息变化']}\n\n"
        f"**状态变化**：{fields['状态变化']}\n\n"
        f"**三维节奏**：{fields['三维节奏']}\n\n"
        f"**章尾钩子**：{fields['章尾钩子']}\n\n"
        f"**证据**：{fields['证据']}\n\n"
        "**情节点**：\n\n"
        f"P1 **章节变化**：类型行动 | {fields['因果']} | 证据{fields['证据']}\n"
        f"主题标签主线 | 基调：{tone}\n"
    )


def compact_cache_record(body: str, chapter: int) -> str:
    fields = {name: compact_field(body, name) for name in COMPACT_CHAPTER_FIELDS}
    return (
        f"### 第{chapter}章\n"
        + "\n".join(f"- {name}：{fields[name]}" for name in COMPACT_CHAPTER_FIELDS)
        + "\n"
    )


def parse_batch(
    text: str, start: int, end: int, input_kind: str
) -> tuple[dict[int, str], str, str, str]:
    if "BATCH_ERROR:" in text:
        raise BatchError("extractor_reported_error", "extractor returned BATCH_ERROR")
    if "{" in text or "}" in text:
        raise BatchError("template_placeholder", "output still contains template braces")

    if input_kind == "existing-results":
        if CHAPTER_TOKEN_RE.search(text):
            raise BatchError(
                "existing_result_overwrite_risk",
                "existing-results output must not contain replacement chapter blocks",
            )
        range_matches = REUSED_RANGE_RE.findall(text)
        if range_matches != [(str(start), str(end))]:
            raise BatchError(
                "reused_range_mismatch",
                f"expected exactly <!-- REUSED_CHAPTERS:{start}-{end} -->",
            )
        marker = REUSED_RANGE_RE.search(text)
        assert marker is not None
        observations, schema = parse_observations(text, marker.end())
        return {}, observations, schema, ""

    expected = list(range(start, end + 1))
    token_matches = list(CHAPTER_TOKEN_RE.finditer(text))
    tokens = [(match.group(1), int(match.group(2))) for match in token_matches]
    expected_tokens = [item for chapter in expected for item in (("START", chapter), ("END", chapter))]
    if tokens != expected_tokens:
        raise BatchError(
            "chapter_marker_mismatch",
            f"expected markers {expected_tokens}, received {tokens}",
        )

    last_chapter_end = max(match.end() for match in token_matches if match.group(1) == "END")

    chapters: dict[int, str] = {}
    compact_records: list[str] = []
    for chapter in expected:
        chapter_pattern = re.compile(
            rf"<!--\s*CHAPTER_START:{chapter}\s*-->\s*(.*?)\s*"
            rf"<!--\s*CHAPTER_END:{chapter}\s*-->",
            re.DOTALL,
        )
        match = chapter_pattern.search(text)
        if not match:
            raise BatchError("chapter_block_missing", f"chapter {chapter} block is missing")
        body = match.group(1).strip()
        if all(re.search(rf"(?m)^\*\*{re.escape(name)}\*\*\s*[：:]\s*\S+", body) for name in COMPACT_CHAPTER_FIELDS):
            chapters[chapter] = render_compact_chapter(body, chapter)
            compact_records.append(compact_cache_record(body, chapter))
        else:
            required_patterns = {
                "heading": rf"(?m)^##\s+第{chapter}章(?:\s+.*)?$",
                "summary": r"(?m)^\*\*概要\*\*\s*[：:]\s*\S+",
                "events": r"(?m)^\*\*关键事件\*\*\s*[：:]?\s*$",
                "plot_points": r"(?m)^\*\*情节点\*\*\s*[：:]?\s*$",
                "event_item": r"(?m)^\s*1[.、]\s*\S+",
                "plot_point_item": r"(?m)^P\d+\s+\*\*.+?\*\*\s*[：:]",
            }
            missing = [name for name, pattern in required_patterns.items() if not re.search(pattern, body)]
            if missing:
                raise BatchError("chapter_schema_incomplete", f"chapter {chapter} missing: {', '.join(missing)}")
            chapters[chapter] = body + "\n"

    observations, observation_schema = parse_observations(text, last_chapter_end)
    if compact_records and len(compact_records) != len(expected):
        raise BatchError("mixed_batch_schema", "all chapters in one raw batch must use the same schema")
    chapter_schema = "compact-v1" if compact_records else "legacy-v1"
    if chapter_schema == "compact-v1" and observation_schema != "compact-v1":
        raise BatchError("mixed_batch_schema", "compact chapter output must use compact block observations")
    compact_facts = "\n".join(compact_records).strip() + "\n" if compact_records else ""
    return chapters, observations, chapter_schema, compact_facts


def update_progress(
    existing: str,
    batch_id: str,
    start: int,
    end: int,
    source_hash: str | None,
    input_kind: str,
) -> str:
    text = normalized(existing)
    if not text.strip():
        text = "# 深度拆解进度\n"
    schema_pattern = re.compile(r"(?m)^-\s*schema_version\s*:\s*\d+\s*$")
    if schema_pattern.search(text):
        text = schema_pattern.sub("- schema_version: 2", text, count=1)
    else:
        lines = text.splitlines()
        insert_at = 1 if lines and lines[0].startswith("#") else 0
        lines.insert(insert_at, "- schema_version: 2")
        text = "\n".join(lines).rstrip() + "\n"

    marker_start = f"<!-- story-long-analyze:batch:{batch_id}:start -->"
    marker_end = f"<!-- story-long-analyze:batch:{batch_id}:end -->"
    block = (
        f"{marker_start}\n"
        f"## 已提交批次 {batch_id}\n"
        f"- chapters: {start}-{end}\n"
        f"- input_kind: {input_kind}\n"
        f"- source_sha256: {source_hash or 'not-required-existing-results'}\n"
        f"- receipt: `_analysis_cache/receipts/{batch_id}.json`\n"
        "- status: success\n"
        f"{marker_end}"
    )
    block_pattern = re.compile(re.escape(marker_start) + r".*?" + re.escape(marker_end), re.DOTALL)
    if block_pattern.search(text):
        text = block_pattern.sub(block, text, count=1)
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    return text.rstrip() + "\n"


def planned_outputs(root: Path, chapters: dict[int, str]) -> dict[Path, bytes]:
    outputs = {
        root / "章节" / f"第{chapter}章_摘要.md": body.encode("utf-8")
        for chapter, body in chapters.items()
    }
    return outputs


def commit(args: argparse.Namespace) -> dict[str, object]:
    if args.start < 1 or args.end < args.start:
        raise BatchError("invalid_range", "start/end must define a positive continuous range")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.batch_id):
        raise BatchError("invalid_batch_id", "batch id may contain only letters, digits, '_' and '-'")
    if args.input_kind == "raw-original" and not args.source_sha256:
        raise BatchError("source_hash_required", "raw-original batches require the original source SHA-256")
    if args.source_sha256 and not re.fullmatch(r"[0-9a-fA-F]{64}", args.source_sha256):
        raise BatchError("invalid_source_hash", "source SHA-256 must contain 64 hexadecimal characters")

    root = args.root.resolve()
    input_path = args.input.resolve()
    source_hash = args.source_sha256.lower() if args.source_sha256 else None
    text = normalized(input_path.read_text(encoding="utf-8-sig"))
    chapters, observations, projection_schema, compact_facts = parse_batch(
        text, args.start, args.end, args.input_kind
    )

    outputs = planned_outputs(root, chapters)
    cache_prefix = "复用提取" if args.input_kind == "existing-results" else "批次"
    cache_path = root / "_analysis_cache" / f"{cache_prefix}-{args.start}-{args.end}.md"
    cache_text = observations
    if compact_facts:
        cache_text = (
            f"# 批次 {args.batch_id}：第{args.start}-{args.end}章\n\n"
            "## 逐章紧凑事实\n\n"
            f"{compact_facts}\n"
            f"{observations}"
        )
    outputs[cache_path] = cache_text.encode("utf-8")

    receipt_path = root / "_analysis_cache" / "receipts" / f"{args.batch_id}.json"
    output_hashes = {
        path.relative_to(root).as_posix(): sha256_bytes(data)
        for path, data in sorted(outputs.items(), key=lambda item: item[0].as_posix())
    }
    receipt = {
        "schema_version": 2,
        "batch_id": args.batch_id,
        "chapter_range": [args.start, args.end],
        "input_kind": args.input_kind,
        "source_sha256": source_hash,
        "input_sha256": sha256_text(text),
        "projection_schema": projection_schema,
        "outputs": output_hashes,
        "status": "success",
    }
    receipt_bytes = (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")

    progress_path = args.progress.resolve() if args.progress else root / "_progress.md"
    existing_progress = progress_path.read_text(encoding="utf-8-sig") if progress_path.exists() else ""
    progress_bytes = update_progress(
        existing_progress, args.batch_id, args.start, args.end, source_hash, args.input_kind
    ).encode("utf-8")

    immutable_targets = {**outputs, receipt_path: receipt_bytes}
    conflicts: list[str] = []
    for path, data in immutable_targets.items():
        if path.exists() and path.read_bytes() != data and not args.replace:
            conflicts.append(path.relative_to(root).as_posix())
    if conflicts:
        raise BatchError(
            "existing_output_conflict",
            "different existing outputs require --replace: " + ", ".join(sorted(conflicts)),
        )

    changed: list[str] = []
    for path, data in outputs.items():
        if not path.exists() or path.read_bytes() != data:
            atomic_write(path, data)
            changed.append(path.relative_to(root).as_posix())
        if sha256_bytes(path.read_bytes()) != output_hashes[path.relative_to(root).as_posix()]:
            raise OSError(f"post-write verification failed: {path}")

    if not receipt_path.exists() or receipt_path.read_bytes() != receipt_bytes:
        atomic_write(receipt_path, receipt_bytes)
        changed.append(receipt_path.relative_to(root).as_posix())
    if receipt_path.read_bytes() != receipt_bytes:
        raise OSError(f"post-write verification failed: {receipt_path}")

    if not progress_path.exists() or progress_path.read_bytes() != progress_bytes:
        atomic_write(progress_path, progress_bytes)
        try:
            progress_label = progress_path.relative_to(root).as_posix()
        except ValueError:
            progress_label = str(progress_path)
        changed.append(progress_label)

    from manage_batch_checkpoint import mark_completed

    try:
        checkpoint_changed = mark_completed(
            root,
            args.batch_id,
            args.start,
            args.end,
            args.input_kind,
            source_hash,
            receipt_path.relative_to(root).as_posix(),
        )
    except ValueError as error:
        raise BatchError("checkpoint_update_failed", str(error)) from error
    if checkpoint_changed:
        changed.append("_analysis_cache/batch-checkpoints.json")

    return {
        "batch_id": args.batch_id,
        "chapters": [args.start, args.end],
        "input_kind": args.input_kind,
        "changed_files": changed,
        "receipt": receipt_path.relative_to(root).as_posix(),
        "reused": not changed,
        "status": "success",
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--input", type=Path, required=True, help="extractor Markdown output")
    result.add_argument("--root", type=Path, required=True, help="book analysis output directory")
    result.add_argument("--batch-id", required=True)
    result.add_argument("--start", type=int, required=True)
    result.add_argument("--end", type=int, required=True)
    result.add_argument("--input-kind", choices=("raw-original", "existing-results"), default="raw-original")
    result.add_argument("--source-sha256", help="raw original SHA-256; optional for existing-results")
    result.add_argument("--progress", type=Path, help="override _progress.md path")
    result.add_argument("--replace", action="store_true", help="replace different existing batch outputs")
    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        payload = commit(parser().parse_args())
    except BatchError as error:
        print(json.dumps({"error": error.code, "detail": error.detail}, ensure_ascii=False))
        return 2
    except (OSError, UnicodeError) as error:
        print(json.dumps({"error": "io_error", "detail": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
