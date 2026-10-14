"""Stdlib HTTP for the JJWXC bookstore rank.

Request headers follow the rank client that already read the boards back.
Cookie, token, and device-id fields are rejected before the request is sent.
Failures name the status only. They do not include the request target.
"""

from __future__ import annotations

from collections.abc import Mapping
import random
import re
import ssl
import sys
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from dataclasses import dataclass
from typing import Callable
from urllib.parse import parse_qsl, urlparse

ANDROID_REFERER = "https://android.jjwxc.net/?v=502"
ANDROID_VERSION_CODE = "502"
BOOK_PAGE_HOST = "www.jjwxc.net"
BOOK_PAGE_PATH = "/onebook.php"
STATS_HOST = "my.jjwxc.net"
STATS_PATH = "/lib/ajax.php"
STATS_ACTION = "getNovelCollectedCount"
STATS_CALLBACK = "jjwxcStats"
WEB_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/126 Safari/537.36"
)
DEFAULT_MIN_DELAY_SECONDS = 2.0
DEFAULT_MAX_DELAY_SECONDS = 4.0
DEFAULT_MAX_RETRIES = 2

FORBIDDEN_ANDROID_REQUEST_FIELDS = frozenset(
    {"appdevice", "cookie", "smdeviceid", "token"}
)

_ANDROID_DEVICE_POOL: tuple[dict[str, str], ...] = (
    {
        "model": "PTP-AN10",
        "android": "Android 9",
        "build": "PQ3A.190605.06171433",
        "chrome": "91.0.4472.114",
    },
    {
        "model": "VOG-AL00",
        "android": "Android 10",
        "build": "QP1A.190711.020",
        "chrome": "92.0.4515.115",
    },
    {
        "model": "M2007J3SC",
        "android": "Android 11",
        "build": "RKQ1.200826.002",
        "chrome": "94.0.4606.71",
    },
    {
        "model": "SM-G9880",
        "android": "Android 11",
        "build": "RP1A.200720.012",
        "chrome": "93.0.4577.82",
    },
    {
        "model": "PEPM00",
        "android": "Android 12",
        "build": "SP1A.210812.016",
        "chrome": "100.0.4896.79",
    },
)


class JjwxcRankError(RuntimeError):
    """A rank request failed. The message has no request target."""


@dataclass(slots=True)
class HttpResponse:
    url: str
    status: int
    headers: dict[str, str]
    text: str


def _assert_no_forbidden_fields(values: Mapping[str, object]) -> None:
    forbidden = sorted(
        str(key)
        for key in values
        if str(key).strip().lower() in FORBIDDEN_ANDROID_REQUEST_FIELDS
    )
    if forbidden:
        raise ValueError(
            "forbidden Android request fields: " + ", ".join(forbidden)
        )


def assert_safe_android_request(url: str, headers: Mapping[str, object]) -> None:
    _assert_no_forbidden_fields(headers)
    _assert_no_forbidden_fields(
        dict(parse_qsl(urlparse(url).query, keep_blank_values=True))
    )


def build_android_headers() -> dict[str, str]:
    device = random.choice(_ANDROID_DEVICE_POOL)
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip",
        "CacheShowed": "false",
        "ReaderId": uuid.uuid4().hex,
        "Referer": ANDROID_REFERER,
        "Source": "android",
        "User-Agent": (
            "Mozilla/5.0 (Linux; {android}; {model} "
            "Build/{build}; wv) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Version/4.0 Chrome/{chrome} "
            "Mobile Safari/537.36/JINJIANG-Android/{version}"
            "({model};Scale/1.5;isHarmonyOS/false)"
        ).format(
            android=device["android"],
            model=device["model"],
            build=device["build"],
            chrome=device["chrome"],
            version=ANDROID_VERSION_CODE,
        ),
        "Version-Code": ANDROID_VERSION_CODE,
        "VersionCode": ANDROID_VERSION_CODE,
        "VersionType": "reading",
    }
    _assert_no_forbidden_fields(headers)
    return headers


class RateLimiter:
    def __init__(
        self,
        *,
        min_delay: float = DEFAULT_MIN_DELAY_SECONDS,
        max_delay: float = DEFAULT_MAX_DELAY_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        uniform: Callable[[float, float], float] = random.uniform,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if min_delay < 0 or max_delay < min_delay:
            raise ValueError("invalid delay range")
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._sleep = sleep
        self._uniform = uniform
        self._clock = clock
        self._last_request_at: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last_request_at is None:
            self._last_request_at = now
            return
        remaining = max(0.0, self._uniform(self.min_delay, self.max_delay) - (now - self._last_request_at))
        if remaining:
            self._sleep(remaining)
        self._last_request_at = self._clock()


def _rank_net():
    bridge = str(Path(__file__).resolve().parents[1])
    if bridge not in sys.path:
        sys.path.insert(0, bridge)
    import net

    return net


def _decompress(body: bytes, content_encoding: str = "") -> bytes:
    return _rank_net().gunzip(body, content_encoding)


def _decode(body: bytes, content_encoding: str = "") -> str:
    return _decompress(body, content_encoding).decode("utf-8", errors="replace")


def _decode_public(body: bytes, content_encoding: str = "") -> str:
    payload = _decompress(body, content_encoding)
    match = re.search(br"charset\s*=\s*['\"]?([A-Za-z0-9_\-]+)", payload[:4096], re.I)
    meta = match.group(1).decode("ascii", errors="ignore") if match else ""
    seen: set[str] = set()
    for candidate in (meta, "utf-8", "gb18030"):
        name = candidate.lower().replace("_", "-")
        if name in {"gb2312", "gbk", "gb-2312"}:
            name = "gb18030"
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            return payload.decode(name)
        except (LookupError, UnicodeDecodeError):
            continue
    return payload.decode("gb18030", errors="replace")


def assert_public_book_request(url: str, headers: Mapping[str, object]) -> None:
    """Reject anything except the two public book-page reads."""
    _assert_no_forbidden_fields(headers)
    parsed = urlparse(url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    _assert_no_forbidden_fields(dict(pairs))
    keys = [key for key, _ in pairs]
    values = dict(pairs)
    novel_id = values.get("novelid", "")
    if parsed.scheme != "https" or not novel_id.isdigit() or len(novel_id) > 12:
        raise ValueError("jjwxc book page url")
    if parsed.hostname == BOOK_PAGE_HOST and parsed.path == BOOK_PAGE_PATH:
        if keys != ["novelid"]:
            raise ValueError("jjwxc book page url")
        return
    if parsed.hostname == STATS_HOST and parsed.path == STATS_PATH:
        if keys != ["action", "novelid", "callback"]:
            raise ValueError("jjwxc book page url")
        if values.get("action") != STATS_ACTION or values.get("callback") != STATS_CALLBACK:
            raise ValueError("jjwxc book page url")
        return
    raise ValueError("jjwxc book page url")


class JjwxcHttpClient:
    def __init__(
        self,
        *,
        timeout: int = 30,
        max_retries: int = DEFAULT_MAX_RETRIES,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.limiter = limiter or RateLimiter()
        self._ssl_context = ssl.create_default_context()

    def fetch(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        if not headers:
            raise JjwxcRankError("jjwxc rank headers missing")
        assert_safe_android_request(url, headers)
        request_headers = {
            "Connection": "close",
            **{str(key): str(value) for key, value in headers.items()},
        }
        last_status = 0
        for attempt in range(self.max_retries + 1):
            self.limiter.wait()
            request = urllib.request.Request(url, headers=request_headers)
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=self.timeout,
                    context=self._ssl_context,
                ) as response:
                    body = response.read()
                    encoding = response.headers.get("Content-Encoding", "")
                    return HttpResponse(
                        url="",
                        status=int(response.status),
                        headers={},
                        text=_decode(body, encoding),
                    )
            except urllib.error.HTTPError as exc:
                last_status = int(exc.code)
                exc.close()
                if last_status in {403, 429} or attempt >= self.max_retries:
                    break
            except (TimeoutError, urllib.error.URLError, OSError):
                last_status = 0
                if attempt >= self.max_retries:
                    break
            if attempt < self.max_retries:
                time.sleep(min(2 ** attempt, 4))
        if last_status:
            raise JjwxcRankError(f"jjwxc rank http status {last_status}")
        raise JjwxcRankError("jjwxc rank request failed")

    def fetch_public(self, url: str) -> HttpResponse:
        headers = {
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Encoding": "gzip",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Connection": "close",
            "Referer": "https://www.jjwxc.net/",
            "User-Agent": WEB_USER_AGENT,
        }
        assert_public_book_request(url, headers)
        requested = urlparse(url)
        last_status = 0
        for attempt in range(self.max_retries + 1):
            self.limiter.wait()
            request = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=self.timeout,
                    context=self._ssl_context,
                ) as response:
                    final = urlparse(response.geturl())
                    if (
                        final.scheme != requested.scheme
                        or final.hostname != requested.hostname
                        or final.path != requested.path
                    ):
                        raise JjwxcRankError("jjwxc book page unavailable")
                    body = response.read()
                    encoding = response.headers.get("Content-Encoding", "")
                    return HttpResponse(
                        url="",
                        status=int(response.status),
                        headers={},
                        text=_decode_public(body, encoding),
                    )
            except JjwxcRankError:
                raise
            except urllib.error.HTTPError as exc:
                last_status = int(exc.code)
                exc.close()
                if last_status in {403, 429} or attempt >= self.max_retries:
                    break
            except (TimeoutError, urllib.error.URLError, OSError):
                last_status = 0
                if attempt >= self.max_retries:
                    break
            if attempt < self.max_retries:
                time.sleep(min(2 ** attempt, 4))
        if last_status:
            raise JjwxcRankError(f"jjwxc book page http status {last_status}")
        raise JjwxcRankError("jjwxc book page request failed")
