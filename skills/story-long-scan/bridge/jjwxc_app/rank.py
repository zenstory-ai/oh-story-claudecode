"""JJWXC bookstore rank protocol.

Rank lists only. This module does not download chapters or open book pages.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

from .http import JjwxcHttpClient, assert_safe_android_request, build_android_headers

RANK_URL = "https://app-cdn.jjwxc.com/bookstore/getFullPageV1"
PAGE_SIZE = 20
RANK_INDEX_CHANNEL = "ranks"
RANK_INDEX_VERSION = "22"
INDEX_ONLY_BOARDS = ("作者积分榜", "TOP100")
# 目录榜名 -> 频道名 -> 榜单键。作者积分榜和 TOP100 没有频道键。
_RANK_TREE: dict[str, dict[str, str]] = {
    "月度排行榜": {
        "言情": "natural_592",
        "纯爱": "natural_604",
        "衍生": "natural_610",
        "无CP+": "natural_888",
        "百合": "natural_1043",
        "原创": "natural_598",
    },
    "季度排行榜": {
        "言情": "natural_593",
        "纯爱": "natural_605",
        "衍生": "natural_611",
        "无CP+": "natural_887",
        "百合": "natural_1042",
        "原创": "natural_599",
    },
    "半年排行榜": {
        "言情": "natural_594",
        "纯爱": "natural_606",
        "衍生": "natural_612",
        "无CP+": "natural_889",
        "百合": "natural_1044",
        "原创": "natural_600",
    },
    "新晋作者榜": {
        "言情": "natural_591",
        "纯爱": "natural_603",
        "衍生": "natural_609",
        "无CP+": "natural_890",
        "百合": "natural_1045",
        "原创": "natural_597",
    },
    "长生殿排行榜": {
        "言情": "natural_595",
        "纯爱": "natural_607",
        "衍生": "natural_613",
        "无CP+": "natural_891",
        "百合": "natural_1046",
        "原创": "natural_601",
    },
    "勤奋指数榜": {
        "言情": "natural_1477",
        "纯爱": "natural_1479",
        "衍生": "natural_1480",
        "无CP+": "natural_1481",
        "百合": "natural_1490",
        "原创": "natural_1478",
    },
    "完结金榜": {
        "言情": "natural_781",
        "纯爱": "natural_783",
        "衍生": "natural_784",
        "无CP+": "natural_896",
        "百合": "natural_1050",
        "原创": "natural_782",
    },
    "字数榜": {
        "言情": "natural_729",
        "纯爱": "natural_731",
        "衍生": "natural_732",
        "无CP+": "natural_895",
        "百合": "natural_1074",
        "原创": "natural_730",
    },
    "霸王票总榜": {
        "言情": "natural_725",
        "纯爱": "natural_727",
        "衍生": "natural_728",
        "无CP+": "natural_894",
        "百合": "natural_1049",
        "原创": "natural_726",
    },
    "读者栽培榜": {
        "言情": "natural_653",
        "纯爱": "natural_655",
        "衍生": "natural_656",
        "无CP+": "natural_893",
        "百合": "natural_1048",
        "原创": "natural_654",
    },
    "驻站作者榜": {
        "言情": "natural_590",
        "纯爱": "natural_602",
        "衍生": "natural_608",
        "无CP+": "natural_892",
        "百合": "natural_1047",
        "原创": "natural_596",
    },
    "总分榜": {
        "言情": "natural_828",
        "纯爱": "natural_830",
        "衍生": "natural_831",
        "无CP+": "natural_903",
        "百合": "natural_1052",
        "原创": "natural_829",
    },
    "作者积分榜": {},
    "TOP100": {},
}


def _catalog() -> tuple[frozenset[str], dict[str, str]]:
    names: dict[str, str] = {}
    for board, genres in _RANK_TREE.items():
        for genre, board_id in genres.items():
            names[board_id] = f"{board}·{genre}"
    return frozenset(names), names


RANK_BOARDS, RANK_BOARD_NAMES = _catalog()
_SUCCESS_CODE = "200"


class RankTransport(Protocol):
    def fetch(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class RankBook:
    novel_id: str
    novel_name: str
    author_name: str


@dataclass(frozen=True, slots=True)
class RankPage:
    channel_name: str
    books: tuple[RankBook, ...]


@dataclass(frozen=True, slots=True)
class RankPages:
    channel_name: str
    books: tuple[RankBook, ...]
    page_count: int
    stop_reason: str
    page_sizes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RankIndex:
    names: tuple[str, ...]
    tabs: tuple[tuple[str, str, str], ...]
    preview_counts: tuple[tuple[str, int], ...]


def _is_success_code(code: object) -> bool:
    if type(code) is str:
        return code == _SUCCESS_CODE
    return type(code) is int and code == 200


def _is_book_list(value: object) -> bool:
    # An empty list is a legal last page, not a missing payload.
    return isinstance(value, list) and all(
        isinstance(item, dict) for item in value
    )


def _channel_name_in(node: object) -> str:
    if isinstance(node, dict):
        found = _text(node.get("channelName"))
        if found:
            return found
        for value in node.values():
            found = _channel_name_in(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _channel_name_in(value)
            if found:
                return found
    return ""


def _blocks(data: object) -> list[object]:
    if isinstance(data, list):
        if not data:
            raise ValueError("rank data missing")
        return list(data)
    if isinstance(data, dict) and data:
        if "channelName" in data or isinstance(data.get("data"), list):
            return [data]
        if len(data) == 1:
            key, value = next(iter(data.items()))
            if _is_book_list(value):
                name = _channel_name_in(value) or _text(key)
                return [{"channelName": name, "data": value}]
        blocks = [
            value for value in data.values() if isinstance(value, dict)
        ]
        if blocks:
            return blocks
    raise ValueError("rank data missing")


def _require_board(board: str) -> None:
    if board not in RANK_BOARDS:
        raise ValueError(f"unknown rank board: {board}")


def _require_page_bounds(limit: int, offset: int) -> None:
    if isinstance(limit, bool) or limit != PAGE_SIZE:
        raise ValueError("rank limit must be 20")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("rank offset must be a non-negative integer")


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _book(item: object) -> RankBook | None:
    if not isinstance(item, dict):
        raise ValueError("rank book must be an object")
    novel_id = _text(item.get("novelId"))
    novel_name = _text(item.get("novelName"))
    author_name = _text(item.get("authorName"))
    if not novel_id or not novel_name or not author_name:
        return None
    return RankBook(
        novel_id=novel_id,
        novel_name=novel_name,
        author_name=author_name,
    )


def build_rank_url(
    board: str,
    *,
    limit: int = PAGE_SIZE,
    offset: int = 0,
) -> str:
    _require_board(board)
    _require_page_bounds(limit, offset)
    body = json.dumps(
        {board: {"limit": limit, "offset": offset}},
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return f"{RANK_URL}?{urlencode([('channelBody', body)])}"


def build_rank_index_url(*, version_first: bool = False) -> str:
    pairs = [
        ("channel", RANK_INDEX_CHANNEL),
        ("version", RANK_INDEX_VERSION),
    ]
    if version_first:
        pairs.reverse()
    return f"{RANK_URL}?{urlencode(pairs)}"


def parse_rank_index(payload: dict) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        raise ValueError("rank index payload must be an object")
    if not _is_success_code(payload.get("code")):
        raise ValueError("rank index code is not success")
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError("rank index data missing")
    names: list[str] = []
    for block in data:
        if not isinstance(block, dict):
            raise ValueError("rank index block must be an object")
        name = _text(block.get("channelName"))
        if not name:
            raise ValueError("rank index channel name missing")
        names.append(name)
    return tuple(sorted(names))


def parse_rank_tabs(payload: dict) -> tuple[tuple[str, str, str], ...]:
    if not isinstance(payload, dict):
        raise ValueError("rank index payload must be an object")
    if not _is_success_code(payload.get("code")):
        raise ValueError("rank index code is not success")
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError("rank index data missing")
    tabs: list[tuple[str, str, str]] = []
    for block in data:
        if not isinstance(block, dict):
            raise ValueError("rank index block must be an object")
        board = _text(block.get("channelName"))
        if not board:
            raise ValueError("rank index channel name missing")
        more = block.get("more")
        listing = more.get("channellist") if isinstance(more, dict) else None
        if not listing:
            continue
        if not isinstance(listing, list):
            raise ValueError("rank index channel list missing")
        for item in listing:
            if not isinstance(item, dict):
                raise ValueError("rank index tab must be an object")
            board_id = _text(item.get("channelid"))
            genre = _text(item.get("channel"))
            if not board_id.startswith("natural_") or not genre:
                raise ValueError("rank index tab is incomplete")
            tabs.append((board, genre, board_id))
    if not tabs:
        raise ValueError("rank index tabs missing")
    return tuple(tabs)


def parse_rank_page(payload: dict) -> RankPage:
    if not isinstance(payload, dict):
        raise ValueError("rank payload must be an object")
    if not _is_success_code(payload.get("code")):
        raise ValueError("rank code is not success")
    blocks = _blocks(payload.get("data"))

    channel_name = ""
    books: list[RankBook] = []
    for block in blocks:
        if not isinstance(block, dict):
            raise ValueError("rank block must be an object")
        if not channel_name:
            channel_name = (
                _text(block.get("channelName"))
                or _text(block.get("channelid"))
                or _text(block.get("natural_rank_id"))
            )
        items = block.get("data")
        if not isinstance(items, list):
            raise ValueError("rank book list missing")
        for item in items:
            book = _book(item)
            if book is not None:
                books.append(book)
    channel_name = RANK_BOARD_NAMES.get(channel_name, channel_name)
    if not channel_name:
        raise ValueError("rank data missing")
    if not books and any(
        isinstance(block.get("data"), list) and block.get("data")
        for block in blocks
        if isinstance(block, dict)
    ):
        raise ValueError("rank data missing")
    return RankPage(channel_name=channel_name, books=tuple(books))


def _preview_counts(payload: dict) -> tuple[tuple[str, int], ...]:
    data = payload.get("data")
    if not isinstance(data, list):
        return ()
    counts: list[tuple[str, int]] = []
    for block in data:
        if not isinstance(block, dict):
            continue
        name = _text(block.get("channelName"))
        items = block.get("data")
        counts.append((name, len(items) if isinstance(items, list) else 0))
    return tuple(counts)


def fetch_rank_index(
    *,
    client: RankTransport | None = None,
) -> RankIndex:
    url = build_rank_index_url()
    headers = build_android_headers()
    assert_safe_android_request(url, headers)
    transport = client if client is not None else JjwxcHttpClient()
    response = transport.fetch(url, headers=headers)
    if getattr(response, "status", None) != 200:
        raise ValueError("rank index http status is not 200")
    try:
        payload = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise ValueError("rank index response is not json") from exc
    return RankIndex(
        names=parse_rank_index(payload),
        tabs=parse_rank_tabs(payload),
        preview_counts=_preview_counts(payload),
    )


def fetch_rank(
    board: str,
    *,
    offset: int = 0,
    limit: int = PAGE_SIZE,
    client: RankTransport | None = None,
) -> RankPage:
    url = build_rank_url(board, limit=limit, offset=offset)
    headers = build_android_headers()
    assert_safe_android_request(url, headers)
    transport = client if client is not None else JjwxcHttpClient()
    response = transport.fetch(url, headers=headers)
    status = getattr(response, "status", None)
    if status != 200:
        raise ValueError("rank http status is not 200")
    try:
        payload = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise ValueError("rank response is not json") from exc
    return parse_rank_page(payload)


def fetch_rank_pages(
    board: str,
    *,
    # 新晋作者榜·衍生的榜尾在第 39 页；再留 2 页是 41，封顶 40。
    max_pages: int = 40,
    client: RankTransport | None = None,
) -> RankPages:
    _require_board(board)
    if (
        isinstance(max_pages, bool)
        or not isinstance(max_pages, int)
        or max_pages < 1
    ):
        raise ValueError("rank max_pages must be a positive integer")
    transport = client if client is not None else JjwxcHttpClient()
    books: list[RankBook] = []
    seen: set[str] = set()
    page_sizes: list[int] = []
    channel_name = ""
    reason = "cap"
    for index in range(max_pages):
        page = fetch_rank(
            board,
            offset=index * PAGE_SIZE,
            limit=PAGE_SIZE,
            client=transport,
        )
        if not channel_name:
            channel_name = page.channel_name
        novel_ids = [book.novel_id for book in page.books]
        if novel_ids and all(novel_id in seen for novel_id in novel_ids):
            reason = "duplicate"
            break
        for book in page.books:
            if book.novel_id in seen:
                continue
            seen.add(book.novel_id)
            books.append(book)
        page_sizes.append(len(page.books))
        if len(page.books) < PAGE_SIZE:
            reason = "short"
            break
    return RankPages(
        channel_name=channel_name,
        books=tuple(books),
        page_count=len(page_sizes),
        stop_reason=reason,
        page_sizes=tuple(page_sizes),
    )
