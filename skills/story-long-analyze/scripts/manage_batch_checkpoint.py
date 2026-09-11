#!/usr/bin/env python3
"""Track batch attempts and split only a failed raw block for retry."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class CheckpointError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
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


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path, default: dict[str, object]) -> dict[str, object]:
    if not path.is_file():
        return default
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise CheckpointError("checkpoint_invalid", f"JSON root must be an object: {path}")
    return value


def ledger_path(root: Path) -> Path:
    return root / "_analysis_cache" / "batch-checkpoints.json"


def base_ledger(source_hash: str | None) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_sha256": source_hash,
        "forced_break_after": [],
        "batches": {},
    }


def validate_id(batch_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", batch_id):
        raise CheckpointError("invalid_batch_id", "batch id contains unsupported characters")


def validate_source_hash(source_hash: str | None) -> None:
    if source_hash and not re.fullmatch(r"[0-9a-fA-F]{64}", source_hash):
        raise CheckpointError("invalid_source_hash", "source SHA-256 must contain 64 hexadecimal characters")


def load_ledger(root: Path, source_hash: str | None) -> dict[str, object]:
    path = ledger_path(root)
    payload = load_json(path, base_ledger(source_hash))
    old_hash = payload.get("source_sha256")
    if source_hash and old_hash and str(old_hash).lower() != source_hash.lower():
        raise CheckpointError("source_hash_mismatch", "checkpoint ledger belongs to a different original")
    if source_hash and not old_hash:
        payload["source_sha256"] = source_hash.lower()
    payload.setdefault("forced_break_after", [])
    payload.setdefault("batches", {})
    return payload


def write_if_changed(path: Path, before: dict[str, object], after: dict[str, object]) -> bool:
    if before == after and path.is_file():
        return False
    after["updated_at"] = now()
    atomic_json(path, after)
    return True


def mark_completed(
    root: Path,
    batch_id: str,
    start: int,
    end: int,
    input_kind: str,
    source_hash: str | None,
    receipt: str,
) -> bool:
    """Called by commit_batch_output after all output hashes are verified."""
    validate_id(batch_id)
    path = ledger_path(root)
    ledger = load_ledger(root, source_hash)
    before = json.loads(json.dumps(ledger))
    batches = ledger["batches"]
    assert isinstance(batches, dict)
    previous = batches.get(batch_id, {})
    attempts = max(1, int(previous.get("attempts", 0)))
    stable = {
        **previous,
        "start": start,
        "end": end,
        "input_kind": input_kind,
        "attempts": attempts,
        "status": "success",
        "receipt": receipt,
        "last_error": None,
    }
    if previous.get("status") != "success" or previous.get("receipt") != receipt:
        stable["updated_at"] = now()
    batches[batch_id] = stable
    return write_if_changed(path, before, ledger)


def find_block(plan: dict[str, object], batch_id: str) -> tuple[list[dict[str, object]], int, dict[str, object]]:
    try:
        blocks = plan["routing"]["raw_original_read"]["blocks"]
    except (KeyError, TypeError) as exc:
        raise CheckpointError("plan_invalid", "run plan has no raw block list") from exc
    if not isinstance(blocks, list):
        raise CheckpointError("plan_invalid", "raw block list is invalid")
    for index, block in enumerate(blocks):
        if isinstance(block, dict) and block.get("id") == batch_id:
            return blocks, index, block
    raise CheckpointError("batch_not_in_plan", f"raw batch is absent from run plan: {batch_id}")


def balanced_boundary(index_path: Path, start: int, end: int) -> int:
    counts: dict[int, int] = {}
    with index_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            counts[int(row["chapter"])] = int(row["char_count"])
    missing = [chapter for chapter in range(start, end + 1) if chapter not in counts]
    if missing:
        raise CheckpointError("chapter_index_invalid", f"missing chapters in index: {missing}")
    total = sum(counts[chapter] for chapter in range(start, end + 1))
    running = 0
    best = start
    distance = total
    for chapter in range(start, end):
        running += counts[chapter]
        current = abs(total - 2 * running)
        if current < distance:
            distance = current
            best = chapter
    return best


def child_block(parent: dict[str, object], child_id: str, start: int, end: int, rows: dict[int, dict[str, str]]) -> dict[str, object]:
    char_count = sum(int(rows[chapter]["char_count"]) for chapter in range(start, end + 1))
    return {
        **parent,
        "id": child_id,
        "start": start,
        "end": end,
        "chapters": end - start + 1,
        "char_count": char_count,
        "oversized_single_chapter": start == end and bool(parent.get("oversized_single_chapter")),
        "source_start": rows[start]["source_locator"],
        "source_end": rows[end]["source_locator"],
        "parent_id": parent["id"],
    }


def split_failed_block(root: Path, plan_path: Path, batch_id: str, ledger: dict[str, object]) -> list[str]:
    try:
        plan_path.relative_to(root)
    except ValueError as exc:
        raise CheckpointError("plan_outside_root", "run plan must stay inside the book analysis root") from exc
    plan = load_json(plan_path, {})
    plan_hash = plan.get("source_sha256")
    ledger_hash = ledger.get("source_sha256")
    if plan_hash and ledger_hash and str(plan_hash).lower() != str(ledger_hash).lower():
        raise CheckpointError("plan_source_mismatch", "run plan and checkpoint ledger refer to different originals")
    blocks, position, parent = find_block(plan, batch_id)
    start, end = int(parent["start"]), int(parent["end"])
    if start >= end:
        raise CheckpointError("single_chapter_cannot_split", "a one-chapter block must be retried or fixed directly")
    index_path = root / "chapter_index.csv"
    if not index_path.is_file():
        raise CheckpointError("chapter_index_required", str(index_path))
    boundary = balanced_boundary(index_path, start, end)
    rows: dict[int, dict[str, str]] = {}
    with index_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            rows[int(row["chapter"])] = row
    child_ids = [f"{batch_id}A", f"{batch_id}B"]
    children = [
        child_block(parent, child_ids[0], start, boundary, rows),
        child_block(parent, child_ids[1], boundary + 1, end, rows),
    ]
    blocks[position : position + 1] = children
    atomic_json(plan_path, plan)

    forced = {int(value) for value in ledger.get("forced_break_after", [])}
    forced.add(boundary)
    ledger["forced_break_after"] = sorted(forced)
    batches = ledger["batches"]
    assert isinstance(batches, dict)
    parent_state = batches.setdefault(batch_id, {})
    parent_state.update({"status": "superseded", "children": child_ids, "split_after": boundary, "updated_at": now()})
    for child in children:
        batches.setdefault(
            str(child["id"]),
            {
                "start": child["start"],
                "end": child["end"],
                "input_kind": "raw-original",
                "attempts": 0,
                "status": "planned",
                "parent_id": batch_id,
            },
        )
    return child_ids


def execute(args: argparse.Namespace) -> dict[str, object]:
    validate_id(args.batch_id)
    root = args.root.resolve()
    validate_source_hash(args.source_sha256)
    source_hash = args.source_sha256.lower() if args.source_sha256 else None
    path = ledger_path(root)
    ledger = load_ledger(root, source_hash)
    before = json.loads(json.dumps(ledger))
    batches = ledger["batches"]
    assert isinstance(batches, dict)
    state = batches.setdefault(args.batch_id, {})

    if args.action == "start":
        if args.start is None or args.end is None or args.input_kind is None:
            raise CheckpointError("range_required", "start requires --start, --end and --input-kind")
        if args.start < 1 or args.end < args.start:
            raise CheckpointError("invalid_range", "start/end must define a positive continuous range")
        state["attempts"] = int(state.get("attempts", 0)) + 1
        state.update(
            {
                "start": args.start,
                "end": args.end,
                "input_kind": args.input_kind,
                "status": "running",
                "last_error": None,
                "updated_at": now(),
            }
        )
        children: list[str] = []
    else:
        if not state:
            state["attempts"] = 1
        state.update({"status": "failed", "last_error": args.reason or "unspecified", "updated_at": now()})
        children = []
        if args.split:
            plan_path = args.plan.resolve() if args.plan else root / "_analysis_cache" / "run-plan.json"
            children = split_failed_block(root, plan_path, args.batch_id, ledger)

    changed = write_if_changed(path, before, ledger)
    return {
        "batch_id": args.batch_id,
        "action": args.action,
        "status": ledger["batches"][args.batch_id]["status"],
        "children": children,
        "changed": changed,
        "ledger": path.relative_to(root).as_posix(),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("action", choices=("start", "fail"))
    result.add_argument("--root", type=Path, required=True)
    result.add_argument("--batch-id", required=True)
    result.add_argument("--start", type=int)
    result.add_argument("--end", type=int)
    result.add_argument("--input-kind", choices=("raw-original", "existing-results"))
    result.add_argument("--source-sha256")
    result.add_argument("--reason")
    result.add_argument("--split", action="store_true", help="replace only this failed raw block with two children")
    result.add_argument("--plan", type=Path)
    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        payload = execute(parser().parse_args())
    except CheckpointError as error:
        print(json.dumps({"error": error.code, "detail": error.detail}, ensure_ascii=False))
        return 2
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, ValueError) as error:
        print(json.dumps({"error": "checkpoint_io_error", "detail": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
