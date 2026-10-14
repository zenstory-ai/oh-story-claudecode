"""Public JJWXC book-page counts.

The rank list does not carry 收藏, 营养液, 积分, or 字数. The public book
page has 字数 in the HTML, and the page's own count request fills 收藏,
积分, and 营养液. This module reads those four numbers only. It does not
download chapters or send a cookie.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .http import (
    BOOK_PAGE_HOST,
    BOOK_PAGE_PATH,
    JjwxcRankError,
    STATS_ACTION,
    STATS_CALLBACK,
    STATS_HOST,
    STATS_PATH,
)

_BLOCK_MARKERS = (
    "访问过于频繁",
    "challenge-platform",
    "cf-turnstile",
)
_STATS_FIELDS = {
    "collectedCount": "favorite_count",
    "novelscore": "score_count",
    "nutritionCount": "nutrition_count",
}


@dataclass(slots=True)
class BookMetrics:
    word_count: str = ""
    favorite_count: str = ""
    score_count: str = ""
    nutrition_count: str = ""

    def complete(self) -> bool:
        return bool(
            self.word_count
            and self.favorite_count
            and self.score_count
            and self.nutrition_count
        )


def _require_novel_id(novel_id: str) -> str:
    text = str(novel_id or "")
    if not text.isdigit() or len(text) > 12:
        raise ValueError("jjwxc book id")
    return text


def book_page_url(novel_id: str) -> str:
    text = _require_novel_id(novel_id)
    return f"https://{BOOK_PAGE_HOST}{BOOK_PAGE_PATH}?novelid={text}"


def book_stats_url(novel_id: str) -> str:
    text = _require_novel_id(novel_id)
    return (
        f"https://{STATS_HOST}{STATS_PATH}"
        f"?action={STATS_ACTION}&novelid={text}&callback={STATS_CALLBACK}"
    )


def _digits(value: object) -> str:
    return re.sub(r"[^\d]", "", str(value or ""))


_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}


def _direct_text_digits(html: str, start: int) -> str:
    """Digits in the element's own text nodes, not descendants or comments."""
    depth = 1
    index = start
    parts: list[str] = []
    length = len(html)
    while index < length and depth > 0:
        if html.startswith("<!--", index):
            comment_end = html.find("-->", index + 4)
            index = length if comment_end < 0 else comment_end + 3
            continue
        if html[index] != "<":
            text_end = html.find("<", index)
            if text_end < 0:
                text_end = length
            if depth == 1:
                parts.append(html[index:text_end])
            index = text_end
            continue
        if html.startswith("</", index):
            closing = re.match(r"</\s*[A-Za-z0-9]+\s*>", html[index:])
            if closing is None:
                index += 1
                continue
            depth -= 1
            index += closing.end()
            continue
        opening = re.match(r"<\s*([A-Za-z0-9]+)\b([^>]*)>", html[index:])
        if opening is None:
            index += 1
            continue
        name = opening.group(1).lower()
        attrs = opening.group(2)
        index += opening.end()
        if name not in _VOID_TAGS and not attrs.rstrip().endswith("/"):
            depth += 1
    return _digits("".join(parts))


def _itemprop_number(html: str, name: str) -> str:
    match = re.search(
        rf"<(?P<tag>[a-zA-Z0-9]+)\b(?P<attrs>[^>]*\bitemprop\s*=\s*[\"']{re.escape(name)}[\"'][^>]*)>",
        html,
        re.I,
    )
    if match is None:
        return ""
    content = re.search(
        r"""\bcontent\s*=\s*["']([^"']*)["']""",
        match.group("attrs"),
        re.I,
    )
    if content is not None:
        digits = _digits(content.group(1))
        if digits:
            return digits
    if match.group("attrs").rstrip().endswith("/"):
        return ""
    return _direct_text_digits(html, match.end())


def parse_book_page(html: str) -> BookMetrics:
    text = html or ""
    if any(marker in text for marker in _BLOCK_MARKERS):
        raise JjwxcRankError("jjwxc book page unavailable")
    metrics = BookMetrics()
    metrics.word_count = _itemprop_number(text, "wordCount")
    metrics.favorite_count = _itemprop_number(text, "collectedCount")
    metrics.score_count = _itemprop_number(text, "scoreCount")
    metrics.nutrition_count = _itemprop_number(text, "nutritionCount")
    return metrics


def parse_book_stats(text: str) -> BookMetrics:
    raw = (text or "").strip()
    if raw.endswith(";"):
        raw = raw[:-1].strip()
    if not raw.startswith(STATS_CALLBACK):
        raise ValueError("jjwxc book stats payload")
    rest = raw[len(STATS_CALLBACK) :].strip()
    if not rest.startswith("(") or not rest.endswith(")"):
        raise ValueError("jjwxc book stats payload")
    try:
        payload = json.loads(rest[1:-1])
    except json.JSONDecodeError as exc:
        raise ValueError("jjwxc book stats payload") from exc
    if not isinstance(payload, dict):
        raise ValueError("jjwxc book stats payload")
    metrics = BookMetrics()
    for source, target in _STATS_FIELDS.items():
        if source in payload:
            setattr(metrics, target, _digits(payload[source]))
    return metrics


def fetch_book_metrics(novel_id: str, *, client: object) -> BookMetrics:
    """Read the four public counts. Stats override the HTML copies."""
    try:
        _require_novel_id(novel_id)
    except ValueError as exc:
        raise JjwxcRankError("jjwxc book page request failed") from exc
    fetch_public = getattr(client, "fetch_public", None)
    if fetch_public is None:
        raise JjwxcRankError("jjwxc book page request failed")
    metrics = BookMetrics()
    page_ok = False
    try:
        page = fetch_public(book_page_url(novel_id))
        if getattr(page, "status", None) != 200:
            raise JjwxcRankError("jjwxc book page http status")
        metrics = parse_book_page(getattr(page, "text", "") or "")
        page_ok = True
    except ValueError as exc:
        raise JjwxcRankError("jjwxc book page request failed") from exc
    except JjwxcRankError:
        page_ok = False
    stats_ok = False
    try:
        stats_response = fetch_public(book_stats_url(novel_id))
        if getattr(stats_response, "status", None) != 200:
            raise JjwxcRankError("jjwxc book page http status")
        stats = parse_book_stats(getattr(stats_response, "text", "") or "")
        stats_ok = True
    except ValueError as exc:
        if not page_ok:
            raise JjwxcRankError("jjwxc book page request failed") from exc
        return metrics
    except JjwxcRankError:
        stats_ok = False
    if not page_ok and not stats_ok:
        raise JjwxcRankError("jjwxc book page request failed")
    if stats_ok:
        for name in ("favorite_count", "score_count", "nutrition_count"):
            value = getattr(stats, name)
            if value:
                setattr(metrics, name, value)
    return metrics


__all__ = [
    "BookMetrics",
    "book_page_url",
    "book_stats_url",
    "fetch_book_metrics",
    "parse_book_page",
    "parse_book_stats",
]
