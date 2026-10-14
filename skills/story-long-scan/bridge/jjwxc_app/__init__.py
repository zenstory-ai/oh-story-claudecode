"""JJWXC bookstore rank client. Ranks plus public book-page counts; no chapter download."""

from .rank import (
    INDEX_ONLY_BOARDS,
    PAGE_SIZE,
    RANK_BOARD_NAMES,
    RANK_BOARDS,
    build_rank_index_url,
    build_rank_url,
    fetch_rank,
    fetch_rank_index,
    fetch_rank_pages,
    parse_rank_index,
    parse_rank_page,
    parse_rank_tabs,
)

__all__ = [
    "INDEX_ONLY_BOARDS",
    "PAGE_SIZE",
    "RANK_BOARD_NAMES",
    "RANK_BOARDS",
    "build_rank_index_url",
    "build_rank_url",
    "fetch_rank",
    "fetch_rank_index",
    "fetch_rank_pages",
    "parse_rank_index",
    "parse_rank_page",
    "parse_rank_tabs",
]
