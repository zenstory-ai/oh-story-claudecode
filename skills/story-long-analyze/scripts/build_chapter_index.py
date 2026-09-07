#!/usr/bin/env python3
"""Build the schema-v4 checkpoint and mechanical chapter index once per source hash."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 4
CONTRACT_VERSION = "5.0"
CSV_COLUMNS = ("chapter", "title", "source_locator", "char_count", "status")
NUMBER_CHARS = "〇零一二三四五六七八九十百千万两0-9"
HEADING_RE = re.compile(
    r"^\s*(?:第(?P<cn>[〇零一二三四五六七八九十百千万两0-9]+)章"
    r"(?:\s*[-—:：、.．]\s*\S.*|\s+\S.*)?|"
    r"Chapter\s+(?P<en>[0-9]+)\b(?:\s*[-—:：.．]\s*\S.*|\s+\S.*)?)\s*$",
    re.IGNORECASE,
)
COMBINED_RE = re.compile(
    r"^\s*第(?P<volume>[〇零一二三四五六七八九十百千万两0-9]+)卷\s*"
    r"第(?P<chapter>[〇零一二三四五六七八九十百千万两0-9]+)章"
    r"(?:\s*[-—:：、.．]\s*\S.*|\s+\S.*)?\s*$"
)
VOLUME_RE = re.compile(r"^\s*第(?P<number>[〇零一二三四五六七八九十百千万两0-9]+)卷(?:\s+\S.*)?\s*$")
STRIP_HEADING_RE = re.compile(
    r"^\s*(?:第[〇零一二三四五六七八九十百千万两0-9]+卷\s*)?"
    r"(?:第[〇零一二三四五六七八九十百千万两0-9]+章|Chapter\s+[0-9]+)"
    r"\s*[-—:：、.．]?\s*",
    re.IGNORECASE,
)
DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def decode_source(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("source_encoding_unsupported")


def parse_number(raw: str) -> int:
    if raw.isdigit():
        value = int(raw)
    elif not any(char in UNITS for char in raw):
        try:
            value = int("".join(str(DIGITS[char]) for char in raw))
        except (KeyError, ValueError) as exc:
            raise ValueError(f"chapter_number_invalid:{raw}") from exc
    else:
        total = 0
        section = 0
        number = 0
        for char in raw:
            if char in DIGITS:
                number = DIGITS[char]
            elif char in UNITS:
                unit = UNITS[char]
                if unit == 10000:
                    section = (section + number) * unit
                    total += section
                    section = 0
                else:
                    section += (number or 1) * unit
                number = 0
            else:
                raise ValueError(f"chapter_number_invalid:{raw}")
        value = total + section + number
    if value < 1:
        raise ValueError("chapter_number_must_be_positive")
    return value


def heading_candidates(lines: list[str]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    volume_key = "__root__"
    volume_title = ""
    for index, line in enumerate(lines):
        combined = COMBINED_RE.match(line)
        if combined:
            volume_raw = combined.group("volume")
            volume_key = f"volume:{volume_raw}:{index + 1}"
            volume_title = f"第{volume_raw}卷"
            candidates.append(
                {
                    "line": index,
                    "heading": line.strip(),
                    "raw_number": parse_number(combined.group("chapter")),
                    "volume_key": volume_key,
                    "volume_title": volume_title,
                }
            )
            continue
        volume = VOLUME_RE.match(line)
        if volume:
            volume_key = f"volume:{volume.group('number')}:{index + 1}"
            volume_title = line.strip()
            continue
        chapter = HEADING_RE.match(line)
        if chapter:
            candidates.append(
                {
                    "line": index,
                    "heading": line.strip(),
                    "raw_number": parse_number(chapter.group("cn") or chapter.group("en")),
                    "volume_key": volume_key,
                    "volume_title": volume_title,
                }
            )
    return candidates


def drop_leading_toc(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop an initial dense heading run when a later body heading run exists."""
    if len(candidates) < 6:
        return candidates
    dense_end = 0
    for idx in range(1, len(candidates)):
        gap = candidates[idx]["line"] - candidates[idx - 1]["line"]
        if gap <= 3 and candidates[idx]["line"] <= 800:
            dense_end = idx
            continue
        break
    dense_count = dense_end + 1
    if dense_count >= 3 and dense_end + 1 < len(candidates):
        next_gap = candidates[dense_end + 1]["line"] - candidates[dense_end]["line"]
        if next_gap > 3:
            return candidates[dense_end + 1 :]
    return candidates


def validate_numbering(candidates: list[dict[str, Any]]) -> None:
    previous_raw: int | None = None
    previous_volume: str | None = None
    for position, candidate in enumerate(candidates, start=1):
        raw_number = candidate["raw_number"]
        volume_key = candidate["volume_key"]
        if previous_raw is None:
            if raw_number != 1:
                raise ValueError(f"chapter_number_gap:expected=1:actual={raw_number}:position={position}")
        elif volume_key == previous_volume:
            expected = previous_raw + 1
            if raw_number != expected:
                kind = "chapter_number_duplicate" if raw_number <= previous_raw else "chapter_number_gap"
                raise ValueError(f"{kind}:expected={expected}:actual={raw_number}:position={position}")
        elif raw_number not in (1, previous_raw + 1):
            raise ValueError(
                f"volume_chapter_number_invalid:expected=1_or_{previous_raw + 1}:actual={raw_number}:position={position}"
            )
        previous_raw = raw_number
        previous_volume = volume_key


def clean_title(candidate: dict[str, Any]) -> str:
    title = STRIP_HEADING_RE.sub("", candidate["heading"]).strip()
    base = title or f"第{candidate['raw_number']}章"
    return f"{candidate['volume_title']}·{base}" if candidate["volume_title"] else base


def build_boundaries(text: str, locator_path: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    candidates = drop_leading_toc(heading_candidates(lines))
    if not candidates:
        raise ValueError("chapter_heading_not_found")
    validate_numbering(candidates)
    boundaries: list[dict[str, Any]] = []
    for offset, candidate in enumerate(candidates):
        start_zero = candidate["line"]
        end_zero = candidates[offset + 1]["line"] - 1 if offset + 1 < len(candidates) else len(lines) - 1
        if end_zero < start_zero:
            raise ValueError(f"chapter_boundary_invalid:position={offset + 1}")
        chapter = offset + 1
        chapter_text = "\n".join(lines[start_zero : end_zero + 1])
        boundaries.append(
            {
                "chapter": chapter,
                "source_chapter": candidate["raw_number"],
                "volume": candidate["volume_title"],
                "title": clean_title(candidate),
                "start_line": start_zero + 1,
                "end_line": end_zero + 1,
                "char_count": len(re.sub(r"\s+", "", chapter_text)),
                "source_locator": f"{locator_path}:L{start_zero + 1}-L{end_zero + 1}",
                "status": "ok",
            }
        )
    return boundaries


def csv_payload(boundaries: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for boundary in boundaries:
        writer.writerow({column: boundary[column] for column in CSV_COLUMNS})
    return buffer.getvalue().encode("utf-8-sig")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def make_snapshot(source_hash: str, boundary_hash: str, boundaries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_sha256": source_hash,
        "boundary_sha256": boundary_hash,
        "chapter_boundaries": boundaries,
        "aliases": {},
        "block_progress": {},
        "unresolved_information": [],
        "evidence_locators": [],
    }


def snapshot_is_current(snapshot: dict[str, Any], source_hash: str, boundary_hash: str, boundaries: list[dict[str, Any]]) -> bool:
    return (
        snapshot.get("schema_version") == SCHEMA_VERSION
        and snapshot.get("source_sha256") == source_hash
        and snapshot.get("boundary_sha256") == boundary_hash
        and snapshot.get("chapter_boundaries") == boundaries
    )


def base_progress(source_hash: str, boundary_hash: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_version": CONTRACT_VERSION,
        "source_sha256": source_hash,
        "boundary_sha256": boundary_hash,
        "current_stage": "stage_0_boundaries_completed",
        "final_status": "pending",
        "last_committed_batch": "chapter_boundaries",
        "completed_ranges": [],
        "pending_ranges": ["stage_1_golden_chapters"],
        "artifact_checksums": {},
        "failed_ranges": [],
        "retry_reasons": [],
        "next_action": "stage_1_golden_chapters",
    }


def run_boundaries(
    args: argparse.Namespace,
    source_hash: str,
    boundary_hash: str,
    boundaries: list[dict[str, Any]],
) -> int:
    snapshot = make_snapshot(source_hash, boundary_hash, boundaries)
    snapshot_data = json_bytes(snapshot)
    old_snapshot = read_json(args.snapshot)
    old_progress = read_json(args.progress)
    same = snapshot_is_current(old_snapshot, source_hash, boundary_hash, boundaries)
    if same and old_progress.get("source_sha256") == source_hash and old_progress.get("boundary_sha256") == boundary_hash:
        print(json.dumps({"ok": True, "reused": True, "stage": 0, "chapters": len(boundaries)}, ensure_ascii=False))
        return 0
    if (args.snapshot.exists() or args.progress.exists()) and not args.rebuild:
        print(json.dumps({"ok": False, "error": "existing_boundaries_incompatible"}, ensure_ascii=False))
        return 2
    progress = base_progress(source_hash, boundary_hash)
    progress["completed_ranges"] = [f"1-{len(boundaries)}:boundaries"]
    progress["artifact_checksums"]["_state_snapshot.json"] = sha256_bytes(snapshot_data)
    atomic_write(args.snapshot, snapshot_data)
    atomic_write(args.progress, json_bytes(progress))
    print(json.dumps({"ok": True, "reused": False, "stage": 0, "chapters": len(boundaries)}, ensure_ascii=False))
    return 0


def run_index(
    args: argparse.Namespace,
    source_hash: str,
    boundary_hash: str,
    boundaries: list[dict[str, Any]],
) -> int:
    if args.output is None:
        raise ValueError("output_required_for_index_mode")
    old_snapshot = read_json(args.snapshot)
    old_progress = read_json(args.progress)
    same_snapshot = snapshot_is_current(old_snapshot, source_hash, boundary_hash, boundaries)
    if old_snapshot and not same_snapshot and not args.rebuild:
        print(json.dumps({"ok": False, "error": "existing_boundaries_incompatible"}, ensure_ascii=False))
        return 2

    csv_data = csv_payload(boundaries)
    csv_hash = sha256_bytes(csv_data)
    output_bytes = args.output.read_bytes() if args.output.is_file() else None
    registered_hash = (old_progress.get("artifact_checksums") or {}).get("chapter_index.csv")
    progress_same = (
        old_progress.get("schema_version") == SCHEMA_VERSION
        and old_progress.get("source_sha256") == source_hash
        and old_progress.get("boundary_sha256") == boundary_hash
    )
    if output_bytes == csv_data and progress_same and registered_hash == csv_hash:
        print(json.dumps({"ok": True, "reused": True, "stage": 2, "chapters": len(boundaries)}, ensure_ascii=False))
        return 0
    if output_bytes is not None and output_bytes != csv_data and not args.rebuild:
        print(json.dumps({"ok": False, "error": "existing_index_incompatible"}, ensure_ascii=False))
        return 2
    if output_bytes == csv_data and registered_hash not in (None, csv_hash) and not args.rebuild:
        print(json.dumps({"ok": False, "error": "artifact_checksum_mismatch"}, ensure_ascii=False))
        return 2

    if same_snapshot and progress_same:
        progress = dict(old_progress)
    else:
        progress = base_progress(source_hash, boundary_hash)
    completed = [item for item in progress.get("completed_ranges", []) if not str(item).endswith(":index")]
    completed.append(f"1-{len(boundaries)}:index")
    pending = [item for item in progress.get("pending_ranges", []) if item not in {"stage_2_index", "chapter_index"}]
    if "structure_blocks" not in pending:
        pending.append("structure_blocks")
    checksums = dict(progress.get("artifact_checksums") or {})
    checksums["chapter_index.csv"] = csv_hash
    progress.update(
        {
            "schema_version": SCHEMA_VERSION,
            "contract_version": CONTRACT_VERSION,
            "source_sha256": source_hash,
            "boundary_sha256": boundary_hash,
            "current_stage": "stage_2_index_completed",
            "final_status": "pending",
            "last_committed_batch": "chapter_index",
            "completed_ranges": completed,
            "pending_ranges": pending,
            "artifact_checksums": checksums,
            "failed_ranges": list(progress.get("failed_ranges") or []),
            "retry_reasons": list(progress.get("retry_reasons") or []),
            "next_action": "stage_3_structure_blocks",
        }
    )
    if not same_snapshot:
        snapshot_data = json_bytes(make_snapshot(source_hash, boundary_hash, boundaries))
        atomic_write(args.snapshot, snapshot_data)
        progress["artifact_checksums"]["_state_snapshot.json"] = sha256_bytes(snapshot_data)
    if output_bytes != csv_data:
        atomic_write(args.output, csv_data)
    atomic_write(args.progress, json_bytes(progress))
    print(
        json.dumps(
            {
                "ok": True,
                "reused": output_bytes == csv_data,
                "adopted": output_bytes == csv_data,
                "stage": 2,
                "chapters": len(boundaries),
            },
            ensure_ascii=False,
        )
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("boundaries", "index"), default="index")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--progress", required=True, type=Path)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--locator-path")
    parser.add_argument("--rebuild", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        raw = args.source.read_bytes()
        source_hash = sha256_bytes(raw)
        text = decode_source(raw)
        locator_path = (args.locator_path or f"原文/{args.source.name}").replace("\\", "/")
        if not locator_path.startswith("原文/") or ".." in locator_path.split("/"):
            raise ValueError("locator_path_must_stay_under_original")
        boundaries = build_boundaries(text, locator_path)
        boundary_hash = sha256_bytes(json_bytes(boundaries))
        if args.mode == "boundaries":
            return run_boundaries(args, source_hash, boundary_hash, boundaries)
        return run_index(args, source_hash, boundary_hash, boundaries)
    except (OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
