from __future__ import annotations

import json
import re
from html import unescape
from typing import Any

from .contracts import ParseResult, RankFetchError, RankItem, RankSnapshot, SourceSpec
from .http_client import fetch_text
from .textutil import now_cst_iso

PARSER_VERSION = "qidian_mobile_rank_ssr_v1"
IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
REFERER = "https://m.qidian.com/rank/"
SCRIPT_RE = re.compile(
    r"<script[^>]+id=[\"']vite-plugin-ssr_pageContext[\"'][^>]*>(.*?)</script>",
    re.I | re.S,
)

# route, short file label, semantic key.
# mobile-newsign shares newbook with mobile-pubnewbook.
# The two female aliases stay resolvable, but the open mobile host no longer serves them.
MOBILE_RANK_ROUTES: dict[str, tuple[str, str, str]] = {
    "mobile-yuepiao": ("yuepiao", "月票榜", "yuepiao"),
    "mobile-hotsales": ("hotsales", "畅销榜", "hotsales"),
    "mobile-readindex": ("readindex", "阅读指数榜", "readindex"),
    "mobile-newfans": ("newfans", "书友榜", "newfans"),
    "mobile-recom": ("rec", "推荐榜", "recom"),
    "mobile-vipup": ("update", "更新榜", "vipup"),
    "mobile-signnewbook": ("sign", "签约作者新书榜", "signnewbook"),
    "mobile-pubnewbook": ("newbook", "公众作者新书榜", "pubnewbook"),
    "mobile-newsign": ("newbook", "新人签约新书榜", "newsign"),
    "mobile-newauthor": ("newauthor", "新人作者新书榜", "newauthor"),
    "mobile-mm": ("female", "女生精选榜", "mm"),
    "mobile-mm-yuepiao": ("female", "女生月票榜", "mm-yuepiao"),
}

ROUTE_ALIASES = {
    "yuepiao": "mobile-yuepiao",
    "m-yuepiao": "mobile-yuepiao",
    "hotsales": "mobile-hotsales",
    "readindex": "mobile-readindex",
    "newfans": "mobile-newfans",
    "recom": "mobile-recom",
    "rec": "mobile-recom",
    "vipup": "mobile-vipup",
    "update": "mobile-vipup",
    "signnewbook": "mobile-signnewbook",
    "sign": "mobile-signnewbook",
    "pubnewbook": "mobile-pubnewbook",
    "newbook": "mobile-pubnewbook",
    "newsign": "mobile-newsign",
    "newauthor": "mobile-newauthor",
    "mm": "mobile-mm",
    "female": "mobile-mm",
    "mm-yuepiao": "mobile-mm-yuepiao",
    "female-yuepiao": "mobile-mm-yuepiao",
}

DEFAULT_CATEGORIES = ("yuepiao", "hotsales", "readindex")


def resolve_qidian_category(value: str) -> str:
    token = (value or "").strip().lower().replace("_", "-")
    if token in MOBILE_RANK_ROUTES:
        return token
    if token in ROUTE_ALIASES:
        return ROUTE_ALIASES[token]
    raise RankFetchError(f"qidian category unsupported: {value}")


def qidian_source(category: str) -> SourceSpec:
    alias = resolve_qidian_category(category)
    route, label, semantic = MOBILE_RANK_ROUTES[alias]
    return SourceSpec(
        site_id="qidian",
        site_name="起点中文网",
        source_id=f"qidian_{alias}",
        semantic_key=semantic,
        category=alias,
        category_name=label,
        url=f"https://m.qidian.com/rank/{route}/",
        required_adapters=["qidian_mobile_rank_ssr_parser"],
        known_risks=["rankCnt is a site metric and is not a read count"],
    )


def _page_context(html: str) -> dict[str, Any]:
    match = SCRIPT_RE.search(html or "")
    if not match:
        raise ValueError("ssr_marker_missing")
    raw = unescape(match.group(1)).strip()
    if not raw:
        raise ValueError("ssr_json_empty")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ssr_json_decode_failed:{exc}") from exc
    page_context = payload.get("pageContext", payload)
    if not isinstance(page_context, dict):
        raise ValueError("page_context_missing")
    page_props = page_context.get("pageProps")
    if not isinstance(page_props, dict):
        raise ValueError("page_props_missing")
    page_data = page_props.get("pageData")
    if not isinstance(page_data, dict):
        raise ValueError("page_data_missing")
    return page_data


def parse_qidian_mobile_rank_ssr(html: str, *, category: str = "mobile-yuepiao", limit: int = 20) -> ParseResult:
    try:
        page_data = _page_context(html)
    except ValueError as exc:
        code = str(exc).split(":", 1)[0]
        return ParseResult(ok=False, failure_code=code, failure_detail=str(exc), parser_version=PARSER_VERSION)
    records = page_data.get("records")
    if not isinstance(records, list):
        return ParseResult(
            ok=False,
            failure_code="book_list_missing",
            failure_detail="pageData.records missing or not list",
            parser_version=PARSER_VERSION,
        )
    if not records:
        return ParseResult(
            ok=False,
            failure_code="book_list_empty",
            failure_detail="pageData.records is empty",
            parser_version=PARSER_VERSION,
        )
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(records[:limit], start=1):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        rank_num = item.get("rankNum")
        item["_rank_position"] = int(rank_num) if isinstance(rank_num, int) or str(rank_num).isdigit() else index
        item["_list_name"] = "records"
        item["_mobile_rank_metric"] = True
        items.append(item)
    if not items:
        return ParseResult(
            ok=False,
            failure_code="item_parse_failed",
            failure_detail="no dict item parsed from pageData.records",
            parser_version=PARSER_VERSION,
        )
    notes = ["qidian_mobile_rank_ssr_page_context", "qidian_mobile_ssr_list:records", "qidian_mobile_rank_metric_not_read_count"]
    if not any(str(item.get("rankCnt") or "").strip() for item in items):
        notes.append("qidian_mobile_rank_count_missing")
    label = MOBILE_RANK_ROUTES.get(category, ("", "起点移动排行榜", ""))[1]
    return ParseResult(ok=True, items=items, category_name=label, parser_version=PARSER_VERSION, source_notes=notes)


def _text(value: object) -> str:
    return str(value or "").strip()


def normalize_qidian_mobile(source: SourceSpec, parse_result: ParseResult) -> RankSnapshot:
    items: list[RankItem] = []
    notes = list(parse_result.source_notes)
    if parse_result.ok and not any(_text(raw.get("rankCnt")) for raw in parse_result.items):
        notes.append("qidian_mobile_rank_count_missing")
    for index, raw in enumerate(parse_result.items, start=1):
        rank_position = int(raw.get("_rank_position") or raw.get("rankNum") or index)
        book_id = _text(raw.get("bid") or f"qidian-{rank_position}")
        book_name = _text(raw.get("bName"))
        author_name = _text(raw.get("bAuth"))
        description = _text(raw.get("desc"))
        word_count = _text(raw.get("cnt"))
        category_text = _text(raw.get("cat")) or source.category_name
        rank_count = _text(raw.get("rankCnt"))
        items.append(RankItem(
            rank_position=rank_position,
            book_id=book_id,
            book_name=book_name,
            author_name=author_name,
            book_url=f"https://book.qidian.com/info/{book_id}/" if book_id else "",
            description=description,
            category_text=category_text,
            score_text=rank_count,
            word_count_text=word_count,
            status=_text(raw.get("state")),
            tags=[category_text] if category_text and category_text != source.category_name else [],
            extra={
                "sub_cat": raw.get("subCat", ""),
                "rank_count": raw.get("rankCnt", ""),
            },
            field_confidence={
                "book_name": "verified" if book_name else "missing",
                "author_name": "verified" if author_name else "missing",
                "score_text": "verified" if rank_count else "missing",
                "word_count_text": "verified" if word_count else "missing",
            },
        ))
    return RankSnapshot(
        site=source.site_id,
        site_name=source.site_name,
        category=source.category,
        category_name=parse_result.category_name or source.category_name,
        semantic_key=source.semantic_key,
        source_url=source.url,
        snapshot_at=now_cst_iso(),
        items=items,
        raw_ref="",
        parse_status="ok" if parse_result.ok else parse_result.failure_code,
        source_notes=sorted(set(notes)),
        parser_version=parse_result.parser_version,
    )


_FEMALE_CLOSED = {"mobile-mm", "mobile-mm-yuepiao"}


def fetch_qidian_mobile(category: str, limit: int = 20) -> RankSnapshot:
    if limit < 1:
        raise RankFetchError("qidian limit must be at least 1")
    alias = resolve_qidian_category(category)
    if alias in _FEMALE_CLOSED:
        raise RankFetchError(
            "qidian female rank unavailable: "
            f"{alias} is not on the open mobile rank host, and the mm host returns an anti-bot page"
        )
    source = qidian_source(category)
    response = fetch_text(source.url, headers={
        "Referer": REFERER,
        "User-Agent": IPHONE_UA,
        "Accept-Encoding": "gzip",
    })
    if response.error or response.status != 200 or not response.text:
        raise RankFetchError(
            f"qidian request failed: category={source.category} status={response.status} error={response.error or 'empty'}"
        )
    parsed = parse_qidian_mobile_rank_ssr(response.text, category=source.category, limit=limit)
    if not parsed.ok:
        raise RankFetchError(
            f"qidian parse failed: category={source.category} code={parsed.failure_code} detail={parsed.failure_detail}"
        )
    snapshot = normalize_qidian_mobile(source, parsed)
    if not snapshot.items or any(not item.book_name for item in snapshot.items):
        raise RankFetchError(f"qidian missing field: book_name category={source.category}")
    return snapshot
