"""2.9.328+ App 请求签名。"""

import base64
import hashlib
import hmac
import secrets
from urllib.parse import quote

from . import config


def build_signature_source(account: str, app_version: str,
                           rand_str: str) -> str:
    """构造与 Native `CenterDataAPI` 一致的 HMAC 输入串。"""
    encoded_account = quote(str(account), safe="")
    return (
        f"account={encoded_account}&app_version={app_version}"
        f"&rand_str={rand_str}"
        f"&signatures={config.REQUEST_SIGNATURE_KEY}"
        f"{config.REQUEST_SIGNATURE_SUFFIX}"
    )


def sign_request(account: str, app_version: str,
                 rand_str: str = None) -> dict[str, str]:
    """返回请求需要追加的 `rand_str` 与 `p`。"""
    nonce = rand_str or secrets.token_hex(8)
    source = build_signature_source(account, app_version, nonce)
    digest = hmac.new(
        config.REQUEST_SIGNATURE_KEY.encode("utf-8"),
        source.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return {
        "rand_str": nonce,
        "p": base64.b64encode(digest).decode("ascii"),
    }
