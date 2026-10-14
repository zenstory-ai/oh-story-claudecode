from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from .contracts import ParseResult, RankFetchError, RankItem, RankSnapshot, SourceSpec
from .textutil import extract_json_object_after_marker, has_private_use_chars, now_cst_iso

PARSER_VERSION = "fanqie_initial_state_v2"
STATE_MARKER = "window.__INITIAL_STATE__"
BASE_URL = "https://fanqienovel.com/rank"
BASE_PAGE = "https://fanqienovel.com/"
LANDING_SOURCE_URL = (
    "https://api5-normal-sinfonlinea.fqnovel.com/reading/bookapi/new_category/landing/v:version/"
)
_CATEGORY_PATTERN = re.compile(r"^[01]_[123]_\d+$")
CHECKED_FIELDS = ("book_name", "author_name", "description")
RISING_BOOK_STATUS = 1
RISING_WORD_NUMBER = 4
RISING_WORD_LIMIT = 300_000


@dataclass(frozen=True, slots=True)
class FanqieGenre:
    slug: str
    name: str
    category_id: str
    gender: str


MALE_GENRES: tuple[FanqieGenre, ...] = (
    FanqieGenre("xifangqihuan", "西方奇幻", "1141", "male"),
    FanqieGenre("dongfangxianxia", "东方仙侠", "1140", "male"),
    FanqieGenre("kehuanmoshi", "科幻末世", "8", "male"),
    FanqieGenre("dushirichang", "都市日常", "261", "male"),
    FanqieGenre("dushixiuzhen", "都市修真", "124", "male"),
    FanqieGenre("dushigaowu", "都市高武", "1014", "male"),
    FanqieGenre("lishigudai", "历史古代", "273", "male"),
    FanqieGenre("zhanshenzhuixu", "战神赘婿", "27", "male"),
    FanqieGenre("dushizhongtian", "都市种田", "263", "male"),
    FanqieGenre("chuantongxuanhuan", "传统玄幻", "258", "male"),
    FanqieGenre("lishinaodong", "历史脑洞", "272", "male"),
    FanqieGenre("xuanyinaodong", "悬疑脑洞", "539", "male"),
    FanqieGenre("dushinaodong", "都市脑洞", "262", "male"),
    FanqieGenre("xuanhuanaodong", "玄幻脑洞", "257", "male"),
    FanqieGenre("xuanyilingyi", "悬疑灵异", "751", "male"),
    FanqieGenre("kangzhandiezhan", "抗战谍战", "504", "male"),
    FanqieGenre("youxitiyu", "游戏体育", "746", "male"),
    FanqieGenre("dongmanyansheng", "动漫衍生", "718", "male"),
    FanqieGenre("nanpinyansheng", "男频衍生", "1016", "male"),
)

FEMALE_GENRES: tuple[FanqieGenre, ...] = (
    FanqieGenre("gufengshiqing", "古风世情", "1139", "female"),
    FanqieGenre("kehuanmoshi", "科幻末世", "8", "female"),
    FanqieGenre("youxitiyu", "游戏体育", "746", "female"),
    FanqieGenre("nvpinyansheng", "女频衍生", "1015", "female"),
    FanqieGenre("xuanhuanyanqing", "玄幻言情", "248", "female"),
    FanqieGenre("zhongtian", "种田", "23", "female"),
    FanqieGenre("niandai", "年代", "79", "female"),
    FanqieGenre("xianyannaodong", "现言脑洞", "267", "female"),
    FanqieGenre("gongdouzhairdou", "宫斗宅斗", "246", "female"),
    FanqieGenre("xuanyinaodong", "悬疑脑洞", "539", "female"),
    FanqieGenre("guyannaodong", "古言脑洞", "253", "female"),
    FanqieGenre("kuaichuan", "快穿", "24", "female"),
    FanqieGenre("qingchuntianchong", "青春甜宠", "749", "female"),
    FanqieGenre("xingguangcuican", "星光璀璨", "745", "female"),
    FanqieGenre("nvpianxuanyi", "女频悬疑", "747", "female"),
    FanqieGenre("zhichanghunlian", "职场婚恋", "750", "female"),
    FanqieGenre("haomenzongcai", "豪门总裁", "748", "female"),
    FanqieGenre("minguoyanqing", "民国言情", "1017", "female"),
)

RANK_TYPES = {
    "hot": {"code": "2", "name": "热门", "sort_by": 24},
    "read": {"code": "2", "name": "热门", "sort_by": 24},
    "reading": {"code": "2", "name": "热门", "sort_by": 24},
    "new": {"code": "1", "name": "最新", "sort_by": 76},
    "newbook": {"code": "1", "name": "最新", "sort_by": 76},
    "rising": {"code": "3", "name": "新书", "sort_by": 24},
}
GENDERS = {"male": "1", "m": "1", "nan": "1", "female": "0", "f": "0", "nv": "0"}
GENDER_NAMES = {"1": "男频", "0": "女频"}
GENRES_BY_GENDER = {"1": MALE_GENRES, "0": FEMALE_GENRES}
DEFAULT_CATEGORIES = (
    "male-hot-xifangqihuan",
    "male-newbook-xifangqihuan",
    "female-hot-gufengshiqing",
    "female-newbook-gufengshiqing",
)


def _norm(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def resolve_fanqie_category(value: str) -> str:
    token_value = (value or "").strip()
    if not token_value:
        raise RankFetchError("fanqie category missing")
    if _CATEGORY_PATTERN.match(token_value):
        return token_value
    parts = [part for part in _norm(token_value).split("-") if part]
    gender_code = "1"
    rank_key = "hot"
    genre_slug = ""
    for part in parts:
        if part in GENDERS:
            gender_code = GENDERS[part]
        elif part in RANK_TYPES:
            if part in {"new", "newbook"}:
                rank_key = "newbook"
            elif part == "rising":
                rank_key = "rising"
            else:
                rank_key = "hot"
        else:
            genre_slug = part
    if not genre_slug:
        raise RankFetchError(f"fanqie category unsupported: {value}")
    for genre in GENRES_BY_GENDER[gender_code]:
        if genre.slug == genre_slug or genre.category_id == genre_slug or _norm(genre.name) == genre_slug:
            return f"{gender_code}_{RANK_TYPES[rank_key]['code']}_{genre.category_id}"
    raise RankFetchError(f"fanqie category unsupported: {value}")


def _rank_key_from_code(rank_code: str) -> str:
    if rank_code == "1":
        return "newbook"
    if rank_code == "3":
        return "rising"
    return "hot"


def fanqie_source(category: str) -> SourceSpec:
    resolved = resolve_fanqie_category(category)
    gender_code, rank_code, genre_id = resolved.split("_", 2)
    rank_key = _rank_key_from_code(rank_code)
    genre = next((item for item in GENRES_BY_GENDER.get(gender_code, ()) if item.category_id == genre_id), None)
    rank = RANK_TYPES[rank_key]
    genre_name = genre.name if genre else genre_id
    if rank_key == "rising":
        risks = [
            "rising is per-genre serializing under-300k by heat via category landing; not the web library cross-genre list; chapter download is not used",
        ]
    else:
        risks = ["category landing is 热门/最新, not the web rank font page; chapter download is not used"]
    return SourceSpec(
        site_id="fanqie",
        site_name="番茄小说",
        source_id=f"fanqie_{resolved}",
        semantic_key=f"{'male' if gender_code == '1' else 'female'}-{rank_key}",
        category=resolved,
        category_name=f"{GENDER_NAMES[gender_code]}{rank['name']} / {genre_name}",
        url=LANDING_SOURCE_URL,
        required_adapters=["fanqie_app_category_landing"],
        known_risks=risks,
    )


def _is_identifier_char(ch: str) -> bool:
    return ch == "_" or ch.isalnum()


def _replace_js_undefined(text: str) -> tuple[str, int]:
    out: list[str] = []
    in_string = False
    escape = False
    replacements = 0
    index = 0
    while index < len(text):
        ch = text[index]
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            index += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            index += 1
            continue
        if text.startswith("undefined", index):
            before = text[index - 1] if index else ""
            after_index = index + len("undefined")
            after = text[after_index] if after_index < len(text) else ""
            if not _is_identifier_char(before) and not _is_identifier_char(after):
                out.append("null")
                replacements += 1
                index = after_index
                continue
        out.append(ch)
        index += 1
    return "".join(out), replacements


def parse_fanqie_initial_state(html: str, limit: int = 20) -> ParseResult:
    if STATE_MARKER not in html:
        return ParseResult(
            ok=False,
            failure_code="state_marker_missing",
            failure_detail="window.__INITIAL_STATE__ not found",
            parser_version=PARSER_VERSION,
        )
    try:
        state_json = extract_json_object_after_marker(html, STATE_MARKER)
    except ValueError as exc:
        return ParseResult(
            ok=False,
            failure_code=str(exc),
            failure_detail="failed to extract state JSON object",
            parser_version=PARSER_VERSION,
        )
    state_json, undefined_replacements = _replace_js_undefined(state_json)
    notes = [f"fanqie_js_undefined_to_null:{undefined_replacements}"] if undefined_replacements else []
    try:
        state = json.loads(state_json)
    except json.JSONDecodeError as exc:
        return ParseResult(
            ok=False,
            failure_code="state_json_decode_failed",
            failure_detail=str(exc),
            parser_version=PARSER_VERSION,
            source_notes=notes,
        )
    rank_node = state.get("rank")
    if not isinstance(rank_node, dict):
        return ParseResult(ok=False, failure_code="rank_node_missing", failure_detail="state.rank missing", parser_version=PARSER_VERSION)
    book_list = rank_node.get("book_list")
    if not isinstance(book_list, list) or not book_list:
        code = "book_list_empty" if isinstance(book_list, list) else "book_list_missing"
        return ParseResult(ok=False, failure_code=code, failure_detail="rank.book_list unusable", parser_version=PARSER_VERSION)
    items: list[dict[str, Any]] = []
    for index, raw_item in enumerate(book_list[:limit], start=1):
        if not isinstance(raw_item, dict):
            continue
        item = dict(raw_item)
        item["_rank_position"] = index
        items.append(item)
    if not items:
        return ParseResult(ok=False, failure_code="item_parse_failed", failure_detail="no dict item", parser_version=PARSER_VERSION)
    return ParseResult(
        ok=True,
        items=items,
        category_name=str(rank_node.get("rankTypeText") or "").strip(),
        parser_version=PARSER_VERSION,
        source_notes=notes,
    )


def _plain(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _creation_status(value: object) -> str:
    if value in ("0", 0):
        return "已完结"
    if value in ("1", 1):
        return "连载中"
    return str(value) if value is not None else ""


def _timestamp(value: object) -> str:
    if not value:
        return ""
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return str(value)


_BRACKET_TAGS = re.compile(r"【([^【】]+)】")
_TAG_SPLIT = re.compile(r"[+＋、，,/|｜]+")


def _selling_tags(description: str) -> list[str]:
    found: list[str] = []
    for inner in _BRACKET_TAGS.findall(description):
        for part in _TAG_SPLIT.split(inner):
            tag = part.strip()
            if not tag or has_private_use_chars(tag) or tag in found:
                continue
            found.append(tag)
    return found


def normalize_fanqie(source: SourceSpec, parse_result: ParseResult) -> RankSnapshot:
    items: list[RankItem] = []
    for index, raw in enumerate(parse_result.items, start=1):
        rank_position = int(raw.get("_rank_position") or raw.get("currentPos") or index)
        book_id = _plain(raw.get("bookId") or raw.get("book_id")) or f"fanqie-{rank_position}"
        book_name = _plain(raw.get("bookName") or raw.get("book_name") or raw.get("original_book_name"))
        author_name = _plain(raw.get("author") or raw.get("author_name"))
        description = _plain(raw.get("abstract") or raw.get("book_abstract_v2"))
        category = _plain(raw.get("category"))
        category_v2 = _plain(raw.get("categoryV2"))
        read_count = _plain(raw.get("read_count") or raw.get("readCount") or raw.get("read_cnt_text"))
        word_number = _plain(raw.get("wordNumber") or raw.get("word_number"))
        items.append(RankItem(
            rank_position=rank_position,
            book_id=book_id,
            book_name=book_name,
            author_name=author_name,
            book_url=urljoin(BASE_PAGE, f"page/{book_id}"),
            cover_url=_plain(raw.get("thumbUri") or raw.get("thumb_url") or raw.get("thumb_uri")),
            description=description,
            category_text=" / ".join(part for part in (category, category_v2) if part),
            score_text=f"在读：{read_count}" if read_count else "",
            word_count_text=word_number,
            status=_creation_status(raw.get("creationStatus", raw.get("creation_status"))),
            tags=_selling_tags(description),
            latest_chapter=_plain(raw.get("lastChapterTitle") or raw.get("last_chapter_title")),
            latest_update_time=_timestamp(raw.get("lastChapterUpdateTime")),
            extra={"read_count": read_count},
            field_confidence={
                "book_name": "polluted" if has_private_use_chars(book_name) else ("verified" if book_name else "missing"),
                "author_name": "polluted" if has_private_use_chars(author_name) else ("verified" if author_name else "missing"),
                "description": "polluted" if has_private_use_chars(description) else ("verified" if description else "missing"),
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
        source_notes=list(parse_result.source_notes),
        parser_version=parse_result.parser_version,
    )


def polluted_fields(snapshot: RankSnapshot) -> list[str]:
    found: list[str] = []
    for item in snapshot.items:
        for field_name in CHECKED_FIELDS:
            value = getattr(item, field_name)
            if value and has_private_use_chars(value):
                found.append(f"{item.book_id}:{field_name}")
            elif field_name == "book_name" and not value:
                found.append(f"{item.book_id}:book_name")
    return found


_CLIENT: Any = None


def _fanqie_client() -> Any:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    root = Path(__file__).resolve().parents[1] / "fanqie_app"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from fanqie_client import FanqieClient
    except ModuleNotFoundError as exc:
        raise RankFetchError(f"fanqie missing module: {exc.name}") from None
    try:
        _CLIENT = FanqieClient()
    except Exception as exc:
        raise RankFetchError(f"fanqie request failed: {type(exc).__name__}") from None
    return _CLIENT


def _walk_books(node: object, found: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        book_id = _plain(node.get("book_id") or node.get("id"))
        book_name = _plain(node.get("book_name") or node.get("original_book_name"))
        if book_id and book_name:
            found.append(node)
            return
        for value in node.values():
            _walk_books(value, found)
    elif isinstance(node, list):
        for item in node:
            _walk_books(item, found)


def _landing_books(
    category_id: str,
    *,
    sort_by: int,
    query_gender: int,
    limit: int,
    book_status: int | None = None,
    word_number: int | None = None,
    client: Any = None,
) -> list[dict[str, Any]]:
    client = client or _fanqie_client()
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    offset = 0
    while len(collected) < limit:
        page_limit = min(30, limit - len(collected))
        kwargs: dict[str, Any] = {
            "offset": offset,
            "limit": page_limit,
            "sort_by": sort_by,
            "query_gender": query_gender,
        }
        if book_status is not None:
            kwargs["book_status"] = book_status
        if word_number is not None:
            kwargs["word_number"] = word_number
        try:
            payload = client.category_landing(category_id, **kwargs)
        except Exception as exc:
            raise RankFetchError(f"fanqie request failed: {type(exc).__name__}") from None
        page: list[dict[str, Any]] = []
        _walk_books(payload, page)
        fresh = 0
        for book in page:
            book_id = _plain(book.get("book_id") or book.get("id"))
            if not book_id or book_id in seen:
                continue
            seen.add(book_id)
            collected.append(book)
            fresh += 1
            if len(collected) >= limit:
                break
        if fresh == 0 or fresh < page_limit:
            break
        offset += fresh
    return collected[:limit]


def _pure_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return None


def rising_book_eligible(book: dict[str, Any]) -> bool:
    """Keep a rising row only when it is explicitly serial and under 300000 words."""
    if "creation_status" in book:
        status = book.get("creation_status")
    elif "creationStatus" in book:
        status = book.get("creationStatus")
    else:
        return False
    if isinstance(status, bool) or status not in ("1", 1):
        return False
    words: int | None = None
    for key in ("word_number", "wordNumber"):
        if key not in book:
            continue
        parsed = _pure_int(book.get(key))
        if parsed is not None:
            words = parsed
            break
    if words is None:
        return False
    return words < RISING_WORD_LIMIT


def fetch_fanqie_rank(category: str, limit: int = 20, *, client: Any = None) -> RankSnapshot:
    if limit < 1:
        raise RankFetchError("fanqie limit must be at least 1")
    source = fanqie_source(category)
    gender_code, rank_code, genre_id = source.category.split("_", 2)
    rank_key = _rank_key_from_code(rank_code)
    sort_by = RANK_TYPES[rank_key]["sort_by"]
    query_gender = 0 if gender_code == "0" else 1
    book_status = RISING_BOOK_STATUS if rank_key == "rising" else None
    word_number = RISING_WORD_NUMBER if rank_key == "rising" else None
    books = _landing_books(
        genre_id,
        sort_by=sort_by,
        query_gender=query_gender,
        limit=limit,
        book_status=book_status,
        word_number=word_number,
        client=client,
    )
    if rank_key == "rising":
        books = [book for book in books if rising_book_eligible(book)]
    if not books:
        raise RankFetchError(f"fanqie book_list_empty: category={source.category}")
    items: list[dict[str, Any]] = []
    for index, book in enumerate(books, start=1):
        item = dict(book)
        item["_rank_position"] = index
        items.append(item)
    if rank_key == "rising":
        parser_version = "fanqie_app_category_landing_v2"
        source_notes = [
            "fanqie_app_category_landing",
            "rising:serializing under-300k by heat, not category 最新, not web library all-genre",
            f"sort_by:{sort_by}",
            f"query_gender:{query_gender}",
            f"book_status:{book_status}",
            f"word_number:{word_number}",
        ]
    else:
        parser_version = "fanqie_app_category_landing_v1"
        source_notes = ["fanqie_app_category_landing", f"sort_by:{sort_by}", f"query_gender:{query_gender}"]
    parsed = ParseResult(
        ok=True,
        items=items,
        category_name=source.category_name,
        parser_version=parser_version,
        source_notes=source_notes,
    )
    snapshot = normalize_fanqie(source, parsed)
    bad = polluted_fields(snapshot)
    if bad:
        raise RankFetchError("fanqie missing or private-use field: " + ",".join(bad))
    return snapshot
