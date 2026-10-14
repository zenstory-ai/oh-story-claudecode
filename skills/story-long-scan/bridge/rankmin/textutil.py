from __future__ import annotations

from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))


def now_cst_iso() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


def today_cst() -> str:
    return datetime.now(CST).strftime("%Y%m%d")


def has_private_use_chars(text: str) -> bool:
    return any(0xE000 <= ord(ch) <= 0xF8FF for ch in text or "")


def extract_json_object_after_marker(text: str, marker: str) -> str:
    marker_index = text.find(marker)
    if marker_index < 0:
        raise ValueError("marker_missing")
    start = text.find("{", marker_index + len(marker))
    if start < 0:
        raise ValueError("json_start_missing")
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        ch = text[index]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    raise ValueError("json_unbalanced")
