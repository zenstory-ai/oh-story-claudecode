from __future__ import annotations

import re
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_META_CHARSET_RE = re.compile(br"<meta[^>]+charset\s*=\s*['\"]?([A-Za-z0-9_\-]+)", re.I)


def _normalize_encoding(encoding: str) -> str:
    normalized = (encoding or "utf-8").lower().replace("_", "-")
    if normalized in {"gb2312", "gbk", "gb-2312"}:
        return "gb18030"
    return normalized or "utf-8"


def _rank_net():
    bridge = str(Path(__file__).resolve().parents[1])
    if bridge not in sys.path:
        sys.path.insert(0, bridge)
    import net

    return net


def _maybe_decompress_body(body: bytes, content_encoding: str = "") -> bytes:
    return _rank_net().gunzip(body, content_encoding)


def _detect_meta_encoding(body: bytes) -> str:
    match = _META_CHARSET_RE.search(body[:4096])
    if not match:
        return ""
    try:
        return match.group(1).decode("ascii", errors="ignore")
    except Exception:
        return ""


def _decode_body(body: bytes, encoding: str = "", content_encoding: str = "") -> str:
    payload = _maybe_decompress_body(body, content_encoding)
    seen: set[str] = set()
    for candidate in (_detect_meta_encoding(payload), encoding, "utf-8"):
        if not candidate:
            continue
        normalized = _normalize_encoding(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            return payload.decode(normalized, errors="strict")
        except LookupError:
            continue
        except UnicodeDecodeError:
            if normalized.startswith("gb"):
                return payload.decode(normalized, errors="replace")
            continue
    fallback = _normalize_encoding(encoding or "utf-8")
    return payload.decode(fallback, errors="replace")


@dataclass(slots=True)
class HttpResponse:
    url: str
    status: int | None
    headers: dict[str, str]
    text: str
    error: str = ""


def _exchange(request: urllib.request.Request, timeout: int, url: str) -> HttpResponse:
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            body = response.read()
            encoding = response.headers.get_content_charset() or ""
            headers_dict = dict(response.headers)
            return HttpResponse(
                url=str(response.url),
                status=response.status,
                headers=headers_dict,
                text=_decode_body(body, encoding, headers_dict.get("Content-Encoding", "")),
            )
    except urllib.error.HTTPError as exc:
        body = exc.read()
        encoding = exc.headers.get_content_charset() or ""
        headers_dict = dict(exc.headers)
        return HttpResponse(
            url=url,
            status=exc.code,
            headers=headers_dict,
            text=_decode_body(body, encoding, headers_dict.get("Content-Encoding", "")),
            error=str(exc),
        )
    except Exception as exc:
        return HttpResponse(url=url, status=None, headers={}, text="", error=repr(exc))


def fetch_text(url: str, timeout: int = 25, headers: dict[str, str] | None = None) -> HttpResponse:
    merged_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if headers:
        merged_headers.update(headers)
    request = urllib.request.Request(url, headers=merged_headers)
    return _exchange(request, timeout, url)


def post_form(
    url: str,
    fields: dict[str, str],
    timeout: int = 25,
    headers: dict[str, str] | None = None,
) -> HttpResponse:
    from urllib.parse import urlencode

    merged_headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    if headers:
        merged_headers.update(headers)
    body = urlencode(fields).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=merged_headers, method="POST")
    return _exchange(request, timeout, url)
