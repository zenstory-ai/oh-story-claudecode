"""JJWXC app bookstore ranks.

The request path is the copied client in bridge/jjwxc_app. This file maps a
named board into scan markdown and walks pages until the caller has enough
books, the board ends, or the page cap is hit. Each kept book then reads the
public book page for 收藏, 营养液, 积分, and 字数. It does not download chapters.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .contracts import RankFetchError, RankItem, RankSnapshot, SourceSpec
from .textutil import now_cst_iso

PARSER_VERSION = "jjwxc_app_rank_v2"
PROTOCOL_MAX_PAGES = 40
DEFAULT_CATEGORIES = (
    "月度排行榜·言情",
    "月度排行榜·纯爱",
    "新晋作者榜·言情",
    "完结金榜·言情",
)
_SEPARATORS = ("•", "・", ":", "：", "/", "|", "—")


def _modules():
    bridge = Path(__file__).resolve().parents[1]
    bridge_text = str(bridge)
    if bridge_text not in sys.path:
        sys.path.insert(0, bridge_text)
    try:
        from jjwxc_app.http import JjwxcRankError
        from jjwxc_app.rank import (
            INDEX_ONLY_BOARDS,
            PAGE_SIZE,
            RANK_BOARD_NAMES,
            RANK_BOARDS,
            RANK_URL,
            fetch_rank_pages,
        )
    except ModuleNotFoundError as exc:
        name = exc.name or "jjwxc_app"
        raise RankFetchError(f"jjwxc missing module: {name}") from exc
    return {
        "error": JjwxcRankError,
        "index_only": INDEX_ONLY_BOARDS,
        "page_size": PAGE_SIZE,
        "names": RANK_BOARD_NAMES,
        "boards": RANK_BOARDS,
        "url": RANK_URL,
        "fetch_pages": fetch_rank_pages,
    }


def _label(text: str) -> str:
    value = "".join((text or "").split())
    for separator in _SEPARATORS:
        value = value.replace(separator, "·")
    return value


def _parents(names: dict[str, str]) -> dict[str, list[str]]:
    parents: dict[str, list[str]] = {}
    for label in names.values():
        board, _, genre = label.partition("·")
        if genre:
            parents.setdefault(board, []).append(genre)
    return parents


def resolve_jjwxc_category(category: str) -> str:
    modules = _modules()
    text = (category or "").strip()
    label = _label(text)
    if text in modules["index_only"] or label in modules["index_only"]:
        raise RankFetchError(f"jjwxc board has no channel tab: {text or label}")
    if text in modules["boards"]:
        return text
    for board_id, board_label in modules["names"].items():
        if board_label == text or board_label == label:
            return board_id
    parents = _parents(modules["names"])
    if label in parents:
        genres = "、".join(parents[label])
        raise RankFetchError(f"jjwxc board needs a genre: {label}（{genres}）")
    known = "、".join(DEFAULT_CATEGORIES)
    raise RankFetchError(f"jjwxc unknown rank: {category or '(empty)'}; examples: {known}")


def jjwxc_source(category: str) -> SourceSpec:
    modules = _modules()
    board_id = resolve_jjwxc_category(category)
    label = modules["names"][board_id]
    return SourceSpec(
        site_id="jjwxc",
        site_name="晋江",
        source_id=f"jjwxc-{label}",
        semantic_key=label,
        category=label,
        category_name=label,
        url=modules["url"],
        required_adapters=["jjwxc_app_rank"],
        known_risks=["book_page_metrics", "no_chapter_fallback", "page_cap_40"],
    )


def _note(result: Any, limit: int, pages_needed: int, page_size: int) -> str:
    if result.stop_reason == "short":
        return f"翻了 {result.page_count} 页，停在短页"
    if result.stop_reason == "duplicate":
        return f"翻了 {result.page_count} 页，停在重复页"
    if (
        pages_needed == PROTOCOL_MAX_PAGES
        and result.page_sizes
        and result.page_sizes[-1] == page_size
    ):
        return f"翻了 {result.page_count} 页，末页仍满，后面可能还有"
    return f"翻了 {result.page_count} 页，按请求保留 {min(limit, len(result.books))} 本"


def _apply_metrics(item: RankItem, metrics: Any) -> None:
    if metrics.word_count:
        item.word_count_text = metrics.word_count
        item.field_confidence["word_count_text"] = "verified"
    if metrics.favorite_count:
        item.extra["favorite_count"] = metrics.favorite_count
        item.field_confidence["favorite_count"] = "verified"
    if metrics.nutrition_count:
        item.extra["nutrition_count"] = metrics.nutrition_count
        item.field_confidence["nutrition_count"] = "verified"
    if metrics.score_count:
        item.extra["score_count"] = metrics.score_count
        item.field_confidence["score_count"] = "verified"


def _book_note(items: list[RankItem], client: Any) -> str:
    if client is None or not hasattr(client, "fetch_public"):
        return ""
    bridge = Path(__file__).resolve().parents[1]
    bridge_text = str(bridge)
    if bridge_text not in sys.path:
        sys.path.insert(0, bridge_text)
    from jjwxc_app.book import fetch_book_metrics
    from jjwxc_app.http import JjwxcRankError

    complete = 0
    partial = 0
    missed = 0
    for item in items:
        try:
            metrics = fetch_book_metrics(item.book_id, client=client)
        except (JjwxcRankError, ValueError):
            missed += 1
            continue
        _apply_metrics(item, metrics)
        filled = any((
            metrics.word_count,
            metrics.favorite_count,
            metrics.score_count,
            metrics.nutrition_count,
        ))
        if metrics.complete():
            complete += 1
        elif filled:
            partial += 1
        else:
            missed += 1
    if items and partial == 0 and missed == 0:
        return "作品页补了收藏、营养液、积分、字数"
    if complete == 0 and partial == 0:
        return "作品页没读到"
    return f"作品页 {complete} 本补全，{partial + missed} 本没读全"


def fetch_jjwxc_rank(category: str, limit: int, *, client: Any = None) -> RankSnapshot:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise RankFetchError("jjwxc limit must be at least 1")
    modules = _modules()
    source = jjwxc_source(category)
    board_id = resolve_jjwxc_category(category)
    page_size = modules["page_size"]
    pages_needed = min(PROTOCOL_MAX_PAGES, (limit + page_size - 1) // page_size)
    if client is None:
        bridge = Path(__file__).resolve().parents[1]
        bridge_text = str(bridge)
        if bridge_text not in sys.path:
            sys.path.insert(0, bridge_text)
        from jjwxc_app.http import JjwxcHttpClient

        client = JjwxcHttpClient()
    try:
        result = modules["fetch_pages"](board_id, max_pages=pages_needed, client=client)
    except modules["error"] as exc:
        raise RankFetchError(f"jjwxc rank failed: {exc}") from exc
    except ValueError as exc:
        raise RankFetchError(f"jjwxc rank failed: {exc}") from exc
    if not result.books:
        raise RankFetchError("jjwxc rank empty")
    still_full = (
        result.stop_reason == "cap"
        and pages_needed == PROTOCOL_MAX_PAGES
        and len(result.books) < limit
        and bool(result.page_sizes)
        and result.page_sizes[-1] == page_size
    )
    if still_full:
        raise RankFetchError("jjwxc rank still full at page cap")
    items: list[RankItem] = []
    for index, book in enumerate(result.books[:limit], start=1):
        items.append(RankItem(
            rank_position=index,
            book_id=book.novel_id,
            book_name=book.novel_name,
            author_name=book.author_name,
            book_url=f"https://www.jjwxc.net/onebook.php?novelid={book.novel_id}",
            field_confidence={"book_name": "verified"},
        ))
    notes = [_note(result, limit, pages_needed, page_size)]
    book_note = _book_note(items, client)
    if book_note:
        notes.append(book_note)
    return RankSnapshot(
        site=source.site_id,
        site_name=source.site_name,
        category=source.category,
        category_name=source.category_name,
        semantic_key=source.semantic_key,
        source_url=source.url,
        snapshot_at=now_cst_iso(),
        items=items,
        raw_ref="",
        parse_status="ok",
        source_notes=notes,
        parser_version=PARSER_VERSION,
    )
