#!/usr/bin/env python3
"""Build the mechanical, content-addressed chapter index.

The CSV is the only source for chapter boundaries. This script never writes
analysis progress and never interprets story semantics.
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
from typing import Any, Dict, List, Optional, Sequence, Tuple


PARSER_VERSION = "3"
CSV_COLUMNS = (
    "chapter", "source_chapter", "volume", "title", "start_line", "end_line",
    "char_count", "source_locator", "status", "chapter_sha256", "source_sha256",
    "parser_version",
)
NUMBER = r"〇零一二三四五六七八九十百千万两0-9"
VOLUME_RE = re.compile(rf"^\s*第(?P<number>[{NUMBER}]+)卷(?P<title>.*)$")
COMBINED_RE = re.compile(rf"^\s*第(?P<volume>[{NUMBER}]+)卷\s*第(?P<chapter>[{NUMBER}]+)章(?P<title>.*)$")
CHAPTER_RE = re.compile(rf"^\s*第(?P<number>[{NUMBER}]+)章(?P<title>.*)$")
ENGLISH_RE = re.compile(r"^\s*Chapter\s+(?P<number>[0-9]+)\b(?P<title>.*)$", re.IGNORECASE)
NUMERIC_RE = re.compile(r"^\s*(?P<number>[0-9]+)[.．、]\s*(?P<title>.*)$")
SPECIAL_RE = re.compile(
    rf"^\s*(?P<label>楔子|序章|引子|前言|后记|尾声|番外(?:[{NUMBER}]+)?)"
    r"(?:[\s:：\-—]+(?P<title>.*))?\s*$"
)
LEGACY_CHAPTER_FILE_RE = re.compile(r"^第0*(\d+)章_(?:摘要|深度拆解)\.md$")
TITLE_PREFIX_RE = re.compile(r"^[\s\-—:：、.．]+")
DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
          "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def decode_source(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("source_encoding_unsupported")


def physical_lines(text: str) -> List[str]:
    """Split on LF only so CSV line numbers agree with grep -n and editors."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def parse_number(raw: str) -> int:
    if raw.isdigit():
        return int(raw)
    if not any(character in UNITS for character in raw):
        try:
            return int("".join(str(DIGITS[character]) for character in raw))
        except (KeyError, ValueError) as exc:
            raise ValueError("chapter_number_invalid:%s" % raw) from exc
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
            raise ValueError("chapter_number_invalid:%s" % raw)
    return total + section + number


def clean_title(raw: str, fallback: str) -> str:
    title = TITLE_PREFIX_RE.sub("", raw or "").strip()
    return title or fallback


def heading_candidates(lines: Sequence[str]) -> List[Dict[str, Any]]:
    explicit = []  # type: List[Dict[str, Any]]
    numeric_candidates = []  # type: List[Dict[str, Any]]
    volume_number = None  # type: Optional[int]
    volume_title = ""
    for line_number, line in enumerate(lines, start=1):
        combined = COMBINED_RE.match(line)
        if combined:
            raw_volume = combined.group("volume")
            raw_chapter = combined.group("chapter")
            volume_number = parse_number(raw_volume)
            volume_title = "第%s卷" % raw_volume
            explicit.append({
                "line": line_number, "heading_kind": "combined",
                "source_chapter": str(parse_number(raw_chapter)),
                "number_value": parse_number(raw_chapter), "volume_number": volume_number,
                "volume": volume_title,
                "title": clean_title(combined.group("title"), "第%s章" % raw_chapter),
            })
            continue
        volume = VOLUME_RE.match(line)
        if volume and not CHAPTER_RE.match(line):
            raw_volume = volume.group("number")
            volume_number = parse_number(raw_volume)
            volume_title = clean_title(volume.group("title"), "第%s卷" % raw_volume)
            continue
        chapter = CHAPTER_RE.match(line)
        english = ENGLISH_RE.match(line)
        match = chapter or english
        if match:
            raw_chapter = match.group("number")
            value = parse_number(raw_chapter)
            explicit.append({
                "line": line_number, "heading_kind": "chapter" if chapter else "english",
                "source_chapter": str(value), "number_value": value,
                "volume_number": volume_number, "volume": volume_title,
                "title": clean_title(match.group("title"), "第%s章" % raw_chapter),
            })
            continue
        special = SPECIAL_RE.match(line)
        if special:
            label = special.group("label")
            explicit.append({
                "line": line_number, "heading_kind": "special", "source_chapter": label,
                "number_value": None, "volume_number": volume_number, "volume": volume_title,
                "title": clean_title(special.group("title") or "", label),
            })
            continue
        numeric = NUMERIC_RE.match(line)
        if numeric:
            raw_chapter = numeric.group("number")
            value = parse_number(raw_chapter)
            numeric_candidates.append({
                "line": line_number, "heading_kind": "numeric", "source_chapter": str(value),
                "number_value": value, "volume_number": volume_number, "volume": volume_title,
                "title": clean_title(numeric.group("title"), "第%s章" % raw_chapter),
            })
    return explicit if explicit else numeric_candidates


def identity(candidate: Dict[str, Any]) -> Tuple[Optional[int], str]:
    return candidate.get("volume_number"), str(candidate["source_chapter"])


def drop_leading_toc(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if len(candidates) < 6:
        return candidates
    max_prefix = min(len(candidates) // 2, 500)
    for prefix_count in range(max_prefix, 2, -1):
        prefix = candidates[:prefix_count]
        if prefix[0]["line"] > 200:
            continue
        gaps = [prefix[index]["line"] - prefix[index - 1]["line"] for index in range(1, len(prefix))]
        if not gaps or statistics.median(gaps) > 3:
            continue
        signature_length = min(8, prefix_count)
        signature = [identity(item) for item in prefix[:signature_length]]
        for body_start in range(prefix_count, len(candidates) - signature_length + 1):
            body_signature = [identity(item) for item in candidates[body_start:body_start + signature_length]]
            if signature == body_signature and candidates[body_start]["line"] - prefix[-1]["line"] > 3:
                return candidates[body_start:]
    return candidates


def duplicate_title_key(title: str) -> str:
    return re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", title).strip()


def drop_adjacent_duplicate_headings(candidates: List[Dict[str, Any]], lines: Sequence[str]) -> List[Dict[str, Any]]:
    deduplicated = []  # type: List[Dict[str, Any]]
    for candidate in candidates:
        if deduplicated:
            previous = deduplicated[-1]
            gap = candidate["line"] - previous["line"]
            between = lines[previous["line"]:candidate["line"] - 1]
            if (previous.get("heading_kind") == "numeric"
                    and candidate.get("heading_kind") == "numeric"
                    and identity(candidate) == identity(previous) and 1 <= gap <= 3
                    and all(not line.strip() for line in between)
                    and duplicate_title_key(candidate["title"]) == duplicate_title_key(previous["title"])):
                continue
        deduplicated.append(candidate)
    return deduplicated


def validate_numbering(candidates: Sequence[Dict[str, Any]]) -> None:
    previous = None  # type: Optional[Dict[str, Any]]
    for position, candidate in enumerate(candidates, start=1):
        number = candidate.get("number_value")
        # 第0章 behaves like a prologue. The first positive chapter may start at
        # any number so excerpts such as 第五章 can be indexed.
        if number is None or number == 0:
            continue
        if previous is None:
            previous = candidate
            continue
        if candidate["volume_number"] == previous["volume_number"]:
            expected = previous["number_value"] + 1
            if number != expected:
                kind = "chapter_number_duplicate" if number <= previous["number_value"] else "chapter_number_gap"
                raise ValueError("%s:expected=%s:actual=%s:position=%s" % (kind, expected, number, position))
        else:
            expected = previous["number_value"] + 1
            if number not in (1, expected):
                raise ValueError("volume_chapter_number_invalid:expected=1_or_%s:actual=%s:position=%s" % (expected, number, position))
        previous = candidate


def normalized_chapter_text(lines: Sequence[str], start_line: int, end_line: int) -> str:
    selected = list(lines[start_line - 1:end_line])
    while selected and not selected[-1].strip():
        selected.pop()
    return "\n".join(selected)


def build_boundaries(text: str, locator_path: str, source_hash: str) -> List[Dict[str, Any]]:
    lines = physical_lines(text)
    candidates = drop_adjacent_duplicate_headings(drop_leading_toc(heading_candidates(lines)), lines)
    if not candidates:
        raise ValueError("chapter_heading_not_found")
    validate_numbering(candidates)
    rows = []  # type: List[Dict[str, Any]]
    for index, candidate in enumerate(candidates):
        start_line = candidate["line"]
        end_line = candidates[index + 1]["line"] - 1 if index + 1 < len(candidates) else len(lines)
        if end_line < start_line:
            raise ValueError("chapter_boundary_invalid:position=%s" % (index + 1))
        body = "\n".join(lines[start_line:end_line])
        char_count = len(re.sub(r"\s+", "", body))
        chapter_text = normalized_chapter_text(lines, start_line, end_line)
        rows.append({
            "chapter": index + 1, "source_chapter": candidate["source_chapter"],
            "volume": candidate["volume"], "title": candidate["title"],
            "start_line": start_line, "end_line": end_line, "char_count": char_count,
            "source_locator": "%s:L%s-L%s" % (locator_path, start_line, end_line),
            "status": "ok" if char_count else "empty",
            "chapter_sha256": sha256(normalized_chapter_text(lines, start_line, end_line).encode("utf-8")),
            "source_sha256": source_hash, "parser_version": PARSER_VERSION,
        })
    return rows


def csv_payload(rows: Sequence[Dict[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row[column] for column in CSV_COLUMNS})
    return buffer.getvalue().encode("utf-8-sig")


def read_existing(path: Path) -> Tuple[bytes, List[Dict[str, str]]]:
    data = path.read_bytes()
    with io.StringIO(data.decode("utf-8-sig"), newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fields = tuple(reader.fieldnames or ())
    if not rows or "chapter" not in fields or "source_chapter" not in fields:
        raise ValueError("existing_index_invalid")
    return data, rows


def reusable_index(path: Path, source_hash: str, locator_path: str) -> Optional[Tuple[bytes, List[Dict[str, str]]]]:
    try:
        data, rows = read_existing(path)
        with io.StringIO(data.decode("utf-8-sig"), newline="") as handle:
            fields = tuple(csv.DictReader(handle).fieldnames or ())
    except (OSError, UnicodeError, csv.Error, ValueError):
        return None
    if fields != CSV_COLUMNS:
        return None
    for expected, row in enumerate(rows, start=1):
        try:
            valid_numbers = (int(row["chapter"]) == expected and int(row["start_line"]) >= 1
                             and int(row["end_line"]) >= int(row["start_line"])
                             and int(row["char_count"]) >= 0)
        except (KeyError, TypeError, ValueError):
            return None
        if not valid_numbers or not re.fullmatch(r"[0-9a-f]{64}", row.get("chapter_sha256", "")):
            return None
        if row.get("source_sha256") != source_hash or row.get("parser_version") != PARSER_VERSION:
            return None
        if row.get("status") not in {"ok", "empty"}:
            return None
        if not str(row.get("source_locator", "")).startswith(locator_path + ":L"):
            return None
    return data, rows


def mapping_signature(row: Dict[str, Any]) -> Tuple[str, str]:
    return str(row.get("volume", "")), str(row.get("source_chapter", ""))


def compare_rebuild(old_rows: Sequence[Dict[str, Any]], new_rows: Sequence[Dict[str, Any]]) -> List[int]:
    if len(new_rows) < len(old_rows):
        raise ValueError("chapter_mapping_ambiguous:index_would_shrink")
    for position, old_row in enumerate(old_rows):
        if mapping_signature(old_row) != mapping_signature(new_rows[position]):
            raise ValueError("chapter_mapping_ambiguous:position=%s" % (position + 1))
    return [position for position, row in enumerate(new_rows, start=1)
            if position > len(old_rows) or old_rows[position - 1].get("chapter_sha256") != row["chapter_sha256"]]


def legacy_mapping_conflict(output: Path, rows: Sequence[Dict[str, Any]]) -> Optional[str]:
    """Reject a fresh ordinal index when existing summary identity is ambiguous.

    A legacy project has no machine-readable mapping between ``第N章_摘要.md``
    and source headings.  If the source starts with a prologue/zero/non-one
    chapter, assigning internal ordinals would silently shift those files.
    A normal source that starts at chapter one remains compatible, including
    later volume-local renumbering.
    """
    summary_dir = output.parent / "章节"
    if not summary_dir.is_dir() or not rows:
        return None
    summary_numbers = sorted(
        int(match.group(1))
        for path in summary_dir.iterdir()
        if path.is_file() and (match := LEGACY_CHAPTER_FILE_RE.fullmatch(path.name))
    )
    if not summary_numbers:
        return None
    first_source = str(rows[0].get("source_chapter", "")).strip()
    try:
        starts_at_one = int(first_source) == 1
    except ValueError:
        starts_at_one = False
    if starts_at_one:
        return None
    return (
        "chapter_mapping_ambiguous:legacy_summaries_require_identity_mapping:"
        "first_source=%s:summaries=%s" % (first_source or "unknown", ",".join(map(str, summary_numbers)))
    )


def preserve_previous_index(output: Path, data: bytes) -> Path:
    """Keep the immediately previous CSV as cache evidence for localized invalidation."""
    previous = output.parent / "_analysis_cache" / "chapter_index.previous.csv"
    if previous.is_file() and previous.read_bytes() != data:
        old = previous.read_bytes()
        history = output.parent / "_analysis_cache" / "legacy" / (
            "chapter_index.%s.csv" % sha256(old)[:12]
        )
        if not history.exists():
            atomic_write(history, old)
    if not previous.is_file() or previous.read_bytes() != data:
        atomic_write(previous, data)
    return previous


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--locator-path")
    parser.add_argument("--rebuild", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if not args.source.is_file():
            raise ValueError("source_not_found:%s" % args.source)
        raw = args.source.read_bytes()
        source_hash = sha256(raw)
        locator_path = (args.locator_path or "原文/%s" % args.source.name).replace("\\", "/")
        if not locator_path.startswith("原文/") or ".." in locator_path.split("/"):
            raise ValueError("locator_path_must_stay_under_original")
        if args.output.exists() and not args.output.is_file():
            raise ValueError("output_is_not_file:%s" % args.output)
        if args.output.is_file() and not args.rebuild:
            reusable = reusable_index(args.output, source_hash, locator_path)
            if reusable is None:
                print(json.dumps({"ok": False, "error": "existing_index_incompatible"}, ensure_ascii=False))
                return 2
            _, existing_rows = reusable
            print(json.dumps({"ok": True, "reused": True, "parsed_source": False,
                              "chapters": len(existing_rows), "pending_chapters": []}, ensure_ascii=False))
            return 0
        rows = build_boundaries(decode_source(raw), locator_path, source_hash)
        pending = list(range(1, len(rows) + 1))
        old_count = 0
        if args.output.is_file():
            old_data, old_rows = read_existing(args.output)
            old_count = len(old_rows)
            pending = compare_rebuild(old_rows, rows)
        else:
            mapping_error = legacy_mapping_conflict(args.output, rows)
            if mapping_error:
                raise ValueError(mapping_error)
        data = csv_payload(rows)
        if not args.output.is_file() or args.output.read_bytes() != data:
            if args.output.is_file():
                preserve_previous_index(args.output, old_data)
            atomic_write(args.output, data)
        print(json.dumps({
            "ok": True, "reused": False, "parsed_source": True, "rebuilt": bool(old_count),
            "chapters": len(rows), "empty_chapters": sum(row["status"] == "empty" for row in rows),
            "pending_chapters": pending, "unchanged_chapters": len(rows) - len(pending),
            "source_sha256": source_hash, "parser_version": PARSER_VERSION,
        }, ensure_ascii=False))
        return 0
    except (OSError, UnicodeError, ValueError, csv.Error) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
