"""Shared libraries for the rank providers.

Qidian and JJWXC stay on urllib. Fanqie and Ciweimao open curl_cffi only
through this module, so the pin and the session constructor live in one place.
"""

from __future__ import annotations

import gzip

CURL_CFFI = "curl_cffi==0.15.0"
PYCRYPTODOME = "pycryptodome==3.17"
KDL = "kdl==0.2.21"


def gunzip(body: bytes, content_encoding: str = "") -> bytes:
    encoding = (content_encoding or "").lower()
    if "gzip" in encoding or body.startswith(b"\x1f\x8b"):
        try:
            return gzip.decompress(body)
        except OSError:
            return body
    return body


def _curl():
    try:
        from curl_cffi import CurlOpt
        from curl_cffi import requests as curl_requests
        from curl_cffi.requests import exceptions as curl_exceptions
    except ModuleNotFoundError as exc:
        missing = ModuleNotFoundError(CURL_CFFI.split("==", 1)[0])
        raise missing from exc
    return curl_requests, curl_exceptions, CurlOpt


def sync_session(**kwargs):
    requests, _, _ = _curl()
    return requests.Session(**kwargs)


def async_session(**kwargs):
    requests, _, _ = _curl()
    return requests.AsyncSession(**kwargs)


def transport_errors() -> tuple[type[BaseException], ...]:
    _, exceptions, _ = _curl()
    return (exceptions.ConnectionError, exceptions.Timeout)


def request_error() -> type[BaseException]:
    _, exceptions, _ = _curl()
    return exceptions.RequestException


def path_as_is():
    _, _, curl_opt = _curl()
    return curl_opt.PATH_AS_IS
