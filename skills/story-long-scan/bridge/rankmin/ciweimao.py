"""Ciweimao app rank list.

The request path is the copied client in bridge/ciweimao_app: sign, decrypt,
guest registration, and Session.get_rank_books. This file only maps that
book_list into the scan markdown.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from .contracts import ParseResult, RankFetchError, RankItem, RankSnapshot, SourceSpec
from .textutil import now_cst_iso

PARSER_VERSION = "ciweimao_app_rank_v1"
BASE_URL = "https://app1.happybooker.cn"
RANK_PATH = "/bookcity/get_rank_book_list"
_ENV_ACCOUNT = "CIWEIMAO_ACCOUNT"
_ENV_LOGIN = "CIWEIMAO_LOGIN_TOKEN"
_ENV_DEVICE = "CIWEIMAO_DEVICE_TOKEN"

_TIMES = ("week", "month", "total")
_ORDERS = (
    "fans_value",
    "no_vip_click",
    "yp",
    "word_count",
    "track_read",
    "complet",
    "blade",
    "yp_new",
    "recommend",
    "tsukkomi",
    "favor",
)
_DEFAULT_TIME = {
    "fans_value": "week",
    "no_vip_click": "week",
    "yp": "month",
    "word_count": "week",
    "track_read": "week",
    "complet": "month",
    "blade": "month",
    "yp_new": "month",
    "recommend": "total",
    "tsukkomi": "week",
    "favor": "week",
}
_LABELS = {
    "fans_value:week": "粉丝值周榜",
    "fans_value:month": "粉丝值月榜",
    "fans_value:total": "粉丝值总榜",
    "no_vip_click:week": "非VIP点击周榜",
    "yp:month": "月票月榜",
    "word_count:week": "字数周榜",
    "track_read:week": "追读周榜",
    "complet:month": "完结月榜",
    "blade:month": "刀片月榜",
    "yp_new:month": "新书月票月榜",
    "recommend:total": "推荐总榜",
    "tsukkomi:week": "吐槽周榜",
    "favor:week": "收藏周榜",
}
DEFAULT_CATEGORIES = (
    "fans_value:week",
    "favor:week",
    "tsukkomi:week",
    "yp_new:month",
)
_SCORE_KEYS = (
    "fans_value",
    "total_click",
    "click_total",
    "total_favor",
    "favor",
    "recommend_num",
    "month_ticket",
    "yp",
    "score",
    "rank_value",
    "hot_value",
)



def resolve_ciweimao_category(category: str) -> str:
    text = (category or "").strip()
    if text in _LABELS:
        return text
    if ":" in text:
        order, time_type = text.split(":", 1)
    else:
        order, time_type = text, _DEFAULT_TIME.get(text, "")
    if order not in _ORDERS or time_type not in _TIMES:
        known = ", ".join(DEFAULT_CATEGORIES)
        raise RankFetchError(f"ciweimao unknown rank: {category or '(empty)'}; examples: {known}")
    key = f"{order}:{time_type}"
    if key not in _LABELS:
        raise RankFetchError(f"ciweimao unknown rank: {key}")
    return key


def ciweimao_source(category: str) -> SourceSpec:
    key = resolve_ciweimao_category(category)
    order, time_type = key.split(":", 1)
    return SourceSpec(
        site_id="ciweimao",
        site_name="刺猬猫",
        source_id=f"ciweimao-{key}",
        semantic_key=key,
        category=key,
        category_name=_LABELS[key],
        url=f"{BASE_URL}{RANK_PATH}?order={order}&time_type={time_type}",
        required_adapters=["ciweimao_app_rank"],
        known_risks=["session_env", "no_chapter_fallback"],
    )


def _text(value: Any) -> str:
    return str(value or "").strip()


def _book(raw: dict[str, Any]) -> dict[str, Any]:
    nested = raw.get("book_info")
    if isinstance(nested, dict) and _text(nested.get("book_id") or nested.get("book_name")):
        return nested
    return raw


def _words(value: Any) -> str:
    text = _text(value)
    if not text or text == "0":
        return ""
    try:
        number = int(text)
    except ValueError:
        return text
    if number >= 10000:
        scaled = number / 10000
        return f"{scaled:.1f}万"
    return str(number)


def _pay_text(raw: dict[str, Any]) -> str:
    flag = _text(raw.get("is_paid"))
    if flag == "0":
        return "免费"
    if flag == "1":
        return "付费书"
    return ""


def _score(raw: dict[str, Any], order: str) -> str:
    for key in (order, *_SCORE_KEYS):
        text = _text(raw.get(key))
        if text and text != "0":
            return text
    return ""


def parse_ciweimao_rank(payload: dict[str, Any] | str, limit: int) -> ParseResult:
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return ParseResult(False, failure_code="json_invalid", failure_detail="body", parser_version=PARSER_VERSION)
    else:
        data = payload
    code = _text(data.get("code"))
    if code and code != "100000":
        return ParseResult(False, failure_code="api_code", failure_detail=code, parser_version=PARSER_VERSION)
    body = data.get("data") if isinstance(data.get("data"), dict) else data
    books = body.get("book_list") if isinstance(body, dict) else None
    if not isinstance(books, list) or not books:
        return ParseResult(False, failure_code="empty_book_list", parser_version=PARSER_VERSION)
    items = []
    for raw in books[:limit]:
        if isinstance(raw, dict):
            items.append(_book(raw))
    if not items:
        return ParseResult(False, failure_code="empty_book_list", parser_version=PARSER_VERSION)
    return ParseResult(True, items=items, parser_version=PARSER_VERSION)


def normalize_ciweimao(source: SourceSpec, parsed: ParseResult) -> RankSnapshot:
    order = source.semantic_key.split(":", 1)[0]
    items: list[RankItem] = []
    for index, raw in enumerate(parsed.items, start=1):
        book_id = _text(raw.get("book_id")) or f"ciweimao-{index}"
        book_name = _text(raw.get("book_name"))
        category_text = _text(raw.get("category_name") or raw.get("category"))
        description = _text(raw.get("description") or raw.get("book_description"))
        items.append(RankItem(
            rank_position=index,
            book_id=book_id,
            book_name=book_name,
            author_name=_text(raw.get("author_name")),
            book_url=f"https://www.ciweimao.com/book/{book_id}" if book_id else "",
            cover_url=_text(raw.get("cover") or raw.get("cover_url")),
            description=description,
            category_text=category_text,
            score_text=_score(raw, order),
            word_count_text=_words(raw.get("total_word_count")),
            extra={"pay_text": _pay_text(raw)},
            field_confidence={
                "book_name": "verified" if book_name else "missing",
            },
        ))
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
        parse_status="ok" if parsed.ok else parsed.failure_code,
        parser_version=parsed.parser_version or PARSER_VERSION,
    )



def _client():
    bridge = Path(__file__).resolve().parents[1]
    bridge_text = str(bridge)
    if bridge_text not in sys.path:
        sys.path.insert(0, bridge_text)
    try:
        from ciweimao_app.api import ApiError, Session
        from ciweimao_app.guest import GuestRegistrationError, register_guest
        from ciweimao_app import config as client_config
    except ModuleNotFoundError as exc:
        name = exc.name or "ciweimao_app"
        raise RankFetchError(f"ciweimao missing module: {name}") from exc
    return ApiError, Session, GuestRegistrationError, register_guest, client_config


def state_path() -> Path:
    override = _text(os.environ.get("CIWEIMAO_STATE"))
    if override:
        return Path(override)
    return Path.home() / ".oh-story" / "ciweimao-guest.json"


def _read_state(path: Path) -> dict[str, str] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    account = _text(data.get("account"))
    login_token = _text(data.get("login_token"))
    if not account or not login_token:
        return None
    return {
        "account": account,
        "login_token": login_token,
        "device_token": _text(data.get("device_token")),
    }


def _write_state(path: Path, account: str, login_token: str, device_token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "account": account,
        "login_token": login_token,
        "device_token": device_token,
    }, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _env_session(env: Mapping[str, str] | None) -> tuple[str, str, str] | None:
    source = os.environ if env is None else env
    account = _text(source.get(_ENV_ACCOUNT))
    login_token = _text(source.get(_ENV_LOGIN))
    device_token = _text(source.get(_ENV_DEVICE))
    if not account and not login_token and not device_token:
        return None
    missing = [
        name for name, value in (
            (_ENV_ACCOUNT, account),
            (_ENV_LOGIN, login_token),
            (_ENV_DEVICE, device_token),
        ) if not value
    ]
    if missing:
        raise RankFetchError("ciweimao missing field: " + ",".join(missing))
    return account, login_token, device_token


def _register_guest(proxy: str | None) -> tuple[str, str, str]:
    _, _, guest_error, register_guest, client_config = _client()
    try:
        guest = asyncio.run(register_guest(proxy=proxy))
    except guest_error as exc:
        raise RankFetchError(f"ciweimao guest registration failed: code={exc.code}")
    except Exception as exc:
        raise RankFetchError(f"ciweimao guest registration failed: {type(exc).__name__}")
    device = guest.device_token or client_config.DEVICE_TOKEN_PREFIX
    _write_state(state_path(), guest.account, guest.login_token, device)
    return guest.account, guest.login_token, device


def _rank_books(
    account: str,
    login_token: str,
    device_token: str,
    order: str,
    time_type: str,
    limit: int,
    proxy: str | None,
) -> list:
    api_error, session_cls, _, _, client_config = _client()
    session = session_cls(
        login_token=login_token,
        account=account,
        device_token=device_token or client_config.DEVICE_TOKEN_PREFIX,
        app_version=client_config.APP_VERSION,
        proxy=proxy,
    )
    try:
        return session.get_rank_books(
            order, time_type, page=0, count=max(1, min(int(limit), 100)),
        )
    except api_error as exc:
        raise RankFetchError(f"ciweimao request failed: code={exc.code}")
    finally:
        session.close()


def _refresh_guest(proxy: str | None) -> tuple[str, str, str]:
    path = state_path()
    if path.is_file():
        path.unlink()
    return _register_guest(proxy)


def fetch_ciweimao_rank(
    category: str,
    limit: int = 20,
    env: Mapping[str, str] | None = None,
) -> RankSnapshot:
    if limit < 1:
        raise RankFetchError("ciweimao limit must be at least 1")
    from .ciweimao_egress import resolve_proxy

    source = ciweimao_source(category)
    order, time_type = source.semantic_key.split(":", 1)
    proxy = resolve_proxy()
    supplied = _env_session(env)
    from_env = supplied is not None
    if supplied is None:
        cached = _read_state(state_path())
        if cached is None:
            supplied = _register_guest(proxy)
        else:
            supplied = (cached["account"], cached["login_token"], cached["device_token"])
    account, login_token, device_token = supplied

    def _load() -> list:
        try:
            return _rank_books(
                account, login_token, device_token, order, time_type, limit, proxy,
            )
        except RankFetchError:
            raise
        except RuntimeError as exc:
            if "login_token 已过期" in str(exc):
                raise RankFetchError("ciweimao request failed: code=200100")
            raise RankFetchError("ciweimao request failed: session")
        except Exception as exc:
            raise RankFetchError(f"ciweimao request failed: {type(exc).__name__}")

    def _load_or_reregister() -> list:
        nonlocal account, login_token, device_token
        try:
            return _load()
        except RankFetchError as exc:
            if from_env or "code=200100" not in str(exc):
                raise
            account, login_token, device_token = _refresh_guest(proxy)
            return _load()

    try:
        books = _load_or_reregister()
    except RankFetchError as exc:
        if "code=320002" not in str(exc):
            raise
        proxy = resolve_proxy(fresh=True)
        books = _load_or_reregister()
    parsed = parse_ciweimao_rank({"code": "100000", "data": {"book_list": books}}, limit)
    if not parsed.ok:
        detail = parsed.failure_detail or parsed.failure_code
        raise RankFetchError(f"ciweimao parse failed: category={source.category} code={detail}")
    snapshot = normalize_ciweimao(source, parsed)
    missing = [item.book_id for item in snapshot.items if not item.book_name]
    if not snapshot.items or missing:
        named = missing[0] if missing else source.category
        raise RankFetchError(f"ciweimao missing field: {named}:book_name")
    return snapshot
