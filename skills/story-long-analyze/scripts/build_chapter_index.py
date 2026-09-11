#!/usr/bin/env python3
"""Build and reuse a mechanical chapter index for story-long-analyze.

The index records source boundaries only.  It deliberately contains no plot,
character, emotion, or other model-derived fields.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import statistics
import tempfile
from pathlib import Path
from typing import Any


PARSER_VERSION = "2"
CSV_COLUMNS = (
    "chapter",
    "source_chapter",
    "volume",
    "title",
    "start_line",
    "end_line",
    "char_count",
    "source_locator",
    "status",
    "source_sha256",
    "parser_version",
)
NUMBER = r"〇零一二三四五六七八九十百千万两0-9"
VOLUME_RE = re.compile(rf"^\s*第(?P<number>[{NUMBER}]+)卷(?P<title>.*)$")
COMBINED_RE = re.compile(
    rf"^\s*第(?P<volume>[{NUMBER}]+)卷\s*第(?P<chapter>[{NUMBER}]+)章(?P<title>.*)$"
)
CHAPTER_RE = re.compile(rf"^\s*第(?P<number>[{NUMBER}]+)章(?P<title>.*)$")
ENGLISH_RE = re.compile(r"^\s*Chapter\s+(?P<number>[0-9]+)\b(?P<title>.*)$", re.IGNORECASE)
NUMERIC_RE = re.compile(r"^\s*(?P<number>[0-9]+)[.．、]\s*(?P<title>.*)$")
TITLE_PREFIX_RE = re.compile(r"^[\s\-—:：、.．]+")
META_START = "<!-- story-long-analyze:chapter-index:start -->"
META_END = "<!-- story-long-analyze:chapter-index:end -->"
DIGITS = {
    "〇": 0,
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
    elif not any(character in UNITS for character in raw):
        try:
            value = int("".join(str(DIGITS[character]) for character in raw))
        except (KeyError, ValueError) as exc:
            raise ValueError(f"chapter_number_invalid:{raw}") from exc
    else:
        total = 0
        section = 0
        number = 0
        for character in raw:
            if character in DIGITS:
                number = DIGITS[character]
            elif character in UNITS:
                unit = UNITS[character]
                if unit == 10000:
                    total += (section + number) * unit
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


def clean_title(raw: str, fallback: str) -> str:
    title = TITLE_PREFIX_RE.sub("", raw).strip()
    return title or fallback


def heading_candidates(lines: list[str]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    numeric_candidates: list[dict[str, Any]] = []
    volume_number: int | None = None
    volume_title = ""
    for line_number, line in enumerate(lines, start=1):
        combined = COMBINED_RE.match(line)
        if combined:
            raw_volume = combined.group("volume")
            volume_number = parse_number(raw_volume)
            volume_title = f"第{raw_volume}卷"
            raw_chapter = combined.group("chapter")
            candidates.append(
                {
                    "line": line_number,
                    "heading_kind": "combined",
                    "source_chapter": parse_number(raw_chapter),
                    "volume_number": volume_number,
                    "volume": volume_title,
                    "title": clean_title(combined.group("title"), f"第{raw_chapter}章"),
                }
            )
            continue

        volume = VOLUME_RE.match(line)
        if volume and not CHAPTER_RE.match(line):
            raw_volume = volume.group("number")
            volume_number = parse_number(raw_volume)
            volume_title = clean_title(volume.group("title"), f"第{raw_volume}卷")
            continue

        chapter = CHAPTER_RE.match(line)
        english = ENGLISH_RE.match(line)
        match = chapter or english
        if not match:
            numeric = NUMERIC_RE.match(line)
            if numeric:
                raw_chapter = numeric.group("number")
                numeric_candidates.append(
                    {
                        "line": line_number,
                        "heading_kind": "numeric",
                        "raw_chapter": raw_chapter,
                        "volume_number": volume_number,
                        "volume": volume_title,
                        "title": clean_title(numeric.group("title"), f"第{raw_chapter}章"),
                    }
                )
            continue
        raw_chapter = match.group("number")
        candidates.append(
            {
                "line": line_number,
                "heading_kind": "chapter" if chapter else "english",
                "source_chapter": parse_number(raw_chapter),
                "volume_number": volume_number,
                "volume": volume_title,
                "title": clean_title(match.group("title"), f"第{raw_chapter}章"),
            }
        )
    # Explicit 第X章/Chapter X headings win over numbered prose lists.  Pure
    # numeric headings are accepted only when the source has no explicit form.
    if candidates:
        return candidates
    for candidate in numeric_candidates:
        candidate["source_chapter"] = parse_number(candidate.pop("raw_chapter"))
    return numeric_candidates


def identity(candidate: dict[str, Any]) -> tuple[int | None, int]:
    return candidate["volume_number"], candidate["source_chapter"]


def drop_leading_toc(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop a dense leading TOC only when its chapter sequence repeats later.

    Requiring a repeated sequence prevents consecutive short real chapters from
    being mistaken for a table of contents.
    """
    if len(candidates) < 6:
        return candidates
    max_prefix = min(len(candidates) // 2, 500)
    for prefix_count in range(max_prefix, 2, -1):
        prefix = candidates[:prefix_count]
        if prefix[0]["line"] > 200:
            continue
        prefix_gaps = [prefix[index]["line"] - prefix[index - 1]["line"] for index in range(1, len(prefix))]
        if not prefix_gaps or statistics.median(prefix_gaps) > 3:
            continue
        signature_length = min(8, prefix_count)
        signature = [identity(item) for item in prefix[:signature_length]]
        for body_start in range(prefix_count, len(candidates) - signature_length + 1):
            body_signature = [identity(item) for item in candidates[body_start : body_start + signature_length]]
            if signature != body_signature:
                continue
            if candidates[body_start]["line"] - prefix[-1]["line"] <= 3:
                continue
            return candidates[body_start:]
    return candidates


def duplicate_title_key(title: str) -> str:
    """Remove an export-only trailing note before comparing numeric headings."""
    return re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", title).strip()


def drop_adjacent_duplicate_headings(
    candidates: list[dict[str, Any]], lines: list[str]
) -> list[dict[str, Any]]:
    """Keep the decorated first copy of an immediately repeated numeric heading.

    Some exports print ``30.标题（作者话）`` and then repeat ``30.标题`` after
    one blank line.  Restricting this repair to numeric headings, whitespace-only
    separators, and equivalent titles keeps genuine duplicate 第X章/卷章
    headings subject to strict numbering validation.
    """
    deduplicated: list[dict[str, Any]] = []
    for candidate in candidates:
        if deduplicated:
            previous = deduplicated[-1]
            gap = candidate["line"] - previous["line"]
            between = lines[previous["line"] : candidate["line"] - 1]
            if (
                previous.get("heading_kind") == "numeric"
                and candidate.get("heading_kind") == "numeric"
                and identity(candidate) == identity(previous)
                and 1 <= gap <= 3
                and all(not line.strip() for line in between)
                and duplicate_title_key(candidate["title"]) == duplicate_title_key(previous["title"])
            ):
                continue
        deduplicated.append(candidate)
    return deduplicated


def validate_numbering(candidates: list[dict[str, Any]]) -> None:
    previous: dict[str, Any] | None = None
    for position, candidate in enumerate(candidates, start=1):
        number = candidate["source_chapter"]
        if previous is None:
            if number != 1:
                raise ValueError(f"chapter_number_gap:expected=1:actual={number}:position={position}")
        elif candidate["volume_number"] == previous["volume_number"]:
            expected = previous["source_chapter"] + 1
            if number != expected:
                kind = "chapter_number_duplicate" if number <= previous["source_chapter"] else "chapter_number_gap"
                raise ValueError(f"{kind}:expected={expected}:actual={number}:position={position}")
        elif number not in (1, previous["source_chapter"] + 1):
            expected = previous["source_chapter"] + 1
            raise ValueError(f"volume_chapter_number_invalid:expected=1_or_{expected}:actual={number}:position={position}")
        previous = candidate


def build_boundaries(text: str, locator_path: str, source_hash: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    candidates = drop_adjacent_duplicate_headings(drop_leading_toc(heading_candidates(lines)), lines)
    if not candidates:
        raise ValueError("chapter_heading_not_found")
    validate_numbering(candidates)
    rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        start_line = candidate["line"]
        end_line = candidates[index + 1]["line"] - 1 if index + 1 < len(candidates) else len(lines)
        if end_line < start_line:
            raise ValueError(f"chapter_boundary_invalid:position={index + 1}")
        body = "\n".join(lines[start_line:end_line])
        char_count = len(re.sub(r"\s+", "", body))
        rows.append(
            {
                "chapter": index + 1,
                "source_chapter": candidate["source_chapter"],
                "volume": candidate["volume"],
                "title": candidate["title"],
                "start_line": start_line,
                "end_line": end_line,
                "char_count": char_count,
                "source_locator": f"{locator_path}:L{start_line}-L{end_line}",
                "status": "ok" if char_count else "empty",
                "source_sha256": source_hash,
                "parser_version": PARSER_VERSION,
            }
        )
    return rows


def csv_payload(rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row[column] for column in CSV_COLUMNS})
    return buffer.getvalue().encode("utf-8-sig")


def reusable_index(path: Path, source_hash: str, locator_path: str) -> tuple[bytes, list[dict[str, Any]]] | None:
    """Return a validated same-source index without parsing chapter headings."""
    try:
        data = path.read_bytes()
        with io.StringIO(data.decode("utf-8-sig"), newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != CSV_COLUMNS:
                return None
            rows: list[dict[str, Any]] = list(reader)
    except (OSError, UnicodeError, csv.Error):
        return None
    if not rows:
        return None
    for expected, row in enumerate(rows, start=1):
        try:
            valid_numbers = (
                int(row["chapter"]) == expected
                and int(row["source_chapter"]) >= 1
                and int(row["start_line"]) >= 1
                and int(row["end_line"]) >= int(row["start_line"])
                and int(row["char_count"]) >= 0
            )
        except (KeyError, TypeError, ValueError):
            return None
        if not valid_numbers:
            return None
        if row.get("source_sha256") != source_hash or row.get("parser_version") != PARSER_VERSION:
            return None
        if row.get("status") not in {"ok", "empty"}:
            return None
        if not str(row.get("source_locator", "")).startswith(f"{locator_path}:L"):
            return None
    return data, rows


def metadata_block(source_hash: str, boundary_hash: str, rows: list[dict[str, Any]]) -> str:
    boundary_lines = [
        "## 章节边界（`chapter_index.csv` 的兼容投影）",
        "| 章号 | 标题 | 起始行 | 字数 |",
        "|---|---|---|---|",
    ]
    boundary_lines.extend(
        f"| {row['chapter']} | {str(row['title']).replace('|', '&#124;')} | {row['start_line']} | {row['char_count']} |"
        for row in rows
    )
    return (
        f"{META_START}\n"
        "## 机械章节索引\n"
        f"- parser_version: {PARSER_VERSION}\n"
        f"- source_sha256: {source_hash}\n"
        f"- boundary_sha256: {boundary_hash}\n"
        f"- chapter_count: {len(rows)}\n"
        f"- empty_chapter_count: {sum(row['status'] == 'empty' for row in rows)}\n"
        "- index_status: complete\n"
        + "\n".join(boundary_lines)
        + "\n"
        f"{META_END}\n"
    )


def update_progress(progress: Path, block: str) -> bytes:
    if progress.exists():
        original = progress.read_text(encoding="utf-8")
    else:
        original = "# 深度拆解进度\n- 最终状态：pending\n- schema_version: 2\n"
    pattern = re.compile(re.escape(META_START) + r".*?" + re.escape(META_END) + r"\n?", re.DOTALL)
    if pattern.search(original):
        updated = pattern.sub(block, original)
    else:
        updated = original.rstrip() + "\n\n" + block
    return updated.encode("utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--progress", type=Path)
    parser.add_argument("--locator-path")
    parser.add_argument("--rebuild", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        raw = args.source.read_bytes()
        source_hash = sha256(raw)
        locator_path = (args.locator_path or f"原文/{args.source.name}").replace("\\", "/")
        if not locator_path.startswith("原文/") or ".." in locator_path.split("/"):
            raise ValueError("locator_path_must_stay_under_original")

        progress_existing = args.progress.read_bytes() if args.progress and args.progress.is_file() else None
        if args.output.is_file() and not args.rebuild:
            reusable = reusable_index(args.output, source_hash, locator_path)
            if reusable is None:
                print(json.dumps({"ok": False, "error": "existing_index_incompatible"}, ensure_ascii=False))
                return 2
            existing, rows = reusable
            block = metadata_block(source_hash, sha256(existing), rows)
            progress_data = update_progress(args.progress, block) if args.progress else None
            repaired_progress = progress_data is not None and progress_existing != progress_data
            if repaired_progress and args.progress:
                atomic_write(args.progress, progress_data)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "reused": True,
                        "parsed_source": False,
                        "repaired_progress": repaired_progress,
                        "chapters": len(rows),
                    },
                    ensure_ascii=False,
                )
            )
            return 0

        rows = build_boundaries(decode_source(raw), locator_path, source_hash)
        data = csv_payload(rows)
        boundary_hash = sha256(data)
        block = metadata_block(source_hash, boundary_hash, rows)
        progress_data = update_progress(args.progress, block) if args.progress else None

        existing = args.output.read_bytes() if args.output.is_file() else None
        if existing is not None and existing != data and not args.rebuild:
            print(json.dumps({"ok": False, "error": "existing_index_incompatible"}, ensure_ascii=False))
            return 2
        if progress_existing and META_START in progress_existing.decode("utf-8", errors="ignore") and progress_existing != progress_data and not args.rebuild:
            print(json.dumps({"ok": False, "error": "existing_index_metadata_incompatible"}, ensure_ascii=False))
            return 2

        atomic_write(args.output, data)
        if args.progress and progress_data is not None:
            atomic_write(args.progress, progress_data)
        print(
            json.dumps(
                {
                    "ok": True,
                    "reused": False,
                    "parsed_source": True,
                    "chapters": len(rows),
                    "empty_chapters": sum(row["status"] == "empty" for row in rows),
                    "source_sha256": source_hash,
                    "parser_version": PARSER_VERSION,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
