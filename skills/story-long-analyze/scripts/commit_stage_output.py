#!/usr/bin/env python3
"""Commit or verify a resumable Stage 3-6 output receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path: Path, payload: dict[str, object]) -> None:
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


def labels(root: Path, values: list[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        path = value.resolve()
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError(f"path must stay inside root: {path}") from exc
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"required file is missing or empty: {relative}")
        result[relative] = digest(path)
    return result


def execute(args: argparse.Namespace) -> dict[str, object]:
    if not re.fullmatch(r"[a-z0-9_-]+", args.stage):
        raise ValueError("stage must contain lowercase letters, digits, '_' or '-'")
    root = args.root.resolve()
    receipt_path = root / "_analysis_cache" / "stage-receipts" / f"{args.stage}.json"
    if args.action == "verify":
        if not receipt_path.is_file():
            return {"stage": args.stage, "reused": False, "reason": "receipt_missing"}
        receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
        expected = {**receipt.get("dependencies", {}), **receipt.get("outputs", {})}
        mismatches = []
        for relative, expected_hash in expected.items():
            path = (root / relative).resolve()
            try:
                path.relative_to(root)
            except ValueError:
                mismatches.append(relative)
                continue
            if not path.is_file() or digest(path) != expected_hash:
                mismatches.append(relative)
        return {"stage": args.stage, "reused": not mismatches, "mismatches": mismatches}

    if not args.output:
        raise ValueError("commit requires at least one --output")
    if not args.dependency:
        raise ValueError("commit requires at least one --dependency so stale inputs can invalidate the stage")
    payload = {
        "schema_version": 1,
        "stage": args.stage,
        "dependencies": labels(root, args.dependency),
        "outputs": labels(root, args.output),
        "status": "success",
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    existing = json.loads(receipt_path.read_text(encoding="utf-8-sig")) if receipt_path.is_file() else None
    if existing:
        comparable = {key: value for key, value in existing.items() if key != "updated_at"}
        next_comparable = {key: value for key, value in payload.items() if key != "updated_at"}
        if comparable == next_comparable:
            return {"stage": args.stage, "reused": True, "receipt": receipt_path.relative_to(root).as_posix()}
    atomic_write(receipt_path, payload)
    return {"stage": args.stage, "reused": False, "receipt": receipt_path.relative_to(root).as_posix()}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("action", choices=("commit", "verify"))
    result.add_argument("--root", type=Path, required=True)
    result.add_argument("--stage", required=True)
    result.add_argument("--dependency", type=Path, action="append", default=[])
    result.add_argument("--output", type=Path, action="append", default=[])
    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        payload = execute(parser().parse_args())
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"error": "stage_receipt_error", "detail": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
