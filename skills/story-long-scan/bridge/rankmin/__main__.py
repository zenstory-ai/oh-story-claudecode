from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .ciweimao import (
    normalize_ciweimao,
    parse_ciweimao_rank,
    resolve_ciweimao_category,
)
from .ciweimao import ciweimao_source
from .contracts import RankFetchError
from .fanqie import (
    fetch_fanqie_rank,
    normalize_fanqie,
    parse_fanqie_initial_state,
    polluted_fields,
    resolve_fanqie_category,
)
from .markdown_out import render_markdown, write_snapshot
from .qidian import (
    fetch_qidian_mobile,
    normalize_qidian_mobile,
    parse_qidian_mobile_rank_ssr,
    qidian_source,
    resolve_qidian_category,
)
from .textutil import today_cst

_DAY = re.compile(r"^\d{8}$")
_QIDIAN_FIXTURE = """
<script id="vite-plugin-ssr_pageContext" type="application/json">
{"pageContext":{"pageProps":{"pageData":{"records":[
  {"bid":"1001","bName":"测试书甲","bAuth":"作者甲","desc":"简介甲","cnt":"12万","cat":"玄幻","subCat":"东方玄幻","state":"连载","rankCnt":"100万月票","rankNum":1},
  {"bid":"1002","bName":"测试书乙","bAuth":"作者乙","desc":"简介乙","cnt":"3万","cat":"都市","state":"连载","rankCnt":"","rankNum":2}
]}}}}
</script>
"""
_FANQIE_FIXTURE = """
<script>window.__INITIAL_STATE__={"rank":{"rankTypeText":"阅读榜","book_list":[
  {"bookId":"9001","bookName":"番茄书","author":"作者丙","abstract":"【种田+慢热】简介丙","read_count":"1.2万","wordNumber":"30万","category":"西方奇幻","creationStatus":"1"}
]}};</script>
"""
_FANQIE_POLLUTED = """
<script>window.__INITIAL_STATE__={"rank":{"book_list":[
  {"bookId":"9002","bookName":"乱码\\ue000书","author":"作者","abstract":"简介"}
]}};</script>
"""


def _split(raw: str, defaults: tuple[str, ...]) -> list[str]:
    if raw.strip() in {"", "default"}:
        return list(defaults)
    return [part.strip() for part in raw.split(",") if part.strip()]


def _run_fetch(
    out_dir: Path,
    day: str,
    qidian: str,
    fanqie: str,
    ciweimao: str,
    jjwxc: str,
    limit: int,
) -> int:
    from .providers import provider_map

    selected = {
        "qidian": qidian,
        "fanqie": fanqie,
        "ciweimao": ciweimao,
        "jjwxc": jjwxc,
    }
    table = provider_map()
    jobs: list[tuple[str, str, object]] = []
    for site_id, raw in selected.items():
        if not raw:
            continue
        fetch = table[site_id].fetch
        jobs.extend((site_id, category, fetch) for category in _split(raw, ()))
    if not jobs:
        print("name --qidian, --fanqie, --ciweimao, or --jjwxc", file=sys.stderr)
        return 2
    failed = False
    for site, category, fetch in jobs:
        try:
            snapshot = fetch(category, limit)  # type: ignore[operator]
            path = write_snapshot(snapshot, out_dir, day)
        except Exception as exc:
            print(f"{site} {category} failed: {exc}", file=sys.stderr)
            failed = True
            continue
        print(path)
    return 2 if failed else 0


def self_test() -> int:
    checks = 0
    source = qidian_source("yuepiao")
    parsed = parse_qidian_mobile_rank_ssr(_QIDIAN_FIXTURE, category=source.category, limit=20)
    if not parsed.ok or parsed.items[0]["bName"] != "测试书甲":
        print("qidian fixture parse failed", file=sys.stderr)
        return 2
    snapshot = normalize_qidian_mobile(source, parsed)
    text = render_markdown(snapshot)
    if "测试书甲" not in text or "100万月票" not in text or "榜单值：[待补]" not in text:
        print("qidian markdown missing fields", file=sys.stderr)
        return 2
    if "总推荐" in text or "签约" in text or "收费模式" in text:
        print("qidian markdown invented closed fields", file=sys.stderr)
        return 2
    checks += 1
    if resolve_qidian_category("hotsales") != "mobile-hotsales":
        print("qidian alias failed", file=sys.stderr)
        return 2
    checks += 1
    try:
        resolve_qidian_category("desktop-yuepiao")
    except RankFetchError:
        checks += 1
    else:
        print("desktop qidian was accepted", file=sys.stderr)
        return 2
    fanqie_source_category = resolve_fanqie_category("male-hot-xifangqihuan")
    if fanqie_source_category != "1_2_1141":
        print(f"fanqie alias failed: {fanqie_source_category}", file=sys.stderr)
        return 2
    checks += 1
    fanqie_rising = resolve_fanqie_category("male-rising-dushinaodong")
    fanqie_female_rising = resolve_fanqie_category("female-rising-gufengshiqing")
    if fanqie_rising != "1_3_262" or fanqie_female_rising != "0_3_1139":
        print(f"fanqie rising alias failed: {fanqie_rising} {fanqie_female_rising}", file=sys.stderr)
        return 2
    checks += 1
    from .fanqie import fanqie_source

    fanqie = fanqie_source("1_2_1141")
    fanqie_parsed = parse_fanqie_initial_state(_FANQIE_FIXTURE, limit=10)
    if not fanqie_parsed.ok or fanqie_parsed.items[0]["bookName"] != "番茄书":
        print("fanqie fixture parse failed", file=sys.stderr)
        return 2
    fanqie_snapshot = normalize_fanqie(fanqie, fanqie_parsed)
    if polluted_fields(fanqie_snapshot):
        print("clean fanqie fixture looked polluted", file=sys.stderr)
        return 2
    fanqie_text = render_markdown(fanqie_snapshot)
    tag_line = next((line for line in fanqie_text.splitlines() if line.startswith("**标签：**")), "")
    if "在读：1.2万" not in fanqie_text or tag_line != "**标签：** 种田、慢热":
        print("fanqie markdown missing read count or selling tags", file=sys.stderr)
        return 2
    checks += 1
    polluted = normalize_fanqie(fanqie, parse_fanqie_initial_state(_FANQIE_POLLUTED, limit=5))
    bad = polluted_fields(polluted)
    if not any(part.endswith(":book_name") for part in bad):
        print(f"polluted title was not named: {bad}", file=sys.stderr)
        return 2
    checks += 1
    fanqie_app = Path(__file__).resolve().parents[1] / "fanqie_app"
    if str(fanqie_app) not in sys.path:
        sys.path.insert(0, str(fanqie_app))
    try:
        from fanqie_client import FanqieClient
        from fanqie_pure import sign_headers
    except ModuleNotFoundError as exc:
        print(f"fanqie missing module: {exc.name}", file=sys.stderr)
        return 2
    if not callable(FanqieClient) or not callable(sign_headers):
        print("fanqie client missing", file=sys.stderr)
        return 2
    checks += 1
    try:
        fetch_qidian_mobile("mm", 1)
    except RankFetchError as exc:
        if "unavailable" not in str(exc):
            print(f"qidian female error changed: {exc}", file=sys.stderr)
            return 2
    else:
        print("qidian female rank was fetched", file=sys.stderr)
        return 2
    checks += 1
    empty = parse_qidian_mobile_rank_ssr("<html></html>", category="mobile-yuepiao", limit=5)
    if empty.ok or empty.failure_code != "ssr_marker_missing":
        print("missing qidian marker did not fail", file=sys.stderr)
        return 2
    checks += 1
    bridge = Path(__file__).resolve().parents[1]
    if str(bridge) not in sys.path:
        sys.path.insert(0, str(bridge))
    try:
        from ciweimao_app.api import Session
        from ciweimao_app.protocol import sign_request
    except ModuleNotFoundError as exc:
        print(f"ciweimao missing module: {exc.name}", file=sys.stderr)
        return 2
    signed = sign_request("acct", "2.9.365", "0011223344556677")
    if signed.get("rand_str") != "0011223344556677" or len(signed.get("p") or "") < 40:
        print("ciweimao client sign failed", file=sys.stderr)
        return 2
    if not callable(Session):
        print("ciweimao client session missing", file=sys.stderr)
        return 2
    from .ciweimao_egress import build_proxy_url

    if build_proxy_url("203.0.113.8:8080", "", "") != "http://203.0.113.8:8080":
        print("ciweimao proxy endpoint failed", file=sys.stderr)
        return 2
    if build_proxy_url("203.0.113.8:8080", "user", "pw") != "http://user:pw@203.0.113.8:8080":
        print("ciweimao proxy auth endpoint failed", file=sys.stderr)
        return 2
    checks += 1
    source = ciweimao_source("fans_value:week")
    parsed = parse_ciweimao_rank(
        {
            "code": "100000",
            "data": {
                "book_list": [{
                    "book_id": "1001",
                    "book_name": "猫测书",
                    "author_name": "作者丁",
                    "description": "简介丁",
                    "total_word_count": "20000",
                    "is_paid": "1",
                    "category_name": "轻小说",
                }]
            },
        },
        10,
    )
    if not parsed.ok:
        print("ciweimao fixture parse failed", file=sys.stderr)
        return 2
    ciweimao_text = render_markdown(normalize_ciweimao(source, parsed))
    if "猫测书" not in ciweimao_text or "2.0万" not in ciweimao_text or "付费书" not in ciweimao_text:
        print("ciweimao markdown missing fields", file=sys.stderr)
        return 2
    if "榜单值：[待补]" not in ciweimao_text or "rankmin-app" not in ciweimao_text:
        print("ciweimao markdown labeled the missing score", file=sys.stderr)
        return 2
    from .markdown_out import output_name

    if output_name(normalize_ciweimao(source, parsed), "20261009") != "刺猬猫粉丝值周榜_20261009.md":
        print("ciweimao filename failed", file=sys.stderr)
        return 2
    checks += 1
    try:
        resolve_ciweimao_category("desktop-click")
    except RankFetchError:
        checks += 1
    else:
        print("unknown ciweimao rank was accepted", file=sys.stderr)
        return 2
    blank = parse_ciweimao_rank(
        {"code": "100000", "data": {"book_list": [{"book_id": "1002", "book_name": ""}]}},
        5,
    )
    missing_name = normalize_ciweimao(ciweimao_source("favor"), blank)
    if missing_name.items and missing_name.items[0].book_name:
        print("blank ciweimao title was kept", file=sys.stderr)
        return 2
    checks += 1
    jjwxc_checks = _jjwxc_self_test()
    if jjwxc_checks == 0:
        return 2
    checks += jjwxc_checks
    if _partial_board_self_test() == 0:
        return 2
    checks += 1
    if _fanqie_rising_self_test() == 0:
        return 2
    checks += 1
    if _provider_self_test() == 0:
        return 2
    checks += 1
    print(f"rankmin self-test ok ({checks})")
    return 0


def _provider_self_test() -> int:
    from .fanqie import DEFAULT_CATEGORIES as fanqie_defaults
    from .providers import provider_map

    table = provider_map()
    if tuple(table) != ("qidian", "fanqie", "ciweimao", "jjwxc"):
        print("rank providers drifted", file=sys.stderr)
        return 0
    if table["qidian"].transport != "urllib" or table["jjwxc"].transport != "urllib":
        print("stdlib rank transport drifted", file=sys.stderr)
        return 0
    if table["fanqie"].transport != "curl_cffi" or table["ciweimao"].transport != "curl_cffi":
        print("curl rank transport drifted", file=sys.stderr)
        return 0
    if table["fanqie"].defaults != fanqie_defaults or "rising" in ",".join(fanqie_defaults):
        print("fanqie default categories drifted", file=sys.stderr)
        return 0
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if path.name == "net.py" or "__pycache__" in path.parts:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("from curl_cffi") or stripped.startswith("import curl_cffi"):
                offenders.append(str(path.relative_to(root)))
                break
    if offenders:
        print("curl_cffi import left in " + ", ".join(offenders), file=sys.stderr)
        return 0
    return 1


def _snapshot_for(category: str) -> object:
    from .contracts import RankItem, RankSnapshot

    label = "月票榜" if category == "yuepiao" else "畅销榜"
    return RankSnapshot(
        site="qidian",
        site_name="起点中文网",
        category=f"mobile-{category}",
        category_name=label,
        semantic_key=category,
        source_url="https://m.qidian.com/rank/",
        snapshot_at="2026-10-10T00:00:00+08:00",
        items=[RankItem(rank_position=1, book_id="1", book_name=f"隔离{category}")],
        raw_ref="fixture",
        parse_status="ok",
    )


def _partial_board_self_test() -> int:
    """One failed board must not hide a sibling that already wrote."""
    import io
    import tempfile
    from contextlib import redirect_stderr, redirect_stdout

    from . import qidian as qidian_provider

    original = qidian_provider.fetch_qidian_mobile

    def patched(category: str, limit: int = 20):
        del limit
        if category == "mm":
            return original(category, 1)
        if category == "boom":
            raise ValueError("bad book id")
        return _snapshot_for(category)

    try:
        qidian_provider.fetch_qidian_mobile = patched
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            err = io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["--out", tmp, "--date", "20261010", "--limit", "1", "--qidian", "yuepiao,mm"])
            text = out.getvalue()
            errors = err.getvalue()
            if code == 0 or "Traceback" in errors or "qidian mm failed:" not in errors or "unavailable" not in errors:
                print("partial board failure was not isolated", file=sys.stderr)
                return 0
            if "起点月票榜_20261010.md" not in text or "隔离yuepiao" not in Path(tmp, "起点月票榜_20261010.md").read_text(encoding="utf-8"):
                print("partial board success was not printed", file=sys.stderr)
                return 0
            out = io.StringIO()
            err = io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["--out", tmp, "--date", "20261010", "--limit", "1", "--qidian", "yuepiao,hotsales"])
            text = out.getvalue()
            if code != 0 or "起点月票榜_20261010.md" not in text or "起点畅销榜_20261010.md" not in text or err.getvalue():
                print("full board success did not exit 0", file=sys.stderr)
                return 0
            out = io.StringIO()
            err = io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["--out", tmp, "--date", "20261010", "--limit", "1", "--qidian", "yuepiao,boom"])
            errors = err.getvalue()
            if code == 0 or "Traceback" in errors or "qidian boom failed:" not in errors or "bad book id" not in errors:
                print("board value error was not isolated", file=sys.stderr)
                return 0
            if "起点月票榜_20261010.md" not in out.getvalue():
                print("board value error dropped the sibling", file=sys.stderr)
                return 0
    finally:
        qidian_provider.fetch_qidian_mobile = original
    return 1


def _fanqie_rising_self_test() -> int:
    from .fanqie import LANDING_SOURCE_URL

    class _Landing:
        def __init__(self, books: list[dict[str, object]]) -> None:
            self.books = books
            self.calls: list[dict[str, object]] = []

        def category_landing(self, category_id: str, **kwargs: object) -> dict[str, object]:
            self.calls.append({"category_id": category_id, **kwargs})
            return {"data": {"book_list": self.books}}

    kept = {
        "book_id": "1",
        "book_name": "留下",
        "author": "作者",
        "abstract": "简介",
        "creation_status": "1",
        "word_number": 299999,
    }
    paired = {
        "book_id": "2",
        "book_name": "双字段留下",
        "author": "作者",
        "abstract": "简介",
        "creationStatus": 1,
        "word_number": "12万",
        "wordNumber": 120000,
    }
    dropped = [
        {"book_id": "3", "book_name": "完结", "author": "作者", "abstract": "简介", "creation_status": "0", "word_number": 1000},
        {"book_id": "4", "book_name": "无状态", "author": "作者", "abstract": "简介", "word_number": 1000},
        {"book_id": "5", "book_name": "无字数", "author": "作者", "abstract": "简介", "creation_status": 1},
        {"book_id": "6", "book_name": "万字", "author": "作者", "abstract": "简介", "creation_status": "1", "word_number": "30万"},
        {"book_id": "7", "book_name": "到顶", "author": "作者", "abstract": "简介", "creation_status": "1", "word_number": 300000},
        {"book_id": "8", "book_name": "双字段到顶", "author": "作者", "abstract": "简介", "creation_status": "1", "word_number": "29万", "wordNumber": 300000},
    ]
    rising = _Landing([kept, paired, *dropped])
    snapshot = fetch_fanqie_rank("male-rising-dushinaodong", 20, client=rising)
    names = [item.book_name for item in snapshot.items]
    if names != ["留下", "双字段留下"]:
        print("fanqie rising keep/drop failed", file=sys.stderr)
        return 0
    if "/rank/" in snapshot.source_url or "new_category/landing" not in snapshot.source_url:
        print("fanqie source url is still a web rank path", file=sys.stderr)
        return 0
    if snapshot.source_url != LANDING_SOURCE_URL:
        print("fanqie source url drifted", file=sys.stderr)
        return 0
    if "new_category/landing" not in render_markdown(snapshot):
        print("fanqie markdown source missing the landing path", file=sys.stderr)
        return 0
    call = rising.calls[0]
    if "book_status" not in call or "word_number" not in call:
        print("fanqie rising filters were not sent", file=sys.stderr)
        return 0
    hot_books = [{"book_id": "9", "book_name": "热门书", "author": "作者", "abstract": "简介", "creation_status": "0"}]
    hot = _Landing(hot_books)
    hot_snapshot = fetch_fanqie_rank("male-hot-xifangqihuan", 5, client=hot)
    newbook = _Landing([{"book_id": "10", "book_name": "最新书", "author": "作者", "abstract": "简介"}])
    new_snapshot = fetch_fanqie_rank("male-newbook-xifangqihuan", 5, client=newbook)
    if hot_snapshot.items[0].book_name != "热门书" or new_snapshot.items[0].book_name != "最新书":
        print("fanqie hot or newbook dropped a book", file=sys.stderr)
        return 0
    for recorded in (hot.calls[0], newbook.calls[0]):
        if "book_status" in recorded or "word_number" in recorded:
            print("fanqie hot or newbook sent rising filters", file=sys.stderr)
            return 0
    if "/rank/" in hot_snapshot.source_url or "/rank/" in new_snapshot.source_url:
        print("fanqie hot source url is a web rank path", file=sys.stderr)
        return 0
    return 1


def _jjwxc_self_test() -> int:
    import json
    from urllib.parse import parse_qsl, urlparse

    bridge = Path(__file__).resolve().parents[1]
    if str(bridge) not in sys.path:
        sys.path.insert(0, str(bridge))
    try:
        from jjwxc_app.http import build_android_headers
        from jjwxc_app.rank import (
            INDEX_ONLY_BOARDS,
            RANK_BOARD_NAMES,
            RANK_BOARDS,
            build_rank_index_url,
            build_rank_url,
            fetch_rank_pages,
            parse_rank_page,
        )
    except ModuleNotFoundError as exc:
        print(f"jjwxc missing module: {exc.name}", file=sys.stderr)
        return 0
    checks = 0
    if len(RANK_BOARDS) != 72 or len(RANK_BOARD_NAMES) != 72:
        print("jjwxc catalog size failed", file=sys.stderr)
        return 0
    if RANK_BOARD_NAMES.get("natural_609") != "新晋作者榜·衍生":
        print("jjwxc label failed", file=sys.stderr)
        return 0
    if set(INDEX_ONLY_BOARDS) != {"作者积分榜", "TOP100"}:
        print("jjwxc index-only boards failed", file=sys.stderr)
        return 0
    checks += 1
    rank_keys = [key for key, _ in parse_qsl(urlparse(build_rank_url("natural_609")).query)]
    if rank_keys != ["channelBody"]:
        print("jjwxc query name failed", file=sys.stderr)
        return 0
    for version_first in (False, True):
        index_keys = [key for key, _ in parse_qsl(urlparse(build_rank_index_url(version_first=version_first)).query)]
        if set(index_keys) != {"channel", "version"} or "channelBody" in index_keys:
            print("jjwxc index query names failed", file=sys.stderr)
            return 0
    checks += 1
    header_names = {key.lower() for key in build_android_headers()}
    if header_names & {"cookie", "token", "appdevice", "smdeviceid"}:
        print("jjwxc forbidden header present", file=sys.stderr)
        return 0
    checks += 1
    parsed = parse_rank_page({
        "code": "200",
        "data": {
            "channelRule": {},
            "channelRuleDown": {},
            "channelid": "natural_609",
            "natural_rank_id": ["one", "two", "three"],
            "data": [{
                "novelId": "1",
                "novelName": "书甲",
                "authorName": "作者甲",
            }],
        },
    })
    if parsed.channel_name != "新晋作者榜·衍生" or parsed.books[0].novel_name != "书甲":
        print("jjwxc captured shape parse failed", file=sys.stderr)
        return 0
    direct = parse_rank_page({
        "code": 200,
        "data": {"natural_0": [{"novelId": "2", "novelName": "书乙", "authorName": "作者乙"}]},
    })
    if direct.channel_name != "natural_0":
        print("jjwxc unknown board label failed", file=sys.stderr)
        return 0
    try:
        parse_rank_page({"code": "500", "data": []})
    except ValueError:
        checks += 1
    else:
        print("jjwxc bad code was accepted", file=sys.stderr)
        return 0

    class _Pages:
        def __init__(self, pages: dict[int, list[dict[str, str]]]) -> None:
            self.pages = pages
            self.offsets: list[int] = []

        def fetch(self, url: str, headers: dict[str, str] | None = None):
            del headers
            query = dict(parse_qsl(urlparse(url).query, keep_blank_values=True))
            if list(query) != ["channelBody"]:
                raise AssertionError("query name")
            body = json.loads(query["channelBody"])
            _board, page = next(iter(body.items()))
            offset = int(page["offset"])
            self.offsets.append(offset)
            payload = {"code": "200", "data": { _board: self.pages.get(offset, []) }}
            return type("Response", (), {"status": 200, "text": json.dumps(payload, ensure_ascii=False)})()

    def _book(novel_id: int) -> dict[str, str]:
        return {"novelId": str(novel_id), "novelName": f"书{novel_id}", "authorName": "作者"}

    short = _Pages({0: [_book(i) for i in range(1, 21)], 20: [_book(i) for i in range(21, 24)]})
    paged = fetch_rank_pages("natural_609", max_pages=5, client=short)
    if paged.stop_reason != "short" or len(paged.books) != 23 or short.offsets != [0, 20]:
        print("jjwxc short page failed", file=sys.stderr)
        return 0
    repeated = _Pages({0: [_book(i) for i in range(1, 21)], 20: [_book(i) for i in range(1, 21)]})
    duplicate = fetch_rank_pages("natural_609", max_pages=4, client=repeated)
    if duplicate.stop_reason != "duplicate" or len(duplicate.books) != 20:
        print("jjwxc duplicate page failed", file=sys.stderr)
        return 0
    checks += 1
    from .jjwxc import fetch_jjwxc_rank, resolve_jjwxc_category
    from .markdown_out import output_name

    try:
        resolve_jjwxc_category("作者积分榜")
    except RankFetchError as exc:
        if "no channel tab" not in str(exc):
            print("jjwxc index-only error changed", file=sys.stderr)
            return 0
    else:
        print("jjwxc index-only board was accepted", file=sys.stderr)
        return 0
    try:
        resolve_jjwxc_category("月度排行榜")
    except RankFetchError as exc:
        if "needs a genre" not in str(exc):
            print("jjwxc genre error changed", file=sys.stderr)
            return 0
    else:
        print("jjwxc bare board was accepted", file=sys.stderr)
        return 0
    checks += 1
    snapshot = fetch_jjwxc_rank("新晋作者榜·衍生", 25, client=short)
    text = render_markdown(snapshot)
    if len(snapshot.items) != 23 or "书1" not in text or "收藏：[待补]" not in text:
        print("jjwxc markdown missing fields", file=sys.stderr)
        return 0
    if "channelBody" in snapshot.source_url or "停在短页" not in text:
        print("jjwxc markdown leaked the query or dropped the page note", file=sys.stderr)
        return 0
    if output_name(snapshot, "20261010") != "晋江新晋作者榜·衍生_20261010.md":
        print("jjwxc filename failed", file=sys.stderr)
        return 0
    checks += 1
    full_pages = {offset: [_book(offset + i) for i in range(1, 21)] for offset in range(0, 800, 20)}
    capped = _Pages(full_pages)
    try:
        fetch_jjwxc_rank("natural_609", 801, client=capped)
    except RankFetchError as exc:
        if "page cap" not in str(exc):
            print("jjwxc page cap error changed", file=sys.stderr)
            return 0
    else:
        print("jjwxc page cap was accepted", file=sys.stderr)
        return 0
    kept = fetch_jjwxc_rank("natural_609", 800, client=_Pages(full_pages))
    if "后面可能还有" not in " ".join(kept.source_notes) or len(kept.items) != 800:
        print("jjwxc full cap note failed", file=sys.stderr)
        return 0
    checks += 1

    from jjwxc_app.book import book_page_url, book_stats_url, parse_book_page, parse_book_stats
    from jjwxc_app.http import assert_public_book_request

    page_keys = [key for key, _ in parse_qsl(urlparse(book_page_url("3173202")).query)]
    stats_keys = [key for key, _ in parse_qsl(urlparse(book_stats_url("3173202")).query)]
    if page_keys != ["novelid"] or stats_keys != ["action", "novelid", "callback"]:
        print("jjwxc book query names failed", file=sys.stderr)
        return 0
    try:
        book_page_url("12abc")
    except ValueError:
        pass
    else:
        print("jjwxc book id was accepted", file=sys.stderr)
        return 0
    try:
        assert_public_book_request(book_page_url("1"), {"Cookie": "a"})
    except ValueError:
        pass
    else:
        print("jjwxc book cookie was accepted", file=sys.stderr)
        return 0
    try:
        assert_public_book_request(book_page_url("1") + "&extra=1", {})
    except ValueError:
        pass
    else:
        print("jjwxc book extra query was accepted", file=sys.stderr)
        return 0
    html = (
        '<span itemprop="wordCount">451171字</span>'
        '<span itemprop="collectedCount">1</span>'
        '<span itemprop="scoreCount">2</span>'
        '请输入验证码'
        '<span itemprop="nutritionCount"></span>'
    )
    parsed_page = parse_book_page(html)
    if parsed_page.word_count != "451171" or parsed_page.nutrition_count:
        print("jjwxc book page parse failed", file=sys.stderr)
        return 0
    parsed_stats = parse_book_stats(
        'jjwxcStats({"collectedCount":"2788810","novelscore":"57,687,396,352",'
        '"comment_count":"1","nutritionCount":"4675768"})'
    )
    if (
        parsed_stats.favorite_count != "2788810"
        or parsed_stats.score_count != "57687396352"
        or parsed_stats.nutrition_count != "4675768"
    ):
        print("jjwxc book stats parse failed", file=sys.stderr)
        return 0
    try:
        parse_book_stats("not-json")
    except ValueError:
        pass
    else:
        print("jjwxc book stats payload was accepted", file=sys.stderr)
        return 0

    class _Books(_Pages):
        def __init__(
            self,
            pages: dict[int, list[dict[str, str]]],
            stats: dict[str, str],
            page_html: str | None = None,
        ) -> None:
            super().__init__(pages)
            self.stats = stats
            self.page_html = html if page_html is None else page_html
            self.requested: list[str] = []

        def fetch_public(self, url: str):
            parsed = urlparse(url)
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            novel_id = query.get("novelid", "")
            self.requested.append(novel_id)
            if novel_id == "2":
                return type("Response", (), {"status": 200, "text": "访问过于频繁"})()
            if parsed.path.endswith("/onebook.php"):
                if list(query) != ["novelid"]:
                    raise AssertionError("book page query names")
                return type("Response", (), {"status": 200, "text": self.page_html})()
            if parsed.path.endswith("/lib/ajax.php"):
                if list(query) != ["action", "novelid", "callback"]:
                    raise AssertionError("book stats query names")
                body = query["callback"] + "(" + json.dumps(self.stats, ensure_ascii=False) + ")"
                return type("Response", (), {"status": 200, "text": body})()
            raise AssertionError("book path")

    rich = fetch_jjwxc_rank(
        "新晋作者榜·衍生",
        1,
        client=_Books({0: [_book(1)]}, {
            "collectedCount": "2788810",
            "novelscore": "57,687,396,352",
            "comment_count": "1",
            "nutritionCount": "4675768",
        }),
    )
    rich_text = render_markdown(rich)
    if (
        rich.items[0].word_count_text != "451171"
        or rich.items[0].extra.get("favorite_count") != "2788810"
        or rich.items[0].extra.get("nutrition_count") != "4675768"
        or rich.items[0].extra.get("score_count") != "57687396352"
        or "字数：451171" not in rich_text
        or "收藏：2788810" not in rich_text
        or "营养液：4675768" not in rich_text
        or "积分：57687396352" not in rich_text
        or "收藏：[待补]" in rich_text
        or "作品页补了收藏、营养液、积分、字数" not in rich_text
        or "getNovelCollectedCount" in rich_text
        or "channelBody" in rich_text
    ):
        print("jjwxc book metrics markdown failed", file=sys.stderr)
        return 0
    partial = fetch_jjwxc_rank(
        "新晋作者榜·衍生",
        1,
        client=_Books({0: [_book(1)]}, {
            "collectedCount": "9",
            "novelscore": "8",
            "comment_count": "7",
        }),
    )
    partial_text = render_markdown(partial)
    if "营养液：[待补]" not in partial_text or "没读全" not in partial_text:
        print("jjwxc partial book metrics failed", file=sys.stderr)
        return 0
    try:
        parse_book_page("访问过于频繁")
    except Exception as exc:
        if "unavailable" not in str(exc):
            print("jjwxc blocked book page changed", file=sys.stderr)
            return 0
    else:
        print("jjwxc blocked book page was accepted", file=sys.stderr)
        return 0
    nested = parse_book_page(
        '<span itemprop="wordCount">451171<span class="extra">99</span>字</span>'
        '<span itemprop="collectedCount">10<button>灌溉营养液 3</button></span>'
        '<span itemprop="scoreCount">20<!--0--></span>'
        '<div itemprop="wordCount">7<span itemprop="wordCount">8</span></div>'
        '<span itemprop="nutritionCount" content="">4675</span>'
        "请输入验证码"
    )
    if (
        nested.word_count != "451171"
        or nested.favorite_count != "10"
        or nested.score_count != "20"
        or nested.nutrition_count != "4675"
    ):
        print("jjwxc nested metric digits failed", file=sys.stderr)
        return 0
    own_only = parse_book_page('<span itemprop="scoreCount" content="">88</span>')
    comment_only = parse_book_page('<span itemprop="collectedCount"><!--0--></span>')
    outer = parse_book_page('<div itemprop="wordCount">7<span itemprop="wordCount">8</span></div>')
    if own_only.score_count != "88" or comment_only.favorite_count or outer.word_count != "7":
        print("jjwxc own-text metric failed", file=sys.stderr)
        return 0
    comment_html = (
        '<span itemprop="wordCount">11</span>'
        '<span itemprop="collectedCount">22</span>'
        '<span itemprop="scoreCount">33</span>'
        '<span itemprop="nutritionCount"><!--0--></span>'
    )
    comment_rank = fetch_jjwxc_rank(
        "新晋作者榜·衍生",
        1,
        client=_Books({0: [_book(1)]}, {"collectedCount": "22", "novelscore": "33"}, comment_html),
    )
    comment_text = render_markdown(comment_rank)
    if (
        comment_rank.items[0].extra.get("nutrition_count")
        or "营养液：[待补]" not in comment_text
        or "营养液：0" in comment_text
    ):
        print("jjwxc comment zero became a count", file=sys.stderr)
        return 0
    mixed_client = _Books(
        {0: [
            {"novelId": "12abc", "novelName": "坏书", "authorName": "甲"},
            _book(1),
            _book(2),
        ]},
        {
            "collectedCount": "2788810",
            "novelscore": "57,687,396,352",
            "nutritionCount": "4675768",
        },
    )
    mixed = fetch_jjwxc_rank("新晋作者榜·衍生", 3, client=mixed_client)
    mixed_text = render_markdown(mixed)
    if (
        "12abc" in mixed_client.requested
        or [item.book_id for item in mixed.items] != ["12abc", "1", "2"]
        or mixed.items[1].word_count_text != "451171"
        or mixed.items[0].word_count_text
        or mixed.items[2].word_count_text
        or "坏书" not in mixed_text
        or "字数：451171" not in mixed_text
        or "没读全" not in mixed_text
    ):
        print("jjwxc bad book id dropped the board", file=sys.stderr)
        return 0
    checks += 1
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rankmin")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--out", default="")
    parser.add_argument("--qidian", default="")
    parser.add_argument("--fanqie", default="")
    parser.add_argument("--ciweimao", default="")
    parser.add_argument("--jjwxc", default="")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--date", default="")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.limit < 1:
        print("limit must be at least 1", file=sys.stderr)
        return 2
    day = args.date or today_cst()
    if not _DAY.match(day):
        print("date must be YYYYMMDD", file=sys.stderr)
        return 2
    if not args.out:
        print("pass --out", file=sys.stderr)
        return 2
    if not args.qidian and not args.fanqie and not args.ciweimao and not args.jjwxc:
        print("pass --qidian, --fanqie, --ciweimao, or --jjwxc", file=sys.stderr)
        return 2
    from .providers import provider_map

    table = provider_map()
    if args.qidian == "default":
        args.qidian = ",".join(table["qidian"].defaults)
    if args.fanqie == "default":
        args.fanqie = ",".join(table["fanqie"].defaults)
    if args.ciweimao == "default":
        args.ciweimao = ",".join(table["ciweimao"].defaults)
    if args.jjwxc == "default":
        args.jjwxc = ",".join(table["jjwxc"].defaults)
    return _run_fetch(
        Path(args.out),
        day,
        args.qidian,
        args.fanqie,
        args.ciweimao,
        args.jjwxc,
        args.limit,
    )


if __name__ == "__main__":
    raise SystemExit(main())
