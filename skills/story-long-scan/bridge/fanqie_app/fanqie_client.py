"""Non-persistent Python workflow client matching the Rust application layer."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import re
import secrets
import time
import sys
import urllib.parse
import uuid
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from fanqie_pure import (
    APPLOG_KEY_MATERIAL,
    APPLOG_MAGIC,
    SignInput,
    aes128_cbc_encrypt,
    applog_pack_decrypt,
    decrypt_chapter_text,
    extract_text,
    find_normalized_khronos,
    raw_query,
    sign_headers,
    unwrap_server_key,
)

HOST = "https://api5-normal-sinfonlinea.fqnovel.com"
USER_AGENT = "Reading 7.2.1 rv:7.2.1.32 (iPad; iOS 26.5; zh_CN) Cronet"
ORIGIN_KEY_DATA = bytes.fromhex("ac25c67ddd8f38c1b37a2348828e222e")
REGISTER_URL = "https://log.snssdk.com/service/2/device_register/?tt_data=a"
IMPERSONATE = "safari"
CATEGORY_LANDING_PATHS = (
    "/reading/bookapi/new_category/landing/v:version/",
    "/reading/bookapi/new_category/landing/v/",
)
CATEGORY_FRONT_PATHS = (
    "/reading/bookapi/new_category/front/v:version/",
    "/reading/bookapi/new_category/front/v/",
)
MALL_CELL_PATHS = (
    "/reading/bookapi/bookmall/cell/change/v:version/",
    "/reading/bookapi/bookmall/cell/change/v1/",
    "/reading/bookapi/bookmall/cell/change/v/",
)
MALL_TAB_PATHS = (
    "/reading/bookapi/bookmall/tab/v:version/",
    "/reading/bookapi/bookmall/tab/v/",
    "/reading/bookapi/bookmall/tab/v",
)
CATEGORY_DAILY_RANKLIST_PATHS = (
    "/reading/bookapi/category_daily_ranklist/v:version/",
    "/reading/bookapi/category_daily_ranklist/v/",
)
RANKLIST_SEQUENCE_PATHS = (
    "/reading/bookapi/ranklist/sequence/v:version/",
    "/reading/bookapi/ranklist/sequence/v/",
)
RANKLIST_RANDOM_PATHS = (
    "/reading/bookapi/ranklist/random/v:version/",
    "/reading/bookapi/ranklist/random/v/",
)
RANK_ALGO = {
    "recommend": 101,
    "complete": 100,
    "dianfeng": 200,
    "fanqie": 104,
    "read": 111,
    "score": 115,
    "follow": 109,
    "comment": 110,
    "darkhorse": 102,
    "hot_search": 103,
}
RANK_ALGO_VALUES = frozenset(RANK_ALGO.values())
RANK_ALGO_EXTRA = {
    "new_book": 108,
    "end_category": 116,
    "hot_read_category": 135,
    "guess_you_like": 167,
}
RANK_SUB_TAB = {
    "dianfeng_monthly": 1,
    "dianfeng_first": 2,
    "dianfeng_potential": 3,
    "dianfeng_female": 4,
    "dianfeng_male": 5,
}
DEFAULT_MALL_CELL_ID = "7098235271900037133"


@dataclass(frozen=True)
class SearchResult:
    book_id: str
    title: str
    author: str = ""
    category: str = ""
    chapter_count: int | None = None
    score: str = ""


@dataclass(frozen=True)
class RankItem:
    book_id: str
    title: str
    author: str = ""
    category: str = ""
    score: str = ""
    rank_score: str = ""
    position: int | None = None


@dataclass(frozen=True)
class MallCell:
    cell_id: str
    name: str = ""
    algo_type: int | None = None
    book_count: int = 0
    tab_title: str = ""


@dataclass(frozen=True)
class ChapterRef:
    item_id: str
    title: str = ""
    order: int | None = None


@dataclass(frozen=True)
class BookInfo:
    book_id: str
    book_name: str
    author: str
    abstract_text: str
    chapters: tuple[ChapterRef, ...]


@dataclass(frozen=True)
class SessionKey:
    key: bytes
    keyver: int


@dataclass(frozen=True)
class DownloadReport:
    book: BookInfo
    destination: Path
    attempted: int
    succeeded: int
    failures: tuple[str, ...]
    key_version: int | None


@dataclass(frozen=True)
class HttpResult:
    status: int
    content: bytes
    content_type: str = ""
    url: str = ""


def _gzip(data: bytes) -> bytes:
    encoder = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    compressed = encoder.compress(data) + encoder.flush()
    header = bytes.fromhex("1f8b0800000000000000")
    return header + compressed + (zlib.crc32(data) & 0xFFFFFFFF).to_bytes(4, "little") + len(data).to_bytes(4, "little")


def _response(response: object) -> bytes:
    raw = response.read()  # type: ignore[attr-defined]
    encoding = response.headers.get("Content-Encoding", "").lower()  # type: ignore[attr-defined]
    if "gzip" in encoding or raw.startswith(b"\x1f\x8b"):
        return gzip.decompress(raw)
    if "deflate" in encoding:
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    if "br" in encoding:
        try:
            import brotli  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError("brotli response received but optional brotli package is unavailable") from error
        return brotli.decompress(raw)
    return raw


def _code(payload: dict) -> int | None:
    value = payload.get("code")
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_value(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def _first_string(value: dict, keys: Iterable[str]) -> str:
    for key in keys:
        result = _string_value(value.get(key))
        if result:
            return result
    return ""


def _nonnegative_int(value: object) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _signed_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_search_results(response: dict, limit: int) -> list[SearchResult]:
    if limit <= 0:
        return []
    tabs = response.get("search_tabs")
    if not isinstance(tabs, list):
        data = response.get("data")
        tabs = data.get("search_tabs") if isinstance(data, dict) else None
    if not isinstance(tabs, list):
        return []

    results: list[SearchResult] = []
    seen: set[str] = set()
    for tab in tabs:
        cells = tab.get("data") if isinstance(tab, dict) else None
        if not isinstance(cells, list):
            continue
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            candidates = cell.get("book_data")
            if isinstance(candidates, dict):
                candidates = [candidates]
            elif not isinstance(candidates, list):
                candidates = [cell] if "book_id" in cell else []
            for book in candidates:
                if not isinstance(book, dict):
                    continue
                book_id = _first_string(book, ("book_id", "id"))
                title = _first_string(book, ("book_name", "title"))
                if not book_id or not title or book_id in seen:
                    continue
                seen.add(book_id)
                results.append(SearchResult(
                    book_id=book_id,
                    title=title,
                    author=_first_string(book, ("author",)),
                    category=_first_string(book, ("category", "complete_category")),
                    chapter_count=_nonnegative_int(book.get("chapter_number", book.get("serial_count"))),
                    score=_first_string(book, ("score",)),
                ))
                if len(results) >= limit:
                    return results
    return results


def _book_dict_candidates(value: object) -> Iterable[dict]:
    if isinstance(value, dict):
        book_id = _first_string(value, ("book_id", "id", "bookId"))
        title = _first_string(value, ("book_name", "title", "bookName", "original_book_name"))
        if book_id and title:
            yield value
        for nested in value.values():
            yield from _book_dict_candidates(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _book_dict_candidates(item)


def parse_rank_results(response: dict, limit: int) -> list[RankItem]:
    if limit <= 0:
        return []
    data = response.get("data") if isinstance(response.get("data"), dict) else response
    preferred: object = data
    if isinstance(data, dict):
        cell_view = data.get("cell_view")
        if isinstance(cell_view, dict) and isinstance(cell_view.get("book_data"), list):
            preferred = cell_view["book_data"]
        elif isinstance(data.get("book_info"), list):
            preferred = data["book_info"]
        elif isinstance(data.get("data"), dict) and isinstance(data["data"].get("book_info"), list):
            preferred = data["data"]["book_info"]
        elif isinstance(data.get("book_list"), list):
            preferred = data["book_list"]
    results: list[RankItem] = []
    seen: set[str] = set()
    for index, book in enumerate(_book_dict_candidates(preferred), start=1):
        book_id = _first_string(book, ("book_id", "id", "bookId"))
        title = _first_string(book, ("book_name", "title", "bookName", "original_book_name"))
        if not book_id or not title or book_id in seen:
            continue
        seen.add(book_id)
        results.append(RankItem(
            book_id=book_id,
            title=title,
            author=_first_string(book, ("author",)),
            category=_first_string(book, ("category", "complete_category", "categoryV2")),
            score=_first_string(book, ("score",)),
            rank_score=_first_string(book, ("rank_score", "read_count")),
            position=_nonnegative_int(book.get("currentPos")) or index,
        ))
        if len(results) >= limit:
            return results
    return results


def collect_cell_ids(value: object) -> tuple[str, ...]:
    return tuple(cell.cell_id for cell in parse_mall_cells(value))


def pick_rank_cell_id(cells: Iterable[MallCell], *, preferred: str | None = None) -> str | None:
    items = tuple(cell for cell in cells if cell.cell_id.isdigit() and cell.cell_id != "0")
    if preferred:
        for cell in items:
            if cell.cell_id == preferred:
                return cell.cell_id
    for cell in items:
        if cell.algo_type in RANK_ALGO_VALUES:
            return cell.cell_id
    for cell in items:
        if "榜" in cell.name or "榜" in cell.tab_title:
            return cell.cell_id
    return items[0].cell_id if items else None


def parse_mall_cells(value: object) -> tuple[MallCell, ...]:
    found: list[MallCell] = []
    index_by_id: dict[str, int] = {}

    def walk(node: object, tab_title: str = "") -> None:
        if isinstance(node, dict):
            next_title = tab_title
            if isinstance(node.get("cell_data"), list) and isinstance(node.get("tab_type"), (int, str)):
                next_title = _first_string(node, ("title", "name")) or tab_title
            cell_id = _first_string(node, ("cell_id_str", "cell_id", "cellId"))
            if cell_id.isdigit() and cell_id != "0":
                name = _first_string(node, ("cell_name", "cell_title", "show_name", "cell_alias"))
                book_like = bool(_first_string(node, ("book_id", "book_name")))
                cell_like = bool(
                    name
                    or isinstance(node.get("cell_view"), dict)
                    or isinstance(node.get("cell_data"), list)
                    or node.get("algo_type") is not None
                    or node.get("default_algo_type") is not None
                    or node.get("algo") is not None
                )
                if cell_like or not book_like:
                    books = node.get("book_data")
                    if books is None:
                        books = node.get("cell_view", ())
                    incoming = MallCell(
                        cell_id=cell_id,
                        name=name,
                        algo_type=_signed_int(node.get("algo_type", node.get("default_algo_type", node.get("algo")))),
                        book_count=sum(1 for _ in _book_dict_candidates(books)),
                        tab_title=next_title,
                    )
                    previous = index_by_id.get(cell_id)
                    if previous is None:
                        index_by_id[cell_id] = len(found)
                        found.append(incoming)
                    else:
                        prior = found[previous]
                        found[previous] = MallCell(
                            cell_id=cell_id,
                            name=incoming.name or prior.name,
                            algo_type=incoming.algo_type if incoming.algo_type is not None else prior.algo_type,
                            book_count=max(incoming.book_count, prior.book_count),
                            tab_title=incoming.tab_title or prior.tab_title,
                        )
            for nested in node.values():
                walk(nested, next_title)
        elif isinstance(node, list):
            for item in node:
                walk(item, tab_title)

    walk(value)
    return tuple(found)


def _append_chapters(value: object, chapters: list[ChapterRef]) -> None:
    if not isinstance(value, list):
        return
    for item in value:
        if not isinstance(item, dict):
            continue
        item_id = _first_string(item, ("item_id", "chapter_id"))
        if item_id:
            chapters.append(ChapterRef(
                item_id=item_id,
                title=_first_string(item, ("title", "chapter_title")),
                order=_signed_int(item.get("order")),
            ))


def parse_directory(response: dict, fallback_book_id: str) -> BookInfo:
    data = response.get("data") if isinstance(response.get("data"), dict) else response
    if not isinstance(data, dict):
        data = {}
    nested = data.get("book_info") if isinstance(data.get("book_info"), dict) else {}
    chapters: list[ChapterRef] = []
    for key in ("item_data_list", "item_list", "all_items", "chapter_list"):
        if isinstance(data.get(key), list):
            _append_chapters(data[key], chapters)
            break
    if not chapters and isinstance(data.get("volume_list"), list):
        for volume in data["volume_list"]:
            if isinstance(volume, dict):
                _append_chapters(volume.get("item_data_list", volume.get("chapter_list")), chapters)
    book_id = _first_string(data, ("book_id",)) or _first_string(nested, ("book_id",)) or fallback_book_id
    book_name = _first_string(data, ("book_name", "name")) or _first_string(nested, ("book_name", "name")) or book_id
    author = _first_string(data, ("author",)) or _first_string(nested, ("author",))
    abstract_text = _first_string(data, ("abstract", "book_abstract")) or _first_string(nested, ("abstract", "book_abstract"))
    return BookInfo(book_id, book_name, author, abstract_text, tuple(chapters))


def _looks_like_base64_cipher(content: str) -> bool:
    return len(content) >= 32 and re.fullmatch(r"[A-Za-z0-9+/=]+", content[:80]) is not None


def _chapter_content(chapter: dict, key: bytes | None) -> str:
    content = chapter.get("content")
    crypt_status = _signed_int(chapter.get("crypt_status")) or 0
    if not isinstance(content, str) or not content or content == "Invalid":
        raise RuntimeError(f"chapter content is locked or empty (crypt_status={crypt_status})")
    if crypt_status == 0 and not _looks_like_base64_cipher(content):
        return extract_text(content)
    if key is None:
        raise RuntimeError(f"chapter is encrypted but no session key is available (crypt_status={crypt_status})")
    return decrypt_chapter_text(content, key)


def _needs_new_key(data: dict, ids: Iterable[str], session: SessionKey) -> bool:
    for item_id in ids:
        chapter = data.get(item_id)
        if not isinstance(chapter, dict):
            continue
        crypt_status = _signed_int(chapter.get("crypt_status")) or 0
        key_version = _signed_int(chapter.get("key_version"))
        if crypt_status != 0 and key_version not in (None, 0, session.keyver):
            return True
    return False


def safe_name(value: str) -> str:
    output = re.sub(r"[/\\:*?\"<>|]", "_", value).strip()
    return output or "book"


def _write_book(output_dir: Path, book: BookInfo, chapters: list[tuple[ChapterRef, str]]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{safe_name(book.book_name)}.txt"
    with destination.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(f"《{book.book_name}》\n")
        handle.write(f"作者: {book.author}\n\n")
        if book.abstract_text:
            handle.write(f"{book.abstract_text}\n\n")
        for _, text in chapters:
            handle.write(f"{text}\n\n")
    return destination


def _rank_net():
    bridge = str(Path(__file__).resolve().parents[1])
    if bridge not in sys.path:
        sys.path.insert(0, bridge)
    import net

    return net


class FanqieClient:
    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout
        library = _rank_net()
        self._http = library.sync_session(
            impersonate=IMPERSONATE,
            default_headers=False,
            allow_redirects=False,
            timeout=timeout,
            curl_options={library.path_as_is(): 1},
        )
        self.device_id, self.install_id = self._register_device()

    def _send(self, url: str, *, method: str, headers: dict[str, str], body: bytes | None) -> HttpResult:
        try:
            response = self._http.request(
                method,
                url,
                headers=headers,
                data=body,
                timeout=self.timeout,
                allow_redirects=False,
                quote=False,
                accept_encoding="gzip, deflate",
            )
        except _rank_net().request_error() as error:
            raise RuntimeError(f"transport error: {error}") from error
        content_type = ""
        header_type = response.headers.get("Content-Type")
        if isinstance(header_type, str):
            content_type = header_type
        return HttpResult(response.status_code, response.content, content_type, url)

    def _register_device(self) -> tuple[str, str]:
        profile = {
            "aid": 1967, "app_version": "7.2.1", "cdid": str(uuid.uuid4()), "channel": "App Store",
            "device_brand": "Apple", "device_manufacturer": "Apple", "device_model": "iPad13,8",
            "device_platform": "ios", "openudid": os.urandom(20).hex(), "os_version": "26.5",
            "resolution": "3840x2160", "update_version_code": "72132", "version_code": "721",
        }
        envelope = {"_gen_time": int(time.time() * 1000), "header": profile, "magic_tag": "ss_app_log"}
        plaintext = json.dumps(envelope, separators=(",", ":")).encode()
        seed = os.urandom(32)
        material = hashlib.sha512(hashlib.sha512(seed).digest() + APPLOG_KEY_MATERIAL).digest()
        compressed = _gzip(plaintext)
        payload = hashlib.sha512(compressed).digest() + compressed
        frame = APPLOG_MAGIC + seed + aes128_cbc_encrypt(payload, material[:16], material[16:32])
        result = self._send(
            REGISTER_URL,
            method="POST",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
                "Accept-Encoding": "gzip, deflate",
                "Content-Type": "application/octet-stream",
            },
            body=frame,
        )
        if result.status >= 400:
            detail = result.content[:300].decode("utf-8", "replace")
            raise RuntimeError(f"device registration returned HTTP {result.status}: {detail}")
        data = result.content
        if data.startswith(APPLOG_MAGIC):
            data = applog_pack_decrypt(data)
        payload = json.loads(data)
        device_id = str(payload.get("device_id_str", ""))
        install_id = str(payload.get("install_id_str", ""))
        if not device_id.isdigit() or not install_id.isdigit():
            raise RuntimeError("device registration returned invalid numeric identity")
        return device_id, install_id

    def _common(self) -> str:
        return f"device_id={self.device_id}&os_version=26.5&app_name=novelapp&version_code=721&channel=App%20Store&update_version_code=72132&device_platform=ipad&device_type=iPad%20Pro%205&aid=1967"

    def _request(self, url: str, body: bytes | None = None) -> dict:
        for attempt in range(3):
            khronos = find_normalized_khronos(raw_query(url), body, int(time.time()))
            headers = sign_headers(SignInput(url, self.device_id, khronos, secrets.randbelow(2**31), secrets.randbelow(2**31), secrets.randbelow(2**31), secrets.randbelow(2**31), body))
            headers.update({"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"})
            if body is not None:
                headers["Content-Type"] = "application/json; encoding=utf-8"
            result = self._send(url, method="POST" if body is not None else "GET", headers=headers, body=body)
            if result.status >= 400:
                detail = result.content[:300].decode("utf-8", "replace")
                raise RuntimeError(f"HTTP {result.status}: {detail}")
            raw = result.content
            content_type = result.content_type
            if not raw:
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise RuntimeError("empty API response after 3 signed attempts")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as error:
                raise RuntimeError(f"non-JSON API response ({content_type}, {len(raw)} bytes)") from error
            if _code(payload) == 100_103 and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            return payload
        raise AssertionError("unreachable")

    @staticmethod
    def _success(payload: dict, stage: str) -> dict:
        if _code(payload) != 0:
            raise RuntimeError(f"{stage} failed: {payload.get('code')} {payload.get('message', '')}")
        return payload

    def search(self, query: str, count: int = 1, offset: int = 0) -> dict:
        query = query.strip()
        if not query:
            raise ValueError("search title cannot be empty")
        if not 1 <= count <= 30:
            raise ValueError("count must be in 1..=30")
        value = urllib.parse.quote(query, safe="-_.~")
        url = f"{HOST}/reading/bookapi/search/tab/v:version/?{self._common()}&query={value}&tab_type=1&offset={offset}&count={count}"
        return self._success(self._request(url), "search")

    def search_results(self, query: str, count: int = 1, offset: int = 0) -> list[SearchResult]:
        return parse_search_results(self.search(query, count, offset), count)

    def _signed_get(self, paths: tuple[str, ...], extra: str, stage: str) -> dict:
        last: Exception | None = None
        common = self._common()
        suffix = f"&{extra}" if extra else ""
        for path in paths:
            url = f"{HOST}{path}?{common}{suffix}"
            try:
                payload = self._request(url)
                return self._success(payload, stage)
            except Exception as error:
                last = error
        if last is None:
            raise RuntimeError(f"{stage} has no candidate paths")
        raise last

    def category_landing(
        self,
        category_id: str,
        *,
        offset: int = 0,
        limit: int = 10,
        sort_by: int = 24,
        query_gender: int = 1,
        book_status: int | str | None = None,
        word_number: int | str | None = None,
    ) -> dict:
        if not category_id.strip():
            raise ValueError("category_id cannot be empty")
        if not 1 <= limit <= 30:
            raise ValueError("limit must be in 1..=30")
        extra = (
            f"category_id={urllib.parse.quote(category_id, safe='')}&offset={offset}&limit={limit}"
            f"&sort_by={sort_by}&source=front_category&query_gender={query_gender}&genre_type=0"
        )
        if book_status is not None:
            extra += f"&book_status={urllib.parse.quote(str(book_status), safe='')}"
        if word_number is not None:
            extra += f"&word_number={urllib.parse.quote(str(word_number), safe='')}"
        return self._signed_get(CATEGORY_LANDING_PATHS, extra, "category_landing")

    def category_landing_results(self, category_id: str, *, limit: int = 10, **kwargs: object) -> list[RankItem]:
        return parse_rank_results(self.category_landing(category_id, limit=limit, **kwargs), limit)

    def category_front(self, *, query_gender: int = 1) -> dict:
        extra = f"query_gender={query_gender}&genre_type=0&source=front_category"
        return self._signed_get(CATEGORY_FRONT_PATHS, extra, "category_front")

    def mall_tab(
        self,
        *,
        tab_type: int = -1,
        offset: int = 0,
        req_rank_algo: int = 0,
        req_rank_category_id: int = 0,
        query_gender: int = 1,
    ) -> dict:
        extra = (
            f"tab_type={tab_type}&offset={offset}&req_rank_algo={req_rank_algo}"
            f"&req_rank_category_id={req_rank_category_id}&query_gender={query_gender}&genre_type=0"
        )
        return self._signed_get(MALL_TAB_PATHS, extra, "mall_tab")

    def category_daily_ranklist(
        self,
        category_id_list: str = "262",
        *,
        rank_gender: int = 1,
        query_gender: int = 1,
    ) -> dict:
        ids = category_id_list.strip()
        if not ids:
            raise ValueError("category_id_list cannot be empty")
        extra = (
            f"category_id_list={urllib.parse.quote(ids, safe=',')}&rank_gender={rank_gender}"
            f"&query_gender={query_gender}&genre_type=0"
        )
        return self._signed_get(CATEGORY_DAILY_RANKLIST_PATHS, extra, "category_daily_ranklist")

    def category_daily_ranklist_results(
        self,
        category_id_list: str = "262",
        *,
        limit: int = 12,
        **kwargs: object,
    ) -> list[RankItem]:
        return parse_rank_results(
            self.category_daily_ranklist(category_id_list, **kwargs),
            limit,
        )

    def ranklist_sequence(self, extra: str = "") -> dict:
        return self._signed_get(RANKLIST_SEQUENCE_PATHS, extra, "ranklist_sequence")

    def ranklist_sequence_results(self, *, limit: int = 12, extra: str = "") -> list[RankItem]:
        return parse_rank_results(self.ranklist_sequence(extra), limit)

    def ranklist_random(self, extra: str = "") -> dict:
        return self._signed_get(RANKLIST_RANDOM_PATHS, extra, "ranklist_random")

    def mall_tab_cells(self, **kwargs: object) -> tuple[MallCell, ...]:
        return parse_mall_cells(self.mall_tab(**kwargs))

    def mall_cell(
        self,
        cell_id: str,
        *,
        algo_type: int = 111,
        offset: int = 0,
        limit: int = 12,
        cell_gender: int = 1,
        inner_algo: int | None = None,
        specific_sub_tab_type: int | None = None,
        category_id: str | None = None,
        tab_type: int | None = None,
        sub_algo_type: int | str | None = None,
        main_algo_type: int | str | None = None,
        monthly_algo_type: int | str | None = None,
        rank_list_sub_tab_type_list: str | int | None = None,
        list_gender: int | None = None,
        gender_list_type: int | None = None,
        rank_list_style_type: int | None = None,
        main_algo_name: str | None = None,
        sub_algo_name: str | None = None,
        client_req_type: int | None = None,
        support_gender_list: bool | str | None = None,
    ) -> dict:
        if not cell_id.strip().isdigit():
            raise ValueError("cell_id must be numeric")
        if not 1 <= limit <= 30:
            raise ValueError("limit must be in 1..=30")
        extra = (
            f"cell_id={urllib.parse.quote(cell_id, safe='')}&algo_type={algo_type}&change_type=1"
            f"&offset={offset}&limit={limit}&list_type=daily&cell_gender={cell_gender}"
            "&genre_type=0&book_type=0"
        )
        optional: list[tuple[str, object]] = [
            ("inner_algo", inner_algo),
            ("specific_sub_tab_type", specific_sub_tab_type),
            ("tab_type", tab_type),
            ("sub_algo_type", sub_algo_type),
            ("main_algo_type", main_algo_type),
            ("monthly_algo_type", monthly_algo_type),
            ("rank_list_sub_tab_type_list", rank_list_sub_tab_type_list),
            ("list_gender", list_gender),
            ("gender_list_type", gender_list_type),
            ("rank_list_style_type", rank_list_style_type),
            ("client_req_type", client_req_type),
            ("support_gender_list", support_gender_list),
        ]
        for key, value in optional:
            if value is not None:
                rendered = "true" if value is True else "false" if value is False else str(value)
                extra += f"&{key}={urllib.parse.quote(rendered, safe=',')}"
        if category_id:
            extra += f"&category_id={urllib.parse.quote(category_id, safe='')}"
        if main_algo_name:
            extra += f"&main_algo_name={urllib.parse.quote(main_algo_name, safe='')}"
        if sub_algo_name:
            extra += f"&sub_algo_name={urllib.parse.quote(sub_algo_name, safe='')}"
        return self._signed_get(MALL_CELL_PATHS, extra, "mall_cell")

    def mall_cell_results(self, cell_id: str, *, limit: int = 12, **kwargs: object) -> list[RankItem]:
        return parse_rank_results(self.mall_cell(cell_id, limit=limit, **kwargs), limit)

    def rank_results(
        self,
        *,
        algo: str = "read",
        cell_id: str | None = None,
        limit: int = 12,
        query_gender: int = 1,
    ) -> list[RankItem]:
        if algo not in RANK_ALGO:
            raise ValueError(f"unknown rank algo: {algo}")
        resolved = cell_id
        if resolved is None:
            cells: tuple[MallCell, ...] = ()
            try:
                cells = parse_mall_cells(self.mall_tab(query_gender=query_gender))
            except Exception:
                cells = ()
            if not cells:
                try:
                    cells = parse_mall_cells(self.category_front(query_gender=query_gender))
                except Exception:
                    cells = ()
            resolved = pick_rank_cell_id(cells, preferred=DEFAULT_MALL_CELL_ID) or DEFAULT_MALL_CELL_ID
        return self.mall_cell_results(
            resolved,
            algo_type=RANK_ALGO[algo],
            limit=limit,
            cell_gender=query_gender,
        )

    def directory(self, book_id: str) -> dict:
        url = f"{HOST}/reading/bookapi/directory/all_items/v:version/?{self._common()}&book_id={urllib.parse.quote(book_id, safe='')}"
        return self._success(self._request(url), "directory")

    def batch_full(self, item_ids: list[str], book_id: str) -> dict:
        if not 1 <= len(item_ids) <= 30:
            raise ValueError("item_ids must contain 1..=30 chapters")
        query = urllib.parse.quote(",".join(item_ids), safe=",")
        url = f"{HOST}/reading/reader/batch_full/v:version/?{self._common()}&book_id={urllib.parse.quote(book_id, safe='')}&item_ids={query}"
        return self._success(self._request(url), "batch_full")

    def _register_session(self) -> SessionKey:
        iv = os.urandom(16)
        plaintext = int(self.device_id).to_bytes(8, "little") + b"\0" * 8
        content = base64.b64encode(iv + aes128_cbc_encrypt(plaintext, ORIGIN_KEY_DATA, iv)).decode()
        body = f'{{\n  "content" : "{content}",\n  "keyver" : 1001\n}}'.encode()
        ordered = f"version_code=721&app_name=novelapp&device_id={self.device_id}&channel=App%20Store&aid=1967&update_version_code=72132&os_version=26.5&device_platform=ipad&device_type=iPad%20Pro%205"
        payload = self._success(self._request(f"{HOST}/reading/crypt/registerkey?{ordered}", body), "registerkey")
        data = payload.get("data")
        if not isinstance(data, dict) or not data.get("key"):
            raise RuntimeError("registerkey response is missing data.key")
        return SessionKey(unwrap_server_key(str(data["key"])), _signed_int(data.get("keyver")) or 0)

    def register_key(self) -> bytes:
        """Backwards-compatible single-key API; full downloads retain keyver."""
        return self._register_session().key

    def chapter_text(self, book_id: str, item_id: str, key: bytes | None) -> str:
        data = self.batch_full([item_id], book_id).get("data", {})
        chapter = data.get(item_id) if isinstance(data, dict) else None
        return _chapter_content(chapter if isinstance(chapter, dict) else {}, key)

    def download_book(
        self,
        book_id: str,
        output_dir: str | Path = "./out",
        max_chapters: int | None = None,
        batch_size: int = 30,
        progress: Callable[[int, int], None] | None = None,
    ) -> DownloadReport:
        if not 1 <= batch_size <= 30:
            raise ValueError("batch_size must be in 1..=30")
        if max_chapters is not None and max_chapters < 0:
            raise ValueError("max_chapters must be non-negative")
        book = parse_directory(self.directory(book_id), book_id)
        if not book.chapters:
            raise RuntimeError("no chapters found in directory")
        selected = list(book.chapters[:max_chapters]) if max_chapters is not None else list(book.chapters)
        failures: list[str] = []
        try:
            session: SessionKey | None = self._register_session()
        except Exception as error:
            session = None
            failures.append(f"register_key: {error}")
        results: list[tuple[ChapterRef, str]] = []
        for start in range(0, len(selected), batch_size):
            batch = selected[start : start + batch_size]
            ids = [chapter.item_id for chapter in batch]
            response = self.batch_full(ids, book_id)
            data = response.get("data") if isinstance(response.get("data"), dict) else {}
            if session is not None and _needs_new_key(data, ids, session):
                try:
                    session = self._register_session()
                    response = self.batch_full(ids, book_id)
                    data = response.get("data") if isinstance(response.get("data"), dict) else {}
                except Exception as error:
                    failures.append(f"re-register_key: {error}")
            for chapter in batch:
                try:
                    results.append((chapter, _chapter_content(data.get(chapter.item_id, {}), session.key if session else None)))
                except Exception as error:
                    message = f"{chapter.item_id}: {error}"
                    failures.append(message)
                    results.append((chapter, f"[failed: {error}]"))
            if progress is not None:
                progress(len(results), len(selected))
        succeeded = sum(not text.startswith("[failed:") for _, text in results)
        destination = _write_book(Path(output_dir), book, results)
        if results and succeeded == 0:
            details = "; ".join(failures) if failures else "no additional error details"
            raise RuntimeError(f"all chapters failed; results were written to {destination}: {details}")
        return DownloadReport(book, destination, len(results), succeeded, tuple(failures), session.keyver if session else None)
