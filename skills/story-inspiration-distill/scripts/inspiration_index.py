#!/usr/bin/env python3
"""Render inspiration atoms, then validate/query the public three-layer index."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


COLUMNS = (
    "item_id",
    "layer",
    "title",
    "source_book",
    "path",
    "source_ids",
    "novel_count",
    "atom_count",
    "tags",
    "status",
)
LAYERS = {"原子灵感": "IA-", "单小说灵感合并": "NM-", "跨书灵感聚合": "CBA-"}
TAG_AXES = {"题材", "读者需求", "情绪", "关系动作", "剧情功能", "节奏位置", "适用阶段", "风险"}
REQUIRED_CBA_AXES = {"题材", "读者需求", "情绪", "剧情功能", "适用阶段", "风险"}
CORE_QUERY_AXES = {"题材", "读者需求", "情绪", "剧情功能", "适用阶段"}
BLOCK_COLUMNS = (
    "block_id", "chapter_range", "block_name", "initial_gap", "goal", "pressure",
    "turning_point", "payoff", "remaining_hook", "state_change", "main_characters",
    "evidence_locator", "plot_intensity", "emotion_type", "emotion_intensity",
    "description_density", "relationship_delta", "rhythm_anchors", "inspiration_title",
    "inspiration_mechanism", "inspiration_reader_effect", "inspiration_transfer_boundary",
    "inspiration_risk", "confidence", "status",
)
INSPIRATION_FIELDS = (
    "inspiration_title",
    "inspiration_mechanism",
    "inspiration_reader_effect",
    "inspiration_transfer_boundary",
    "inspiration_risk",
)


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def csv_text(rows: list[dict[str, str]]) -> str:
    import io

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return "\ufeff" + buffer.getvalue()


def inspiration_names(row: dict[str, str]) -> list[str]:
    return [
        value.strip()
        for value in re.split(r"[|；;,，、/]+", row.get("main_characters", ""))
        if len(value.strip()) >= 2
    ]


def atom_markdown(book: str, row: dict[str, str], atom_id: str) -> str:
    title = row["inspiration_title"].strip().replace("\n", " ").replace("#", "")
    return (
        f"# {atom_id}：{title}\n\n"
        f"- 来源小说：《{book}》\n"
        f"- 来源结构块：{row['block_id'].strip()}；{row['chapter_range'].strip()}章\n"
        f"- 来源分析：[structure_blocks.csv](../../../拆文库/{book}/structure_blocks.csv) + "
        f"[六维拆书](../../../拆文库/{book}/全局分析/六维拆书.md)\n\n"
        "## 机制原子\n"
        f"- 机制链：{row['inspiration_mechanism'].strip()}\n"
        f"- 读者心理效果：{row['inspiration_reader_effect'].strip()}\n\n"
        "## 迁移边界\n"
        f"- 可迁移与必须替换：{row['inspiration_transfer_boundary'].strip()}\n"
        f"- 误用风险：{row['inspiration_risk'].strip()}\n\n"
        "## 聚类键\n"
        f"- 读者需求/情绪：{row['inspiration_reader_effect'].strip()}\n"
        f"- 机制链：{row['inspiration_mechanism'].strip()}\n"
    )


def render_atoms(root: Path, blocks_path: Path, book: str) -> dict[str, Any]:
    try:
        with blocks_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            blocks = list(reader)
            if tuple(reader.fieldnames or ()) != BLOCK_COLUMNS:
                raise ValueError("structure_blocks_header_mismatch")
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValueError(f"structure_blocks_unreadable:{exc}") from exc

    prepared: list[tuple[str, dict[str, str], str]] = []
    seen_atoms: set[str] = set()
    for row in blocks:
        if row.get("status", "").strip() != "ok":
            continue
        block_id = row.get("block_id", "").strip()
        match = re.fullmatch(r"SB-([0-9]{3,})", block_id)
        if not match:
            raise ValueError(f"block_id_invalid:{block_id}")
        atom_id = f"IA-{match.group(1)}"
        if atom_id in seen_atoms:
            raise ValueError(f"atom_id_duplicate:{atom_id}")
        seen_atoms.add(atom_id)
        missing = [field for field in INSPIRATION_FIELDS if not row.get(field, "").strip()]
        if missing:
            raise ValueError(f"{block_id}:inspiration_fields_missing:{'|'.join(missing)}")
        abstract_text = " ".join(row[field] for field in INSPIRATION_FIELDS)
        leaked = sorted({name for name in inspiration_names(row) if name in abstract_text})
        if leaked:
            raise ValueError(f"{block_id}:source_specific_name_in_inspiration:{'|'.join(leaked)}")
        prepared.append((atom_id, row, atom_markdown(book, row, atom_id)))

    existing, errors = load_rows(root) if (root / "灵感索引.csv").is_file() else ([], [])
    if errors:
        raise ValueError(";".join(errors))
    preserved = [
        row
        for row in existing
        if not (row.get("layer") == "原子灵感" and row.get("source_book") == book)
    ]
    atom_rows: list[dict[str, str]] = []
    atom_dir = root / "原子灵感" / book
    for atom_id, row, markdown in prepared:
        card_path = atom_dir / f"{atom_id}.md"
        atomic_write_text(card_path, markdown)
        atom_rows.append(
            {
                "item_id": atom_id,
                "layer": "原子灵感",
                "title": row["inspiration_title"].strip(),
                "source_book": book,
                "path": f"原子灵感/{book}/{atom_id}.md",
                "source_ids": row["block_id"].strip(),
                "novel_count": "1",
                "atom_count": "1",
                "tags": "",
                "status": "active",
            }
        )
    layer_order = {"原子灵感": 0, "单小说灵感合并": 1, "跨书灵感聚合": 2}
    combined = preserved + atom_rows
    combined.sort(
        key=lambda row: (
            layer_order.get(row.get("layer", ""), 9),
            row.get("source_book", ""),
            row.get("item_id", ""),
        )
    )
    atomic_write_text(root / "灵感索引.csv", csv_text(combined), encoding="utf-8")
    return {"ok": True, "book": book, "atoms": len(atom_rows), "index_writes": 1}


def load_rows(root: Path) -> tuple[list[dict[str, str]], list[str]]:
    errors: list[str] = []
    index_path = root / "灵感索引.csv"
    try:
        with index_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            if tuple(reader.fieldnames or ()) != COLUMNS:
                errors.append("index_header_mismatch")
    except (OSError, UnicodeError, csv.Error) as exc:
        return [], [f"index_unreadable:{exc}"]
    return rows, errors


def parse_tags(raw: str) -> tuple[dict[str, set[str]], list[str]]:
    result: dict[str, set[str]] = {}
    errors: list[str] = []
    if not raw.strip():
        return result, errors
    for part in raw.split("；"):
        if not part.strip():
            continue
        if "=" not in part:
            errors.append(f"tag_missing_equals:{part}")
            continue
        axis, values = (piece.strip() for piece in part.split("=", 1))
        if axis not in TAG_AXES:
            errors.append(f"tag_axis_unknown:{axis}")
            continue
        parsed = {value.strip() for value in values.split("|") if value.strip()}
        if not parsed:
            errors.append(f"tag_value_empty:{axis}")
            continue
        result.setdefault(axis, set()).update(parsed)
    return result, errors


def positive_int(raw: str) -> int | None:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 1 else None


def source_ids(raw: str) -> list[str]:
    return [item.strip() for item in re.split(r"[|；]", raw) if item.strip()]


def load_valid_blocks(root: Path, source_book: str) -> tuple[set[str], str | None]:
    block_path = root.parent / "拆文库" / source_book / "structure_blocks.csv"
    try:
        with block_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            if tuple(reader.fieldnames or ()) != BLOCK_COLUMNS:
                return set(), "structure_blocks_header_mismatch"
    except (OSError, UnicodeError, csv.Error):
        return set(), "structure_blocks_unreadable"
    return {row["block_id"].strip() for row in rows if row.get("status", "").strip() == "ok"}, None


def validate(root: Path) -> list[str]:
    rows, errors = load_rows(root)
    seen: set[tuple[str, str, str]] = set()
    by_key: dict[tuple[str, str], dict[str, str]] = {}
    ia_by_book: dict[str, dict[str, dict[str, str]]] = {}
    nm_by_book: dict[str, dict[str, dict[str, str]]] = {}
    active_single_book_cba: dict[str, int] = {}
    for number, row in enumerate(rows, start=2):
        item_id = row.get("item_id", "").strip()
        layer = row.get("layer", "").strip()
        book = row.get("source_book", "").strip()
        prefix = LAYERS.get(layer)
        if not prefix:
            errors.append(f"line_{number}:layer_invalid")
            continue
        unique_key = (layer, book if layer != "跨书灵感聚合" else "", item_id)
        if not item_id.startswith(prefix) or unique_key in seen:
            errors.append(f"line_{number}:item_id_invalid_or_duplicate")
        seen.add(unique_key)
        by_key[(book, item_id)] = row
        if layer == "原子灵感":
            ia_by_book.setdefault(book, {})[item_id] = row
        elif layer == "单小说灵感合并":
            nm_by_book.setdefault(book, {})[item_id] = row
        relative = row.get("path", "").strip().replace("\\", "/")
        if not relative.startswith(f"{layer}/") or ".." in relative.split("/"):
            errors.append(f"line_{number}:path_outside_layer")
        elif not (root / Path(relative)).is_file():
            errors.append(f"line_{number}:path_missing")
        tags, tag_errors = parse_tags(row.get("tags", ""))
        errors.extend(f"line_{number}:{error}" for error in tag_errors)
        if layer == "跨书灵感聚合":
            missing = REQUIRED_CBA_AXES - set(tags)
            if missing:
                errors.append(f"line_{number}:cba_tags_missing:{'|'.join(sorted(missing))}")
            novel_count = positive_int(row.get("novel_count", ""))
            if novel_count is None:
                errors.append(f"line_{number}:novel_count_invalid")
            if positive_int(row.get("atom_count", "")) is None:
                errors.append(f"line_{number}:atom_count_invalid")
            if not row.get("source_ids", "").strip():
                errors.append(f"line_{number}:source_ids_missing")
            card_path = root / Path(relative)
            try:
                card_text = card_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                card_text = ""
            if novel_count == 1 and "单书假设" not in card_text:
                errors.append(f"line_{number}:single_book_hypothesis_marker_missing")
            if novel_count == 1 and row.get("status", "").strip() == "active" and book:
                active_single_book_cba[book] = active_single_book_cba.get(book, 0) + 1
            if novel_count is not None and novel_count >= 2 and "跨书重复验证" not in card_text:
                errors.append(f"line_{number}:cross_book_validation_marker_missing")
        elif tags:
            errors.append(f"line_{number}:tags_reserved_for_cba")

    for book, count in active_single_book_cba.items():
        if count > 3:
            errors.append(f"book_{book}:active_single_book_cba_limit_exceeded:{count}")

    membership: dict[tuple[str, str], int] = {}
    for book, atoms in ia_by_book.items():
        valid_blocks, block_error = load_valid_blocks(root, book)
        if block_error:
            errors.append(f"book_{book}:{block_error}")
        atom_blocks: set[str] = set()
        for item_id, row in atoms.items():
            refs = source_ids(row.get("source_ids", ""))
            if len(refs) != 1 or not refs[0].startswith("SB-"):
                errors.append(f"{book}/{item_id}:ia_source_block_invalid")
            else:
                atom_blocks.add(refs[0])
            if positive_int(row.get("novel_count", "")) != 1 or positive_int(row.get("atom_count", "")) != 1:
                errors.append(f"{book}/{item_id}:ia_counts_must_equal_one")
        if not block_error and atom_blocks != valid_blocks:
            missing = sorted(valid_blocks - atom_blocks)
            extra = sorted(atom_blocks - valid_blocks)
            errors.append(f"book_{book}:ia_block_set_mismatch:missing={missing}:extra={extra}")

    for book, merges in nm_by_book.items():
        atoms = ia_by_book.get(book, {})
        for item_id, row in merges.items():
            refs = source_ids(row.get("source_ids", ""))
            if not refs:
                errors.append(f"{book}/{item_id}:nm_source_ids_missing")
                continue
            unknown = sorted(set(refs) - set(atoms))
            if unknown:
                errors.append(f"{book}/{item_id}:nm_source_ia_missing:{unknown}")
            known = set(refs) & set(atoms)
            if positive_int(row.get("novel_count", "")) != 1:
                errors.append(f"{book}/{item_id}:nm_novel_count_must_equal_one")
            if positive_int(row.get("atom_count", "")) != len(known):
                errors.append(f"{book}/{item_id}:nm_atom_count_mismatch")
            for atom_id in known:
                membership[(book, atom_id)] = membership.get((book, atom_id), 0) + 1

    for book, atoms in ia_by_book.items():
        for item_id in atoms:
            if membership.get((book, item_id), 0) < 1:
                errors.append(f"{book}/{item_id}:ia_not_assigned_to_nm")

    for row in rows:
        if row.get("layer") != "跨书灵感聚合":
            continue
        cba_id = row.get("item_id", "").strip()
        default_books = source_ids(row.get("source_book", ""))
        default_book = default_books[0] if len(default_books) == 1 else ""
        nm_refs: set[tuple[str, str]] = set()
        ia_refs: set[tuple[str, str]] = set()
        unknown_refs: list[str] = []
        for raw_ref in source_ids(row.get("source_ids", "")):
            if "/" in raw_ref:
                book, ref = raw_ref.split("/", 1)
            else:
                book, ref = default_book, raw_ref
            if not book:
                unknown_refs.append(raw_ref)
            elif ref.startswith("NM-") and ref in nm_by_book.get(book, {}):
                nm_refs.add((book, ref))
            elif ref.startswith("IA-") and ref in ia_by_book.get(book, {}):
                ia_refs.add((book, ref))
            else:
                unknown_refs.append(raw_ref)
        if unknown_refs:
            errors.append(f"{cba_id}:cba_source_missing:{sorted(unknown_refs)}")
        if not nm_refs or not ia_refs:
            errors.append(f"{cba_id}:cba_requires_nm_and_ia_sources")
        expected_ia: set[tuple[str, str]] = set()
        for book, nm_id in nm_refs:
            for atom_id in source_ids(nm_by_book[book][nm_id].get("source_ids", "")):
                if atom_id in ia_by_book.get(book, {}):
                    expected_ia.add((book, atom_id))
        if ia_refs != expected_ia:
            errors.append(f"{cba_id}:cba_ia_closure_mismatch")
        novels = {book for book, _ in expected_ia}
        if positive_int(row.get("novel_count", "")) != len(novels):
            errors.append(f"{cba_id}:cba_novel_count_mismatch")
        if positive_int(row.get("atom_count", "")) != len(expected_ia):
            errors.append(f"{cba_id}:cba_atom_count_mismatch")
    return errors


def requested_tags(values: list[str]) -> dict[str, set[str]]:
    tags, errors = parse_tags("；".join(values))
    if errors:
        raise ValueError(";".join(errors))
    return tags


def query(root: Path, values: list[str], limit: int) -> list[dict[str, Any]]:
    rows, errors = load_rows(root)
    if errors:
        raise ValueError(";".join(errors))
    wanted = requested_tags(values)
    matches: list[dict[str, Any]] = []
    for row in rows:
        if row.get("layer") != "跨书灵感聚合" or row.get("status") != "active":
            continue
        tags, tag_errors = parse_tags(row.get("tags", ""))
        if tag_errors:
            continue
        score = 0
        matched: list[str] = []
        core_match = False
        for axis, wanted_values in wanted.items():
            overlap = wanted_values & tags.get(axis, set())
            if overlap:
                score += (2 if axis in CORE_QUERY_AXES else 1) * len(overlap)
                matched.extend(f"{axis}={value}" for value in sorted(overlap))
                if axis in CORE_QUERY_AXES:
                    core_match = True
        if score <= 0 or not core_match:
            continue
        matches.append(
            {
                "item_id": row["item_id"],
                "title": row["title"],
                "path": row["path"],
                "score": score,
                "matched_tags": matched,
                "novel_count": positive_int(row.get("novel_count", "")) or 0,
                "atom_count": positive_int(row.get("atom_count", "")) or 0,
            }
        )
    matches.sort(key=lambda item: (-item["score"], -item["novel_count"], -item["atom_count"], item["item_id"]))
    return matches[: max(3, min(limit, 8))]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    render_parser = subparsers.add_parser("render-atoms")
    render_parser.add_argument("--root", required=True, type=Path)
    render_parser.add_argument("--blocks", required=True, type=Path)
    render_parser.add_argument("--book", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--root", required=True, type=Path)
    query_parser = subparsers.add_parser("query")
    query_parser.add_argument("--root", required=True, type=Path)
    query_parser.add_argument("--tag", action="append", default=[])
    query_parser.add_argument("--limit", type=int, default=6)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "render-atoms":
        try:
            payload = render_atoms(args.root, args.blocks, args.book.strip())
        except ValueError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            return 2
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    if args.command == "validate":
        errors = validate(args.root)
        print(json.dumps({"ok": not errors, "errors": errors}, ensure_ascii=False))
        return 0 if not errors else 1
    try:
        matches = query(args.root, args.tag, args.limit)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, "matches": matches}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
