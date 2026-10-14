"""App 游客身份自动注册。默认协议档案见 `client.config.APP_VERSION`。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import sys
from pathlib import Path
from uuid import uuid4

from . import config, crypto, protocol


def _rank_net():
    bridge = str(Path(__file__).resolve().parents[1])
    if bridge not in sys.path:
        sys.path.insert(0, bridge)
    import net

    return net


class GuestRegistrationError(RuntimeError):
    """游客注册请求失败或返回的数据不完整。"""

    def __init__(self, code: str, tip: str = ""):
        self.code = str(code)
        self.tip = str(tip or "")
        super().__init__(f"游客注册失败 code={self.code}: {self.tip}")


@dataclass(frozen=True, repr=False)
class GuestCredentials:
    """游客凭据；repr 不包含任何字段，避免日志意外泄露。"""

    login_token: str
    account: str
    device_token: str
    reader_id: str = ""


def build_guest_registration_params(
    *,
    app_version: str = config.APP_VERSION,
    uuid_value: str | None = None,
    rand_str: str | None = None,
) -> dict[str, str]:
    """构造与官方 App 首次启动一致的 auto_reg_v2 参数。"""
    params = {
        "app_version": app_version,
        "channel": config.GUEST_REGISTRATION_CHANNEL,
        "device_token": config.DEVICE_TOKEN_PREFIX,
        "gender": "1",
        "oauth_open_id": "",
        "oauth_type": "",
        "oauth_union_id": "",
        "uuid": uuid_value or f"android{uuid4()}",
    }
    params.update(protocol.sign_request(
        config.GUEST_REGISTRATION_ACCOUNT,
        app_version,
        rand_str=rand_str,
    ))
    return params


def _decode_registration_response(text: str,
                                  app_version: str) -> dict:
    raw = str(text or "").strip()
    if not raw:
        raise GuestRegistrationError("empty-response", "响应为空")
    try:
        if raw.startswith("{"):
            return json.loads(raw)
        plaintext = crypto.decrypt_response_for_version(raw, app_version)
        return json.loads(plaintext)
    except GuestRegistrationError:
        raise
    except Exception as exc:
        raise GuestRegistrationError(
            "decode-failed", "响应解密或 JSON 解析失败") from exc


async def register_guest(
    *,
    app_version: str = config.APP_VERSION,
    base_url: str = config.GUEST_REGISTRATION_BASE_URL,
    timeout: float = 30,
    impersonate: str | None = None,
    proxy: str | None = None,
    max_retries: int = 2,
    retry_backoff: float = 0.25,
    uuid_value: str | None = None,
    rand_str: str | None = None,
    session_factory=None,
) -> GuestCredentials:
    """经指定出口创建未绑定游客身份，不在日志中输出凭据。"""
    headers = {
        "User-Agent": (
            "Android com.kuangxiangciweimao.novel "
            f"{app_version}"
        ),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    session_kwargs = {
        "headers": headers,
        "proxy": proxy,
    }
    if impersonate:
        session_kwargs["impersonate"] = impersonate

    params = build_guest_registration_params(
        app_version=app_version,
        uuid_value=uuid_value,
        rand_str=rand_str,
    )
    attempts = max(1, int(max_retries) + 1)
    factory = session_factory or _rank_net().async_session
    async with factory(**session_kwargs) as session:
        response = None
        for attempt in range(attempts):
            try:
                response = await session.post(
                    f"{base_url.rstrip('/')}/signup/auto_reg_v2",
                    data=params,
                    timeout=float(timeout),
                )
                break
            except _rank_net().transport_errors():
                if attempt + 1 >= attempts:
                    raise
                delay = max(0, float(retry_backoff)) * (2 ** attempt)
                if delay:
                    await asyncio.sleep(delay)

    if response is None:
        raise GuestRegistrationError("no-response", "未获得 HTTP 响应")
    if response.status_code != 200:
        raise GuestRegistrationError(
            f"http-{response.status_code}", "HTTP 状态异常")

    payload = _decode_registration_response(response.text, app_version)
    code = str(payload.get("code", ""))
    if code != "100000":
        raise GuestRegistrationError(code, payload.get("tip", ""))

    data = payload.get("data") or {}
    reader_info = data.get("reader_info") or {}
    login_token = str(data.get("login_token", "")).strip()
    account = str(reader_info.get("account", "")).strip()
    if not login_token or not account:
        raise GuestRegistrationError(
            "invalid-response", "响应缺少 login_token 或 account")
    return GuestCredentials(
        login_token=login_token,
        account=account,
        device_token=config.DEVICE_TOKEN_PREFIX,
        reader_id=str(reader_info.get("reader_id", "")).strip(),
    )


def android_id_to_am(android_id: str) -> str:
    """Official SendImeiTask `am` is MD5(Settings.Secure.ANDROID_ID)."""
    return hashlib.md5(str(android_id).encode("utf-8")).hexdigest()


def build_save_reader_oaid_params(
    *,
    reader_id: str,
    am: str,
    channel: str = config.GUEST_REGISTRATION_CHANNEL,
    oaid: str = "",
) -> dict[str, str]:
    """Fields for /signup/save_reader_oaid. Session adds account/token/p."""
    return {
        "reader_id": str(reader_id),
        "channel": channel,
        "oaid": oaid,
        "am": am,
    }


def save_reader_oaid(session, reader_id: str, *, am: str, oaid: str = "",
                     channel: str = config.GUEST_REGISTRATION_CHANNEL):
    """Post-registration follow-up used by official AutoRegTask -> SendImeiTask."""
    return session._call(
        "/signup/save_reader_oaid",
        build_save_reader_oaid_params(
            reader_id=reader_id, am=am, channel=channel, oaid=oaid,
        ),
    )
