"""网页章节链客户端（与 App API 凭据完全隔离）。

刺猬猫网页章节使用另一套接口，不需要 App 的 ``account``、``login_token``、
``device_token``、``app_version`` 或签名参数：

``GET /chapter/<id>`` -> ``POST /chapter/ajax_get_session_code`` ->
``POST /chapter/get_book_chapter_detail_info``。

本模块故意不复用 :mod:`client.api` 的 ``Session``，也不把 App 参数拼进网页
请求。网页登录 Cookie 若由调用方显式提供，仍会原样保留（VIP 章节可能需要
站点 Cookie）；这和把 App 凭据作为表单/查询参数发送是两回事。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import inspect
import re
import sys
import threading
import time
from pathlib import Path
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from types import TracebackType
from typing import Any, ClassVar, Self
from urllib.parse import quote, urlsplit

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

WEB_BASE_URL = "https://www.ciweimao.com"
WEB_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)
WEB_SESSION_PATH = "/chapter/ajax_get_session_code"
WEB_DETAIL_PATH = "/chapter/get_book_chapter_detail_info"

_APP_CREDENTIAL_KEYS = frozenset({
    "account",
    "login_token",
    "device_token",
    "app_version",
    "rand_str",
    "p",
    "signatures",
    "chapter_command",
})
_COOKIE_HEADER = "Cookie"
_SET_COOKIE_HEADER = "set-cookie"


class WebChapterError(RuntimeError):
    """网页章节请求或业务响应错误。"""

    def __init__(
        self,
        message: str,
        *,
        stage: str = "",
        code: str | None = None,
        tip: str = "",
        status_code: int | None = None,
    ) -> None:
        self.stage = stage
        self.code = str(code) if code is not None else None
        self.tip = str(tip or "")
        self.status_code = status_code
        super().__init__(message)


class WebDecryptError(ValueError):
    """网页章节双层密文格式或密钥错误。"""


# 兼容更直观的别名；错误类型仍然保持与 App ``ApiError`` 分离。
WebAPIError = WebChapterError


class WebCookieJar(MutableMapping[str, str]):
    """轻量、可测试的站点 Cookie jar。

    网页接口只需要同一主域下的 Cookie，因此用名称到值的映射足够表达
    ``Set-Cookie`` 轮换，同时避免把 curl 的内部 Cookie 实现暴露给调用方。
    ``login_token`` 之类的网页 Cookie 可以存在这里，但不会被转成 App 表单
    参数。
    """

    def __init__(self, cookies: Mapping[str, str] | str | None = None) -> None:
        self._values: dict[str, str] = {}
        if cookies:
            self.update(cookies)

    def __getitem__(self, key: str) -> str:
        return self._values[key]

    def __setitem__(self, key: str, value: str) -> None:
        key = str(key).strip()
        if key:
            self._values[key] = str(value)

    def __delitem__(self, key: str) -> None:
        del self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def update(  # type: ignore[override]
        self,
        other: Mapping[str, str] | str | Sequence[tuple[str, str]] = (),
        **kwargs: str,
    ) -> None:
        if isinstance(other, str):
            parsed = SimpleCookie()
            parsed.load(other)
            for morsel in parsed.values():
                self[morsel.key] = morsel.value
        elif isinstance(other, Mapping):
            for key, value in other.items():
                self[key] = value
        else:
            for key, value in other:
                self[key] = value
        for key, value in kwargs.items():
            self[key] = value

    def copy(self) -> WebCookieJar:
        return WebCookieJar(self._values)

    def as_dict(self) -> dict[str, str]:
        return dict(self._values)

    def header_value(self) -> str:
        return "; ".join(f"{key}={value}" for key, value in self._values.items())

    def ingest_set_cookie(self, values: Sequence[str] | str) -> dict[str, tuple[str | None, str | None]]:
        """合并一个或多个 ``Set-Cookie``，返回 ``name -> (old, new)`` 变更。"""
        if isinstance(values, str):
            values = [values]
        changes: dict[str, tuple[str | None, str | None]] = {}
        for raw in values:
            parsed = SimpleCookie()
            try:
                parsed.load(raw)
            except Exception:  # noqa: BLE001 - malformed Set-Cookie is ignorable
                continue
            for morsel in parsed.values():
                name = morsel.key
                old = self._values.get(name)
                # Max-Age=0 / an expired cookie removes the current value.
                max_age = str(morsel["max-age"] or "").strip().lower()
                if max_age == "0":
                    self._values.pop(name, None)
                    new: str | None = None
                else:
                    self[name] = morsel.value
                    new = morsel.value
                if old != new:
                    changes[name] = (old, new)
        return changes


@dataclass(frozen=True, slots=True)
class WebChapterResult:
    """一次网页章节读取结果，不包含原始密文。"""

    chapter_id: str
    # access key 是短期会话材料；禁止在 dataclass repr/日志中回显。
    access_key: str = field(repr=False)
    html: str
    text: str
    cookies: Mapping[str, str] = field(repr=False)

    @property
    def content_html(self) -> str:
        return self.html

    @property
    def content_text(self) -> str:
        return self.text

    @property
    def content(self) -> str:
        return self.text

    def __str__(self) -> str:
        return self.text


def _normalise_key_name(value: str) -> str:
    return value.strip().lower().replace("-", "_")


def _reject_app_headers(headers: Mapping[str, str] | None) -> None:
    if not headers:
        return
    for name in headers:
        if _normalise_key_name(str(name)) in _APP_CREDENTIAL_KEYS:
            raise ValueError(
                f"网页 session 禁止 App credential header: {name}")


def _safe_b64decode(value: str | bytes, label: str) -> bytes:
    if isinstance(value, str):
        value = value.encode("ascii", "strict")
    value = re.sub(rb"\s+", b"", bytes(value))
    if not value:
        raise WebDecryptError(f"{label} 为空")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        # 某些抓包工具会把 URL-safe 字符带入；只在标准解码失败时宽容一次。
        try:
            return base64.urlsafe_b64decode(value + b"=" * (-len(value) % 4))
        except (binascii.Error, ValueError) as second_exc:
            raise WebDecryptError(f"{label} 不是有效 Base64") from second_exc


def _decrypt_layer(encoded: str | bytes, key_b64: str, label: str) -> bytes:
    raw = _safe_b64decode(encoded, f"{label} 密文")
    if len(raw) < AES.block_size:
        raise WebDecryptError(f"{label} 密文缺少 IV")
    iv, ciphertext = raw[: AES.block_size], raw[AES.block_size :]
    # 兼容少数 OpenSSL 风格载荷；正常网页载荷不带该标记。
    if ciphertext.startswith(b"Salted__"):
        if len(ciphertext) < 24:
            raise WebDecryptError(f"{label} Salted__ 载荷不完整")
        ciphertext = ciphertext[16:]
    if not ciphertext or len(ciphertext) % AES.block_size:
        raise WebDecryptError(f"{label} ciphertext 长度非法")
    key = _safe_b64decode(key_b64, f"{label} key")
    if len(key) not in (16, 24, 32):
        raise WebDecryptError(f"{label} AES key 长度非法: {len(key)}")
    try:
        plain = AES.new(key, AES.MODE_CBC, iv).decrypt(ciphertext)
        return unpad(plain, AES.block_size)
    except (ValueError, TypeError) as exc:
        raise WebDecryptError(f"{label} AES-CBC 解密失败") from exc


def decrypt_chapter_payload(
    content: str,
    keys: Sequence[str],
    access_key: str,
) -> str:
    """解密网页章节双层 AES-CBC 载荷。

    第一层 key 由 ``access_key`` 最后一个字符选取，第二层 key 由首字符
    选取；索引使用 Unicode code point（``ord``），不能把字符强转成数字。
    每层格式都是 ``Base64(IV || AES-CBC(ciphertext))``，第一层明文仍是
    Base64，第二层明文是 UTF-8 HTML。
    """
    if not content or not keys or not access_key:
        raise WebDecryptError("章节密文、encryt_keys 或 access_key 缺失")
    try:
        first_key = keys[ord(access_key[-1]) % len(keys)]
        second_key = keys[ord(access_key[0]) % len(keys)]
    except (IndexError, TypeError) as exc:
        raise WebDecryptError("章节密钥选择失败") from exc
    inner = _decrypt_layer(content, str(first_key), "第一层")
    outer = _decrypt_layer(inner, str(second_key), "第二层")
    try:
        return outer.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WebDecryptError("第二层明文不是 UTF-8 HTML") from exc


# 便于调用方按习惯命名。
decrypt_web_chapter = decrypt_chapter_payload
decrypt_chapter = decrypt_chapter_payload


class _ChapterTextParser(HTMLParser):
    """提取 ``p`` 段落并丢弃网页水印 span。"""

    _BLOCK_TAGS: ClassVar[set[str]] = {
        "div", "li", "h1", "h2", "h3", "h4", "section"
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.paragraphs: list[str] = []
        self._skip_depth = 0
        self._block_depth = 0

    def _flush(self) -> None:
        value = "".join(self.parts)
        value = value.replace("\xa0", " ")
        value = re.sub(r"[ \t\f\v]+", " ", value)
        value = re.sub(r" *\n *", "\n", value).strip()
        if value:
            self.paragraphs.append(value)
        self.parts = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.lower()
        if self._skip_depth:
            self._skip_depth += 1
            return
        if tag in {"span", "script", "style"}:
            self._skip_depth = 1
        elif tag == "p":
            self._flush()
        elif tag == "br" or tag in self._BLOCK_TAGS and self.parts:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # ``<span/>`` must not leave the parser in skip mode.  For ordinary
        # self-closing tags the regular start/end handling is sufficient.
        tag = tag.lower()
        if self._skip_depth or tag in {"span", "script", "style"}:
            return
        self.handle_starttag(tag, attrs)
        if not self._skip_depth:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "p" or tag in self._BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)

    def finish(self) -> list[str]:
        self._flush()
        return self.paragraphs


_SPAN_RE = re.compile(r"<span\b[^>]*>.*?</span\s*>", re.IGNORECASE | re.DOTALL)


def normalize_chapter_html(raw_html: str) -> str:
    """删除网页水印 ``span``，保留其它 HTML 结构。"""
    value = str(raw_html or "")
    # 循环是为了处理嵌套 span；限制轮数避免恶意输入造成无限循环。
    for _ in range(32):
        cleaned = _SPAN_RE.sub("", value)
        if cleaned == value:
            break
        value = cleaned
    return value.strip()


def normalize_chapter_text(raw_html: str) -> str:
    """把章节 HTML 规范化为纯文本，段落以单个换行分隔。"""
    parser = _ChapterTextParser()
    try:
        parser.feed(normalize_chapter_html(raw_html))
        parser.close()
    except Exception as exc:
        raise WebDecryptError("章节 HTML 解析失败") from exc
    return "\n".join(parser.finish())


def _header_values(headers: Any, name: str) -> list[str]:
    if headers is None:
        return []
    for method_name in ("get_list", "getlist", "get_all"):
        method = getattr(headers, method_name, None)
        if callable(method):
            try:
                values = method(name)
                if values:
                    return [str(item) for item in values]
            except Exception:  # noqa: BLE001 - adapter header APIs vary
                pass
    try:
        value = headers.get(name)
        if value is None:
            value = headers.get(name.title())
    except Exception:  # noqa: BLE001 - malformed test/adapter headers
        value = None
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def _response_set_cookie_values(response: Any) -> list[str]:
    values = _header_values(getattr(response, "headers", None), _SET_COOKIE_HEADER)
    if values:
        return values
    # 某些 mock/transport 只填 response.cookies，不提供 headers。
    jar = getattr(response, "cookies", None)
    if jar is None:
        return []
    result: list[str] = []
    try:
        iterator = jar.items() if hasattr(jar, "items") else jar
        for item in iterator:
            if isinstance(item, tuple) and len(item) == 2:
                result.append(f"{item[0]}={item[1]}")
            else:
                name = getattr(item, "name", getattr(item, "key", ""))
                value = getattr(item, "value", "")
                if name:
                    result.append(f"{name}={value}")
    except Exception:  # noqa: BLE001 - cookie jar adapters are best effort
        return []
    return result


def _response_status(response: Any) -> int:
    try:
        return int(response.status_code)
    except (TypeError, ValueError, AttributeError):
        return 0


def _response_text(response: Any) -> str:
    value = getattr(response, "text", "")
    if callable(value):
        value = value()
    if value is None:
        value = ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _response_json(response: Any) -> Mapping[str, Any]:
    value = getattr(response, "json", None)
    if callable(value):
        value = value()
    if isinstance(value, str):
        import json

        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise TypeError("JSON 响应不是对象")
    return value


def _rank_net():
    bridge = str(Path(__file__).resolve().parents[1])
    if bridge not in sys.path:
        sys.path.insert(0, bridge)
    import net

    return net


def _call_supported(method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """给真实 curl client 和极简 mock 都传递兼容的参数。"""
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return method(*args, **kwargs)
    parameters = signature.parameters.values()
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters):
        return method(*args, **kwargs)
    allowed = {
        p.name for p in parameters
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                      inspect.Parameter.KEYWORD_ONLY)
    }
    return method(*args, **{key: value for key, value in kwargs.items() if key in allowed})


def _instantiate(factory: Callable[..., Any], kwargs: dict[str, Any]) -> Any:
    """实例化 session_factory；仅在工厂不接受 ``impersonate`` 时降级。"""
    try:
        return _call_supported(factory, **kwargs)
    except TypeError:
        if "impersonate" not in kwargs:
            raise
        reduced = dict(kwargs)
        reduced.pop("impersonate", None)
        return _call_supported(factory, **reduced)


class _WebSessionBase:
    """同步/异步实现共享的参数、Cookie 和响应逻辑。"""

    def __init__(
        self,
        *,
        base_url: str = WEB_BASE_URL,
        timeout: float = 30.0,
        proxy: str | None = None,
        impersonate: str | None = None,
        user_agent: str = WEB_USER_AGENT,
        headers: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | str | None = None,
        client: Any = None,
        session_factory: Callable[..., Any] | None = None,
        min_interval: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] | None = None,
    ) -> None:
        _reject_app_headers(headers)
        if not str(base_url).startswith(("http://", "https://")):
            raise ValueError("base_url 必须是 http(s) URL")
        if float(timeout) <= 0:
            raise ValueError("timeout 必须大于 0")
        if float(min_interval) < 0:
            raise ValueError("min_interval 不能为负数")
        self.base_url = str(base_url).rstrip("/")
        self.timeout = float(timeout)
        self.proxy = proxy
        # curl_cffi 支持该参数；自定义 mock 不接受时由 _instantiate 忽略。
        self.impersonate = impersonate
        self.user_agent = str(user_agent)
        self._extra_headers = {str(k): str(v) for k, v in (headers or {}).items()}
        self.cookies = WebCookieJar(cookies)
        self.min_interval = float(min_interval)
        self._clock = clock
        self._sleep = sleep or time.sleep
        self._last_request_at: float | None = None
        self.cookie_changes: list[dict[str, tuple[str | None, str | None]]] = []
        # 只保留脱敏的请求元数据，便于 canary/故障定位；不记录 Cookie、
        # 请求体、访问密钥或响应正文。
        self.request_log: list[dict[str, Any]] = []
        self._owns_client = client is None
        self._session = client
        self.client = client
        self.session_factory = session_factory

    @property
    def origin(self) -> str:
        parsed = urlsplit(self.base_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def chapter_url(self, chapter_id: str | int) -> str:
        value = str(chapter_id).strip()
        if not value:
            raise ValueError("chapter_id 不能为空")
        return f"{self.base_url}/chapter/{quote(value, safe='')}"

    def _headers(self, *, ajax: bool, chapter_url: str) -> dict[str, str]:
        if ajax:
            result = {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": self.origin,
                "Referer": chapter_url,
            }
        else:
            result = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": self.origin + "/",
            }
        result["User-Agent"] = self.user_agent
        result.update(self._extra_headers)
        cookie = self.cookies.header_value()
        if cookie:
            result[_COOKIE_HEADER] = cookie
        return result

    def _ingest_cookies(self, response: Any) -> None:
        values = _response_set_cookie_values(response)
        if not values:
            return
        changes = self.cookies.ingest_set_cookie(values)
        if changes:
            self.cookie_changes.append(changes)
        # 保持底层 curl jar 也同步，防止其内部逻辑覆盖显式 Cookie header。
        jar = getattr(self._session, "cookies", None)
        if jar is not None and hasattr(jar, "update"):
            try:
                jar.update(self.cookies.as_dict())
            except Exception:  # noqa: BLE001 - syncing optional adapter jar
                pass

    def _check_http(self, response: Any, stage: str) -> None:
        status = _response_status(response)
        if status < 200 or status >= 300:
            raise WebChapterError(
                f"网页 {stage} HTTP {status}",
                stage=stage,
                status_code=status,
            )

    def _check_text_chapter_page(self, response: Any) -> None:
        """Reject image/VIP reader pages instead of treating them as text."""
        self._check_http(response, "chapter-page")
        if "J_ImgRead" in _response_text(response):
            raise WebChapterError(
                "网页章节是图片/VIP 形式，当前 fallback 仅支持文本免费章",
                stage="chapter-page",
                code="image-chapter",
            )

    def _business_payload(self, response: Any, stage: str) -> Mapping[str, Any]:
        self._check_http(response, stage)
        try:
            payload = _response_json(response)
        except Exception as exc:
            raise WebChapterError(
                f"网页 {stage} JSON 解析失败", stage=stage) from exc
        code = str(payload.get("code", ""))
        if code != "100000":
            raise WebChapterError(
                f"网页 {stage} 业务错误 code={code}",
                stage=stage,
                code=code or None,
                tip=str(payload.get("tip", "") or payload.get("error_message", "")),
            )
        return payload

    @staticmethod
    def _chapter_fields(payload: Mapping[str, Any]) -> tuple[str, Sequence[str]]:
        container: Mapping[str, Any] = payload
        if isinstance(payload.get("data"), Mapping):
            data = payload["data"]
            # 兼容镜像把章节字段包进 data 的响应。
            if "chapter_info" in data and isinstance(data["chapter_info"], Mapping):
                container = data["chapter_info"]
            else:
                container = data
        content = str(
            container.get("chapter_content", container.get("txt_content", ""))
            or ""
        )
        keys = container.get("encryt_keys", container.get("encrypt_keys", []))
        if not isinstance(keys, Sequence) or isinstance(keys, (str, bytes)):
            keys = []
        return content, [str(key) for key in keys]

    def _extract_access_key(self, payload: Mapping[str, Any], stage: str) -> str:
        value: Any = payload.get("chapter_access_key", "")
        if not value and isinstance(payload.get("data"), Mapping):
            value = payload["data"].get("chapter_access_key", "")
        value = str(value or "").strip()
        if not value:
            raise WebChapterError(
                "网页 session 响应缺少 chapter_access_key", stage=stage,
                code="missing-access-key")
        return value

    def _new_client(self, default_factory: Callable[..., Any]) -> Any:
        if self._session is not None:
            return self._session
        factory = self.session_factory or default_factory
        kwargs: dict[str, Any] = {
            "timeout": self.timeout,
            "headers": {"User-Agent": self.user_agent},
        }
        if self.proxy:
            kwargs["proxy"] = self.proxy
        if self.impersonate:
            kwargs["impersonate"] = self.impersonate
        if self.cookies:
            kwargs["cookies"] = self.cookies.as_dict()
        self._session = _instantiate(factory, kwargs)
        self.client = self._session
        return self._session

    def _before_request(self) -> None:
        if self._last_request_at is None:
            self._last_request_at = self._clock()
            return
        elapsed = self._clock() - self._last_request_at
        delay = self.min_interval - elapsed
        if delay > 0:
            result = self._sleep(delay)
            # Sync callers normally provide a sync sleep; accepting an
            # awaitable here is harmless for test doubles but cannot be
            # awaited from this method, so fail loudly rather than silently
            # dropping the delay.
            if inspect.isawaitable(result):
                raise RuntimeError("同步 WebChapterSession 的 sleep 不能是异步函数")
        self._last_request_at = self._clock()

    def _finish_result(
        self,
        chapter_id: str,
        access_key: str,
        plaintext_html: str,
    ) -> WebChapterResult:
        html = normalize_chapter_html(plaintext_html)
        text = normalize_chapter_text(html)
        if not text:
            raise WebChapterError(
                "章节解密成功但正文为空", stage="normalize", code="empty-content")
        return WebChapterResult(
            chapter_id=chapter_id,
            access_key=access_key,
            html=html,
            text=text,
            cookies=self.cookies.as_dict(),
        )


class WebChapterSession(_WebSessionBase):
    """同步网页章节客户端。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._lock = threading.Lock()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client and self._session is not None:
            close = getattr(self._session, "close", None)
            if callable(close):
                close()
        self._session = None
        self.client = None

    def _request(self, method: str, url: str, *, headers: Mapping[str, str], data: Mapping[str, str] | None = None) -> Any:
        self._before_request()
        fn = getattr(self._session, method)
        kwargs: dict[str, Any] = {"headers": dict(headers), "timeout": self.timeout}
        if data is not None:
            kwargs["data"] = dict(data)
        response = _call_supported(fn, url, **kwargs)
        self._ingest_cookies(response)
        self.request_log.append({
            "method": method.upper(),
            "path": urlsplit(url).path,
            "status": _response_status(response),
            "bytes": len(getattr(response, "content", b"") or b""),
        })
        return response

    def fetch_chapter(self, chapter_id: str | int) -> WebChapterResult:
        cid = str(chapter_id).strip()
        chapter_url = self.chapter_url(cid)
        with self._lock:
            self._new_client(_rank_net().sync_session)
            page_response = self._request(
                "get", chapter_url,
                headers=self._headers(ajax=False, chapter_url=chapter_url),
            )
            self._check_text_chapter_page(page_response)
            session_response = self._request(
                "post", f"{self.base_url}{WEB_SESSION_PATH}",
                headers=self._headers(ajax=True, chapter_url=chapter_url),
                data={"chapter_id": cid},
            )
            session_payload = self._business_payload(session_response, "session")
            access_key = self._extract_access_key(session_payload, "session")
            detail_response = self._request(
                "post", f"{self.base_url}{WEB_DETAIL_PATH}",
                headers=self._headers(ajax=True, chapter_url=chapter_url),
                data={"chapter_id": cid, "chapter_access_key": access_key},
            )
            detail_payload = self._business_payload(detail_response, "detail")
            encrypted, keys = self._chapter_fields(detail_payload)
            if not encrypted or not keys:
                raise WebChapterError(
                    "网页 detail 响应缺少 chapter_content/encryt_keys",
                    stage="detail", code="missing-content")
            try:
                plaintext = decrypt_chapter_payload(encrypted, keys, access_key)
            except WebDecryptError as exc:
                raise WebChapterError(
                    "网页章节解密失败", stage="decrypt") from exc
            return self._finish_result(cid, access_key, plaintext)

    def get_chapter_content(self, chapter_id: str | int) -> str:
        return self.fetch_chapter(chapter_id).text

    def get_chapter(self, chapter_id: str | int) -> str:
        return self.get_chapter_content(chapter_id)


class AsyncWebChapterSession(_WebSessionBase):
    """异步网页章节客户端。"""

    def __init__(self, *, sleep: Callable[[float], Any] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._lock: asyncio.Lock | None = None
        self._sleep = sleep or asyncio.sleep

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client and self._session is not None:
            close = getattr(self._session, "close", None)
            if callable(close):
                result = close()
                if inspect.isawaitable(result):
                    await result
        self._session = None
        self.client = None

    async def _before_request_async(self) -> None:
        if self._last_request_at is None:
            self._last_request_at = self._clock()
            return
        elapsed = self._clock() - self._last_request_at
        delay = self.min_interval - elapsed
        if delay > 0:
            result = self._sleep(delay)
            if inspect.isawaitable(result):
                await result
        self._last_request_at = self._clock()

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        data: Mapping[str, str] | None = None,
    ) -> Any:
        await self._before_request_async()
        fn = getattr(self._session, method)
        kwargs: dict[str, Any] = {"headers": dict(headers), "timeout": self.timeout}
        if data is not None:
            kwargs["data"] = dict(data)
        response = _call_supported(fn, url, **kwargs)
        if inspect.isawaitable(response):
            response = await response
        self._ingest_cookies(response)
        self.request_log.append({
            "method": method.upper(),
            "path": urlsplit(url).path,
            "status": _response_status(response),
            "bytes": len(getattr(response, "content", b"") or b""),
        })
        return response

    async def _business_payload_async(self, response: Any, stage: str) -> Mapping[str, Any]:
        self._check_http(response, stage)
        value = getattr(response, "json", None)
        try:
            value = value() if callable(value) else value
            if inspect.isawaitable(value):
                value = await value
            if isinstance(value, str):
                import json

                value = json.loads(value)
        except Exception as exc:
            raise WebChapterError(
                f"网页 {stage} JSON 解析失败", stage=stage) from exc
        if not isinstance(value, Mapping):
            raise WebChapterError(
                f"网页 {stage} JSON 不是对象", stage=stage)
        code = str(value.get("code", ""))
        if code != "100000":
            raise WebChapterError(
                f"网页 {stage} 业务错误 code={code}", stage=stage,
                code=code or None,
                tip=str(value.get("tip", "") or value.get("error_message", "")),
            )
        return value

    async def fetch_chapter(self, chapter_id: str | int) -> WebChapterResult:
        cid = str(chapter_id).strip()
        chapter_url = self.chapter_url(cid)
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            self._new_client(_rank_net().async_session)
            page_response = await self._request(
                "get", chapter_url,
                headers=self._headers(ajax=False, chapter_url=chapter_url),
            )
            self._check_text_chapter_page(page_response)
            session_response = await self._request(
                "post", f"{self.base_url}{WEB_SESSION_PATH}",
                headers=self._headers(ajax=True, chapter_url=chapter_url),
                data={"chapter_id": cid},
            )
            session_payload = await self._business_payload_async(session_response, "session")
            access_key = self._extract_access_key(session_payload, "session")
            detail_response = await self._request(
                "post", f"{self.base_url}{WEB_DETAIL_PATH}",
                headers=self._headers(ajax=True, chapter_url=chapter_url),
                data={"chapter_id": cid, "chapter_access_key": access_key},
            )
            detail_payload = await self._business_payload_async(detail_response, "detail")
            encrypted, keys = self._chapter_fields(detail_payload)
            if not encrypted or not keys:
                raise WebChapterError(
                    "网页 detail 响应缺少 chapter_content/encryt_keys",
                    stage="detail", code="missing-content")
            try:
                plaintext = decrypt_chapter_payload(encrypted, keys, access_key)
            except WebDecryptError as exc:
                raise WebChapterError(
                    "网页章节解密失败", stage="decrypt") from exc
            return self._finish_result(cid, access_key, plaintext)

    async def get_chapter_content(self, chapter_id: str | int) -> str:
        result = await self.fetch_chapter(chapter_id)
        return result.text

    async def get_chapter(self, chapter_id: str | int) -> str:
        return await self.get_chapter_content(chapter_id)


__all__ = [
    "WEB_BASE_URL",
    "WEB_USER_AGENT",
    "WEB_SESSION_PATH",
    "WEB_DETAIL_PATH",
    "WebAPIError",
    "WebChapterError",
    "WebDecryptError",
    "WebCookieJar",
    "WebChapterResult",
    "WebChapterSession",
    "AsyncWebChapterSession",
    "decrypt_chapter_payload",
    "decrypt_web_chapter",
    "decrypt_chapter",
    "normalize_chapter_html",
    "normalize_chapter_text",
]
