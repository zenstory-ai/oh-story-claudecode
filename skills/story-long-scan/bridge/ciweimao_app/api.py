"""刺猬猫 App API 的同步与异步客户端。

同步 `Session` 保留给现有 CLI；FastAPI、队列和定时任务统一使用
`AsyncSession`，两者底层均由 curl_cffi 提供。
"""

import asyncio
import inspect
import json
import sys
import threading
import time
from pathlib import Path

from . import config, content, crypto, protocol
from .web import AsyncWebChapterSession, WebChapterSession


def _rank_net():
    bridge = str(Path(__file__).resolve().parents[1])
    if bridge not in sys.path:
        sys.path.insert(0, bridge)
    import net

    return net


class ApiError(RuntimeError):
    """刺猬猫 API 返回的业务错误。"""

    def __init__(self, code: str, tip: str = ""):
        self.code = str(code)
        self.tip = tip
        super().__init__(f"API 错误 code={self.code}: {tip}")


class _ProtocolMixin:
    """同步/异步客户端共享的协议参数与响应解析。"""

    def _init_protocol(self, login_token: str, account: str,
                       device_token: str, app_version: str,
                       base_url: str, rand_factory, timeout: float,
                       web_fallback_enabled: bool = True,
                       web_min_interval: float = 3.0,
                       web_base_url: str | None = None):
        self.login_token = login_token
        self.account = account
        self.device_token = device_token
        self.app_version = app_version
        self.base_url = base_url or config.base_url_for_version(app_version)
        self._rand_factory = rand_factory
        self.timeout = float(timeout)
        self.web_fallback_enabled = bool(web_fallback_enabled)
        self.web_min_interval = max(0.0, float(web_min_interval))
        self.web_base_url = web_base_url
        self.web_fallback_used = False
        self.gt3_stamped = False
        self.gt3_stamp_origin = None
        self._gt3_stamp_lock = threading.Lock()
        self._gt3_stamp_async_lock = None

    @property
    def headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Android com.kuangxiangciweimao.novel "
                f"{self.app_version}"
            ),
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def _auth_params(self) -> dict:
        params = {
            "login_token": self.login_token,
            "account": self.account,
            "device_token": self.device_token,
            "app_version": self.app_version,
        }
        if config.uses_signed_transport(self.app_version):
            rand_str = self._rand_factory() if self._rand_factory else None
            params.update(protocol.sign_request(
                self.account,
                self.app_version,
                rand_str=rand_str,
            ))
        return params

    def _request_params(self, extra_params: dict = None) -> dict:
        params = self._auth_params()
        if extra_params:
            params.update(extra_params)
        return params

    @property
    def request_timeout(self) -> float:
        """返回请求超时，兼容绕过 ``__init__`` 的测试替身。"""
        return float(getattr(self, "timeout", 30))

    @property
    def request_attempts(self) -> int:
        return max(1, int(getattr(self, "max_retries", 2)) + 1)

    @property
    def retry_backoff(self) -> float:
        return max(0, float(getattr(self, "_retry_backoff", 0.25)))

    @property
    def transient_api_attempts(self) -> int:
        return max(1, int(getattr(self, "transient_api_retries", 1)) + 1)

    def _decode_response(self, response) -> dict:
        if response.status_code != 200:
            raise RuntimeError(
                f"HTTP {response.status_code}: {response.text[:200]}")
        try:
            raw = response.text.strip()
            if raw.startswith("{"):
                data = json.loads(raw)
            else:
                plaintext = crypto.decrypt_response_for_version(
                    raw, self.app_version)
                data = json.loads(plaintext)
        except Exception as exc:
            raise RuntimeError(f"解密/解析失败: {exc}") from exc

        code = str(data.get("code", ""))
        if code != "100000":
            tip = data.get("tip", "")
            if code == "200100":
                raise RuntimeError("login_token 已过期，请重新提取")
            raise ApiError(code, tip)
        return data

    @staticmethod
    def _search_params(keyword: str, page: int, count: int) -> dict:
        return {
            "key": keyword,
            "page": str(page),
            "count": str(max(1, min(int(count), 10))),
            "category_index": "0",
            "filter_uptime": "",
            "filter_word": "",
            "is_paid": "",
            "order": "",
            "tags": "[]",
            "up_status": "",
            "use_daguan": "0",
        }

    @staticmethod
    def _bookcity_params(page: int, count: int, order: str) -> dict:
        return {
            "tab_type": "200",
            "count": str(max(1, min(int(count), 100))),
            "page": str(page),
            "order": order,
        }

    @staticmethod
    def _rank_params(order: str, time_type: str, page: int,
                     count: int, category_index: int = 0) -> dict:
        return {
            "order": order,
            "time_type": time_type,
            "page": str(page),
            "count": str(max(1, min(int(count), 100))),
            "category_index": str(category_index),
        }

    @staticmethod
    def _dedupe_page(books, seen_ids: set[str],
                     seen_pages: set[tuple[str, ...]]):
        books = list(books or [])
        if not books:
            return [], True
        signature = tuple(str(item.get("book_id", "")) for item in books)
        if signature in seen_pages:
            return [], True
        seen_pages.add(signature)
        fresh = []
        for book in books:
            book_id = str(book.get("book_id", ""))
            if not book_id or book_id in seen_ids:
                continue
            seen_ids.add(book_id)
            fresh.append(book)
        return fresh, not fresh


class Session(_ProtocolMixin):
    """curl_cffi 同步客户端，兼容原有 CLI。"""

    def __init__(self, login_token: str, account: str,
                 device_token: str = "ciweimao_",
                 app_version: str = config.APP_VERSION,
                 base_url: str = None, rand_factory=None,
                 timeout: float = 30, impersonate: str = None,
                 max_retries: int = 2, retry_backoff: float = 0.25,
                 transient_api_retries: int = 0,
                 proxy: str = None,
                 web_fallback_enabled: bool = True,
                 web_min_interval: float = 3.0,
                 web_base_url: str | None = None,
                 web_session_factory=None):
        self._init_protocol(
            login_token, account, device_token, app_version,
            base_url, rand_factory, timeout,
            web_fallback_enabled=web_fallback_enabled,
            web_min_interval=web_min_interval,
            web_base_url=web_base_url)
        self.max_retries = max(0, int(max_retries))
        self._retry_backoff = max(0, float(retry_backoff))
        self.transient_api_retries = max(
            0, int(transient_api_retries))
        self.proxy = proxy
        self.impersonate = impersonate
        self._web_session_factory = web_session_factory
        self._web_session = None
        self._web_session_init_lock = threading.Lock()
        self._session = _rank_net().sync_session(
            headers=self.headers,
            impersonate=impersonate,
            proxy=proxy,
        )

    def close(self):
        session = getattr(self, "_session", None)
        if session is not None:
            close = getattr(session, "close", None)
            if callable(close):
                close()
        web_session = getattr(self, "_web_session", None)
        self._web_session = None
        if web_session is not None:
            web_session.close()

    @property
    def supports_web_fallback(self) -> bool:
        """标记下载编排器可传入 ``allow_web_fallback``。"""
        return True

    def _get_web_session(self):
        lock = getattr(self, "_web_session_init_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._web_session_init_lock = lock
        with lock:
            if self._web_session is None:
                kwargs = {
                    "proxy": self.proxy,
                    "timeout": self.request_timeout,
                    "impersonate": self.impersonate,
                    "min_interval": self.web_min_interval,
                }
                if self.web_base_url:
                    kwargs["base_url"] = self.web_base_url
                if self._web_session_factory is not None:
                    kwargs["session_factory"] = self._web_session_factory
                self._web_session = WebChapterSession(**kwargs)
        return self._web_session

    def _call(self, endpoint: str, extra_params: dict = None) -> dict:
        for attempt in range(self.transient_api_attempts):
            response = self._request_with_retry(
                "post",
                f"{self.base_url}{endpoint}",
                data=self._request_params(extra_params),
            )
            try:
                return self._decode_response(response)
            except ApiError as exc:
                if (exc.code != "320002"
                        or attempt + 1 >= self.transient_api_attempts):
                    raise
                if self.retry_backoff > 0:
                    time.sleep(self.retry_backoff * (2 ** attempt))

    def _request_with_retry(self, method: str, url: str, **kwargs):
        kwargs.setdefault("timeout", self.request_timeout)
        for attempt in range(self.request_attempts):
            try:
                return getattr(self._session, method)(url, **kwargs)
            except _rank_net().transport_errors():
                if attempt + 1 >= self.request_attempts:
                    raise
                if self.retry_backoff > 0:
                    time.sleep(self.retry_backoff * (2 ** attempt))

    def get_my_info(self) -> dict:
        return self._call("/reader/get_my_info")

    def get_book_info(self, book_id: str) -> dict:
        return self._call("/book/get_info_by_id", {
            "book_id": book_id, "use_daguan": "0",
        })

    def get_division_list(self, book_id: str) -> dict:
        return self._call("/book/get_division_list", {"book_id": book_id})

    def get_book_catalog(self, book_id: str) -> dict:
        return self._call(
            "/chapter/get_updated_chapter_by_division_new",
            {"book_id": book_id, "division_id": "0"},
        )

    def get_chapter_list(self, division_id: str) -> dict:
        return self._call(
            "/chapter/get_updated_chapter_by_division_id",
            {"division_id": division_id},
        )

    def get_chapter_command(self, chapter_id: str) -> str:
        data = self._call(
            "/chapter/get_chapter_cmd", {"chapter_id": chapter_id})
        return data.get("data", {}).get("command", "")

    def get_chapter_content(self, chapter_id: str, command: str,
                            *, allow_web_fallback: bool = False,
                            allow_gt3_stamp: bool = False) -> str:
        try:
            data = self._call("/chapter/get_cpt_ifm", {
                "chapter_id": chapter_id,
                "chapter_command": command,
            })
        except ApiError as exc:
            if exc.code == "310017" and allow_gt3_stamp:
                try:
                    triple = self._ensure_gt3_stamp()
                    if triple is None:
                        data = self._call("/chapter/get_cpt_ifm", {
                            "chapter_id": chapter_id,
                            "chapter_command": command,
                        })
                    else:
                        data = self.retry_chapter_after_gt3(
                            chapter_id, command, triple)
                except Exception:
                    if (not allow_web_fallback
                            or not getattr(self, "web_fallback_enabled", False)):
                        raise
                    self.web_fallback_used = True
                    return self._get_web_session().get_chapter_content(
                        chapter_id)
            elif (exc.code == "310017" and allow_web_fallback
                    and getattr(self, "web_fallback_enabled", False)):
                self.web_fallback_used = True
                return self._get_web_session().get_chapter_content(chapter_id)
            else:
                raise
        return self._decode_chapter_payload(data, command)

    def _decode_chapter_payload(self, data: dict, command: str) -> str:
        chapter_info = data.get("data", {}).get("chapter_info", {})
        txt_content = chapter_info.get("txt_content", "")
        if not txt_content:
            return ""
        if str(txt_content).startswith(("http://", "https://")):
            response = self._request_with_retry(
                "get",
                txt_content,
                headers={"Accept-Encoding": "gzip"},
            )
            response.raise_for_status()
            return content.decode_cdn_payload(response.content)
        plaintext = crypto.decrypt_chapter(txt_content, command)
        return content.normalize_chapter_text(
            plaintext.decode("utf-8", errors="replace"))

    def _ensure_gt3_stamp(self):
        if getattr(self, "gt3_stamped", False):
            return None
        lock = getattr(self, "_gt3_stamp_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._gt3_stamp_lock = lock
        with lock:
            if getattr(self, "gt3_stamped", False):
                return None
            return self.stamp_gt3()

    def first_register_gt3(self, *, now_ms: int | None = None):
        """拉官方 GT3 API1。不求解 ``ajax.php``。"""
        from . import gt3
        return gt3.first_register(self, now_ms=now_ms)

    def bind_gt3(self, *, w_provider=None, now_ms: int | None = None):
        """完整 GT3 bind。默认 ``Gt3BindNotReady``；传入 ``w_provider`` 才求解。"""
        from . import gt3
        return gt3.bind(self, w_provider=w_provider, now_ms=now_ms)

    def stamp_gt3(self, *, prefer: str = "aes-rsa", now_ms: int | None = None):
        """fullpage 9.2.0 纯算 ``w`` bind。"""
        from . import gt3_w
        provider = gt3_w.FullpageWProvider(prefer=prefer)
        triple = self.bind_gt3(w_provider=provider, now_ms=now_ms)
        self.gt3_stamped = True
        self.gt3_stamp_origin = provider.origin
        return triple

    def retry_chapter_after_gt3(self, chapter_id: str, command: str, triple):
        """带官方三元组重试 ``get_cpt_ifm``。假三元组会 280002。"""
        from . import gt3
        return self._call("/chapter/get_cpt_ifm", gt3.retry_chapter_params({
            "chapter_id": chapter_id,
            "chapter_command": command,
        }, triple))

    def get_shelf_list(self) -> list[dict]:
        data = self._call("/bookshelf/get_shelf_list")
        return data.get("data", {}).get("shelf_list", [])

    def get_shelf_books(self, shelf_id: str,
                        page: int = 1, count: int = 50) -> list[dict]:
        data = self._call("/bookshelf/get_shelf_book_list", {
            "shelf_id": shelf_id,
            "page": str(page),
            "count": str(count),
        })
        return data.get("data", {}).get("book_list", [])

    def get_all_shelf_books(self, shelf_id: str = None) -> list[dict]:
        all_books = []
        seen_ids = set()
        shelves = ([{"shelf_id": shelf_id}] if shelf_id
                   else self.get_shelf_list())
        for shelf in shelves:
            sid = shelf.get("shelf_id", "")
            shelf_name = shelf.get("shelf_name", sid)
            page = 1
            seen_pages = set()
            while True:
                books = self.get_shelf_books(sid, page=page, count=50)
                signature = tuple(
                    str(item.get("book_info", {}).get("book_id", ""))
                    for item in books)
                if not books or signature in seen_pages:
                    break
                seen_pages.add(signature)
                for item in books:
                    info = dict(item.get("book_info", {}))
                    book_id = str(info.get("book_id", ""))
                    if not book_id or book_id in seen_ids:
                        continue
                    seen_ids.add(book_id)
                    info["_shelf_name"] = shelf_name
                    all_books.append(info)
                if len(books) < 50:
                    break
                page += 1
        return all_books

    def search_books(self, keyword: str, page: int = 0,
                     count: int = 10) -> dict:
        return self._call(
            "/bookcity/get_filter_search_book_list",
            self._search_params(keyword, page, count),
        )

    def iter_search_books(self, keyword: str, max_pages: int = None,
                          count: int = 10):
        yield from self._iter_book_pages(
            lambda page: self.search_books(
                keyword, page=page, count=count)
            .get("data", {}).get("book_list", []),
            max_pages=max_pages,
        )

    def get_bookcity_books(self, page: int = 0, count: int = 100,
                           order: str = "uptime") -> list[dict]:
        data = self._call(
            "/bookcity/get_filter_book_list",
            self._bookcity_params(page, count, order),
        )
        return data.get("data", {}).get("book_list", [])

    def iter_all_books(self, max_pages: int = None, count: int = 100,
                       order: str = "uptime"):
        yield from self._iter_book_pages(
            lambda page: self.get_bookcity_books(
                page=page, count=count, order=order),
            max_pages=max_pages,
        )

    def get_rank_books(self, order: str, time_type: str,
                       page: int = 0, count: int = 10,
                       category_index: int = 0) -> list[dict]:
        data = self._call(
            "/bookcity/get_rank_book_list",
            self._rank_params(
                order, time_type, page, count, category_index),
        )
        return data.get("data", {}).get("book_list", [])

    @staticmethod
    def _iter_book_pages(fetch_page, max_pages: int = None):
        seen_ids: set[str] = set()
        seen_pages: set[tuple[str, ...]] = set()
        page = 0
        while max_pages is None or page < max_pages:
            fresh, stop = _ProtocolMixin._dedupe_page(
                fetch_page(page), seen_ids, seen_pages)
            yield from fresh
            if stop:
                break
            page += 1


class AsyncSession(_ProtocolMixin):
    """curl_cffi 异步客户端，供 FastAPI、队列与调度器使用。"""

    def __init__(self, login_token: str, account: str,
                 device_token: str = "ciweimao_",
                 app_version: str = config.APP_VERSION,
                 base_url: str = None, rand_factory=None,
                 timeout: float = 30, impersonate: str = None,
                 max_clients: int = 10, max_retries: int = 2,
                 retry_backoff: float = 0.25,
                 transient_api_retries: int = 0,
                 proxy: str = None,
                 web_fallback_enabled: bool = True,
                 web_min_interval: float = 3.0,
                 web_base_url: str | None = None,
                 web_session_factory=None):
        self._init_protocol(
            login_token, account, device_token, app_version,
            base_url, rand_factory, timeout,
            web_fallback_enabled=web_fallback_enabled,
            web_min_interval=web_min_interval,
            web_base_url=web_base_url)
        self.max_retries = max(0, int(max_retries))
        self._retry_backoff = max(0, float(retry_backoff))
        self.transient_api_retries = max(
            0, int(transient_api_retries))
        self.proxy = proxy
        self.impersonate = impersonate
        self._web_session_factory = web_session_factory
        self._web_session = None
        self._web_session_init_lock = threading.Lock()
        self._session = _rank_net().async_session(
            headers=self.headers,
            impersonate=impersonate,
            max_clients=max(1, int(max_clients)),
            proxy=proxy,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        await self.close()

    async def close(self):
        session = getattr(self, "_session", None)
        if session is not None:
            close = getattr(session, "close", None)
            if callable(close):
                result = close()
                if inspect.isawaitable(result):
                    await result
        web_session = getattr(self, "_web_session", None)
        self._web_session = None
        if web_session is not None:
            close = getattr(web_session, "close", None)
            if callable(close):
                result = close()
                if inspect.isawaitable(result):
                    await result

    @property
    def supports_web_fallback(self) -> bool:
        """标记下载编排器可传入 ``allow_web_fallback``。"""
        return True

    def _get_web_session(self):
        lock = getattr(self, "_web_session_init_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._web_session_init_lock = lock
        with lock:
            if self._web_session is None:
                kwargs = {
                    "proxy": self.proxy,
                    "timeout": self.request_timeout,
                    "impersonate": self.impersonate,
                    "min_interval": self.web_min_interval,
                }
                if self.web_base_url:
                    kwargs["base_url"] = self.web_base_url
                if self._web_session_factory is not None:
                    kwargs["session_factory"] = self._web_session_factory
                self._web_session = AsyncWebChapterSession(**kwargs)
        return self._web_session

    async def _call(self, endpoint: str,
                    extra_params: dict = None) -> dict:
        for attempt in range(self.transient_api_attempts):
            response = await self._request_with_retry(
                "post",
                f"{self.base_url}{endpoint}",
                data=self._request_params(extra_params),
            )
            try:
                return self._decode_response(response)
            except ApiError as exc:
                if (exc.code != "320002"
                        or attempt + 1 >= self.transient_api_attempts):
                    raise
                if self.retry_backoff > 0:
                    await asyncio.sleep(
                        self.retry_backoff * (2 ** attempt))

    async def _request_with_retry(self, method: str, url: str, **kwargs):
        kwargs.setdefault("timeout", self.request_timeout)
        for attempt in range(self.request_attempts):
            try:
                return await getattr(self._session, method)(url, **kwargs)
            except _rank_net().transport_errors():
                if attempt + 1 >= self.request_attempts:
                    raise
                if self.retry_backoff > 0:
                    await asyncio.sleep(
                        self.retry_backoff * (2 ** attempt))

    async def get_my_info(self) -> dict:
        return await self._call("/reader/get_my_info")

    async def get_book_info(self, book_id: str) -> dict:
        return await self._call("/book/get_info_by_id", {
            "book_id": book_id, "use_daguan": "0",
        })

    async def get_division_list(self, book_id: str) -> dict:
        return await self._call(
            "/book/get_division_list", {"book_id": book_id})

    async def get_book_catalog(self, book_id: str) -> dict:
        return await self._call(
            "/chapter/get_updated_chapter_by_division_new",
            {"book_id": book_id, "division_id": "0"},
        )

    async def get_chapter_list(self, division_id: str) -> dict:
        return await self._call(
            "/chapter/get_updated_chapter_by_division_id",
            {"division_id": division_id},
        )

    async def get_chapter_command(self, chapter_id: str) -> str:
        data = await self._call(
            "/chapter/get_chapter_cmd", {"chapter_id": chapter_id})
        return data.get("data", {}).get("command", "")

    async def get_chapter_content(self, chapter_id: str,
                                  command: str,
                                  *, allow_web_fallback: bool = False,
                                  allow_gt3_stamp: bool = False) -> str:
        try:
            data = await self._call("/chapter/get_cpt_ifm", {
                "chapter_id": chapter_id,
                "chapter_command": command,
            })
        except ApiError as exc:
            if exc.code == "310017" and allow_gt3_stamp:
                try:
                    triple = await self._ensure_gt3_stamp_async()
                    if triple is None:
                        data = await self._call("/chapter/get_cpt_ifm", {
                            "chapter_id": chapter_id,
                            "chapter_command": command,
                        })
                    else:
                        data = await self.retry_chapter_after_gt3(
                            chapter_id, command, triple)
                except Exception:
                    if (not allow_web_fallback
                            or not getattr(self, "web_fallback_enabled", False)):
                        raise
                    self.web_fallback_used = True
                    return await self._get_web_session().get_chapter_content(
                        chapter_id)
            elif (exc.code == "310017" and allow_web_fallback
                    and getattr(self, "web_fallback_enabled", False)):
                self.web_fallback_used = True
                return await self._get_web_session().get_chapter_content(
                    chapter_id)
            else:
                raise
        return await self._decode_chapter_payload_async(data, command)

    async def _decode_chapter_payload_async(self, data: dict, command: str) -> str:
        chapter_info = data.get("data", {}).get("chapter_info", {})
        txt_content = chapter_info.get("txt_content", "")
        if not txt_content:
            return ""
        if str(txt_content).startswith(("http://", "https://")):
            response = await self._request_with_retry(
                "get",
                txt_content,
                headers={"Accept-Encoding": "gzip"},
            )
            response.raise_for_status()
            return content.decode_cdn_payload(response.content)
        plaintext = crypto.decrypt_chapter(txt_content, command)
        return content.normalize_chapter_text(
            plaintext.decode("utf-8", errors="replace"))

    async def _ensure_gt3_stamp_async(self):
        if getattr(self, "gt3_stamped", False):
            return None
        lock = getattr(self, "_gt3_stamp_async_lock", None)
        if lock is None:
            guard = getattr(self, "_gt3_stamp_lock", None)
            if guard is None:
                guard = threading.Lock()
                self._gt3_stamp_lock = guard
            with guard:
                if getattr(self, "_gt3_stamp_async_lock", None) is None:
                    self._gt3_stamp_async_lock = asyncio.Lock()
                lock = self._gt3_stamp_async_lock
        async with lock:
            if getattr(self, "gt3_stamped", False):
                return None
            return await self.stamp_gt3()

    async def first_register_gt3(self, *, now_ms: int | None = None):
        from . import gt3
        return await gt3.first_register_async(self, now_ms=now_ms)

    async def bind_gt3(self, *, w_provider=None, now_ms: int | None = None):
        from . import gt3
        return await gt3.bind_async(self, w_provider=w_provider, now_ms=now_ms)

    async def stamp_gt3(self, *, prefer: str = "aes-rsa",
                        now_ms: int | None = None):
        from . import gt3, gt3_w
        api1 = await gt3.first_register_async(self, now_ms=now_ms)
        provider = gt3_w.FullpageWProvider(prefer=prefer)
        triple = await asyncio.to_thread(provider.complete_bind, api1)
        self.gt3_stamped = True
        self.gt3_stamp_origin = provider.origin
        return triple

    async def retry_chapter_after_gt3(self, chapter_id: str, command: str,
                                      triple):
        from . import gt3
        return await self._call(
            "/chapter/get_cpt_ifm",
            gt3.retry_chapter_params({
                "chapter_id": chapter_id,
                "chapter_command": command,
            }, triple),
        )

    async def search_books(self, keyword: str, page: int = 0,
                           count: int = 10) -> dict:
        return await self._call(
            "/bookcity/get_filter_search_book_list",
            self._search_params(keyword, page, count),
        )

    async def iter_search_books(self, keyword: str,
                                max_pages: int = None,
                                count: int = 10):
        seen_ids: set[str] = set()
        seen_pages: set[tuple[str, ...]] = set()
        page = 0
        while max_pages is None or page < max_pages:
            data = await self.search_books(keyword, page=page, count=count)
            fresh, stop = self._dedupe_page(
                data.get("data", {}).get("book_list", []),
                seen_ids, seen_pages)
            for book in fresh:
                yield book
            if stop:
                break
            page += 1

    async def get_bookcity_books(self, page: int = 0,
                                 count: int = 100,
                                 order: str = "uptime") -> list[dict]:
        data = await self._call(
            "/bookcity/get_filter_book_list",
            self._bookcity_params(page, count, order),
        )
        return data.get("data", {}).get("book_list", [])

    async def iter_all_books(self, max_pages: int = None,
                             count: int = 100,
                             order: str = "uptime"):
        seen_ids: set[str] = set()
        seen_pages: set[tuple[str, ...]] = set()
        page = 0
        while max_pages is None or page < max_pages:
            books = await self.get_bookcity_books(
                page=page, count=count, order=order)
            fresh, stop = self._dedupe_page(
                books, seen_ids, seen_pages)
            for book in fresh:
                yield book
            if stop:
                break
            page += 1

    async def get_rank_books(self, order: str, time_type: str,
                             page: int = 0, count: int = 10,
                             category_index: int = 0) -> list[dict]:
        data = await self._call(
            "/bookcity/get_rank_book_list",
            self._rank_params(
                order, time_type, page, count, category_index),
        )
        return data.get("data", {}).get("book_list", [])
