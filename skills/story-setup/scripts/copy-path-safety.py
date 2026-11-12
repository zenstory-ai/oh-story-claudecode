#!/usr/bin/env python3
"""Classify a recursive deployment copy before any filesystem mutation."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple


def canonical_path(raw_path: str) -> Path:
    """Return an absolute path with existing symlinks resolved."""

    return Path(os.path.realpath(os.path.abspath(os.path.expanduser(raw_path))))


def stat_path(path: Path) -> Tuple[Optional[bool], Optional[OSError]]:
    try:
        path.stat()
    except FileNotFoundError:
        return False, None
    except OSError as exc:
        return None, exc
    return True, None


def is_descendant(path: Path, parent: Path) -> bool:
    path_key = os.path.normcase(str(path))
    parent_key = os.path.normcase(str(parent))
    if path_key == parent_key:
        return False
    try:
        return os.path.commonpath((path_key, parent_key)) == parent_key
    except ValueError:
        # Different Windows drives cannot contain one another.
        return False


def classify_copy(source_raw: str, target_raw: str) -> Dict[str, object]:
    source = canonical_path(source_raw)
    target = canonical_path(target_raw)
    result: Dict[str, object] = {
        "source_realpath": str(source),
        "target_realpath": str(target),
        "copy_allowed": False,
    }

    source_exists, source_error = stat_path(source)
    if source_error is not None:
        result["status"] = "filesystem_identity_error"
        result["error"] = str(source_error)
        return result
    if not source_exists:
        result["status"] = "source_missing"
        return result

    source_key = os.path.normcase(str(source))
    target_key = os.path.normcase(str(target))
    if source_key == target_key:
        result["status"] = "same"
        return result

    target_exists, target_error = stat_path(target)
    if target_error is not None:
        result["status"] = "filesystem_identity_error"
        result["error"] = str(target_error)
        return result
    if target_exists:
        try:
            same_object = os.path.samefile(source, target)
        except OSError as exc:
            result["status"] = "filesystem_identity_error"
            result["error"] = str(exc)
            return result
        if same_object:
            result["status"] = "same"
            return result

    if is_descendant(target, source):
        result["status"] = "unsafe_target_within_source"
        return result

    result["status"] = "safe"
    result["copy_allowed"] = True
    return result


def prune_orphans(source_raw: str, target_raw: str) -> Dict[str, object]:
    raw_target = Path(os.path.abspath(os.path.expanduser(target_raw)))
    result = classify_copy(source_raw, target_raw)
    result["pruned"] = []
    if result["status"] != "safe" or not result["copy_allowed"]:
        return result
    if raw_target.is_symlink():
        result["status"] = "unsafe_target_symlink"
        result["copy_allowed"] = False
        return result

    source = Path(str(result["source_realpath"]))
    target = Path(str(result["target_realpath"]))
    if not source.is_dir() or not target.exists() or not target.is_dir() or target.is_symlink():
        return result

    pruned = []
    for dirpath, dirnames, filenames in os.walk(target, topdown=False, followlinks=False):
        cur_dir = Path(dirpath)
        for fname in filenames:
            t_entry = cur_dir / fname
            rel = t_entry.relative_to(target)
            s_entry = source / rel
            if not s_entry.exists() or (s_entry.is_dir() and not s_entry.is_symlink()):
                t_entry.unlink()
                pruned.append(rel.as_posix())
        for dname in dirnames:
            t_sub = cur_dir / dname
            rel = t_sub.relative_to(target)
            s_sub = source / rel
            if t_sub.is_symlink():
                if not s_sub.exists():
                    t_sub.unlink()
                    pruned.append(rel.as_posix())
            elif not s_sub.is_dir() or s_sub.is_symlink():
                try:
                    t_sub.rmdir()
                except OSError:
                    pass
                else:
                    pruned.append(rel.as_posix() + "/")
    result["pruned"] = sorted(pruned)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve symlinks, reject unsafe recursive copies, and optionally prune retired files in managed target directories."
    )
    parser.add_argument(
        "--prune-orphans",
        action="store_true",
        help="When status is safe and target is a real directory, delete files inside target that no longer exist in source.",
    )
    parser.add_argument("source")
    parser.add_argument("target")
    args = parser.parse_args()

    result = (
        prune_orphans(args.source, args.target)
        if args.prune_orphans
        else classify_copy(args.source, args.target)
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return status_exit_code(str(result["status"]))


def status_exit_code(status: str) -> int:
    return 0 if status in {"safe", "same"} else 2


if __name__ == "__main__":
    sys.exit(main())
