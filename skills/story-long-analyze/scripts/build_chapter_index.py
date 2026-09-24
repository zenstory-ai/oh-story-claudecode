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
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from inspect_existing_assets import legacy_mapping_check


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


def fold_leading_specials(candidates: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Merge 楔子/序章/第0章… before the first numbered chapter into that chapter.

    Only on request: it reproduces the numbering of older runs that did not
    count a prologue, so their 第N章 files keep pointing at the same chapter.
    """
    first = next((index for index, item in enumerate(candidates)
                  if item.get("number_value") is not None and item["number_value"] >= 1), None)
    if not first:
        return candidates, []
    folded = [str(item["source_chapter"]) if item["number_value"] is None else "第0章"
              for item in candidates[:first]]
    body = dict(candidates[first])
    body["line"] = candidates[0]["line"]
    return [body] + candidates[first + 1:], folded


def build_boundaries(text: str, locator_path: str, source_hash: str,
                     fold_prologue: bool = False) -> Tuple[List[Dict[str, Any]], List[str]]:
    lines = physical_lines(text)
    candidates = drop_adjacent_duplicate_headings(drop_leading_toc(heading_candidates(lines)), lines)
    if not candidates:
        raise ValueError("chapter_heading_not_found")
    validate_numbering(candidates)
    folded = []  # type: List[str]
    if fold_prologue:
        candidates, folded = fold_leading_specials(candidates)
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
    return rows, folded


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


class RebuildMismatch(ValueError):
    def __init__(self, code: str, author_message: str) -> None:
        super().__init__(code)
        self.author_message = author_message


REBUILD_MISMATCH_MESSAGE = (
    "重建章节表时发现，%s。照这样继续，已拆好的章节会和原文错开，所以章节表没有改。请选一种："
    "① 换回上次拆文时用的那份原文再继续（推荐）；② 换一个新目录，整本重新拆。"
)


def index_was_folded(old_rows: Sequence[Dict[str, Any]], new_rows: Sequence[Dict[str, Any]]) -> bool:
    """True when the existing index merged a prologue into chapter one.

    A folded index starts with a numbered chapter although the text opens with
    楔子/序章/第0章; a rebuild keeps that numbering instead of shifting it.
    """
    old_first = str(old_rows[0].get("source_chapter", "")) if old_rows else ""
    new_first = str(new_rows[0].get("source_chapter", "")) if new_rows else ""
    return (old_first.isdigit() and int(old_first) >= 1
            and not (new_first.isdigit() and int(new_first) >= 1))


def compare_rebuild(old_rows: Sequence[Dict[str, Any]], new_rows: Sequence[Dict[str, Any]]) -> List[int]:
    for position, old_row in enumerate(old_rows[:len(new_rows)]):
        if mapping_signature(old_row) != mapping_signature(new_rows[position]):
            raise RebuildMismatch(
                "chapter_mapping_ambiguous:position=%s" % (position + 1),
                REBUILD_MISMATCH_MESSAGE % ("第%s章和上次的章节表对不上（上次是「%s」，这次是「%s」）" % (
                    position + 1, old_row.get("title", ""), new_rows[position]["title"])))
    if len(new_rows) < len(old_rows):
        raise RebuildMismatch("chapter_mapping_ambiguous:index_would_shrink",
                              REBUILD_MISMATCH_MESSAGE % "这次认出的章节比上次少")
    return [position for position, row in enumerate(new_rows, start=1)
            if position > len(old_rows) or old_rows[position - 1].get("chapter_sha256") != row["chapter_sha256"]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--locator-path")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--fold-prologue", action="store_true",
                        help="merge 楔子/序章/第0章 before the first numbered chapter into it")
    return parser.parse_args()


def fail(error: str, author_message: Optional[str] = None) -> int:
    payload = {"ok": False, "error": error}  # type: Dict[str, Any]
    if author_message:
        payload["author_message"] = author_message
    print(json.dumps(payload, ensure_ascii=False))
    return 2


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
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
                return fail("existing_index_incompatible",
                            "原文和上次建章节表时不一样了（内容、文件名或识别规则变了）。确认原文就是要拆的版本后，再重建章节表。")
            _, existing_rows = reusable
            print(json.dumps({"ok": True, "reused": True, "parsed_source": False,
                              "chapters": len(existing_rows), "pending_chapters": []}, ensure_ascii=False))
            return 0
        text = decode_source(raw)
        rows, folded = build_boundaries(text, locator_path, source_hash, args.fold_prologue)
        pending = list(range(1, len(rows) + 1))
        old_count = 0
        if args.output.is_file():
            _, old_rows = read_existing(args.output)
            old_count = len(old_rows)
            if not args.fold_prologue and index_was_folded(old_rows, rows):
                rows, folded = build_boundaries(text, locator_path, source_hash, True)
            pending = compare_rebuild(old_rows, rows)
        else:
            mapping = legacy_mapping_check(args.output.parent, rows)
            if mapping:
                return fail("chapter_mapping_ambiguous:%s:legacy_chapters=%s" % (
                    mapping["code"], ",".join(map(str, mapping["legacy_chapters"]))), str(mapping["author_message"]))
        data = csv_payload(rows)
        if not args.output.is_file() or args.output.read_bytes() != data:
            atomic_write(args.output, data)
        print(json.dumps({
            "ok": True, "reused": False, "parsed_source": True, "rebuilt": bool(old_count),
            "chapters": len(rows), "empty_chapters": sum(row["status"] == "empty" for row in rows),
            "pending_chapters": pending, "unchanged_chapters": len(rows) - len(pending),
            "source_sha256": source_hash, "parser_version": PARSER_VERSION,
            "folded_into_first_chapter": folded,
        }, ensure_ascii=False))
        return 0
    except RebuildMismatch as exc:
        return fail(str(exc), exc.author_message)
    except (OSError, UnicodeError, ValueError, csv.Error) as exc:
        return fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
