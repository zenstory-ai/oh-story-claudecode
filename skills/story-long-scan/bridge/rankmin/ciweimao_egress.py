"""Egress for one rank run. Same contract as the collector, no URL logging."""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from urllib.parse import quote

from .contracts import RankFetchError

_LEASE: str | None = None


def build_proxy_url(ip_port: str, username: str, password: str) -> str:
    value = str(ip_port or "").strip()
    host, separator, port_text = value.rpartition(":")
    try:
        address = ipaddress.ip_address(host.strip("[]"))
        port = int(port_text)
    except (TypeError, ValueError) as exc:
        raise RankFetchError("ciweimao proxy failed: endpoint") from exc
    if not separator or not 1 <= port <= 65535 or any(ch.isspace() for ch in value):
        raise RankFetchError("ciweimao proxy failed: endpoint")
    rendered = f"[{address.compressed}]" if address.version == 6 else address.compressed
    endpoint = f"{rendered}:{port}"
    if username and password:
        return f"http://{quote(username, safe='')}:{quote(password, safe='')}@{endpoint}"
    if username or password:
        raise RankFetchError("ciweimao proxy failed: auth")
    return f"http://{endpoint}"


def _read_secret(env_name: str, file_name: str, default_name: str) -> str | None:
    value = os.getenv(env_name, "").strip()
    if value:
        return value
    path_text = os.getenv(file_name, "").strip()
    path = Path(path_text).expanduser() if path_text else Path.home() / ".oh-story" / "ciweimao" / default_name
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        raise RankFetchError(f"ciweimao proxy failed: unreadable {file_name}")
    return text or None


def _kdl_secrets() -> tuple[str, str] | None:
    secret_id = _read_secret("KDL_SECRET_ID", "KDL_SECRET_ID_FILE", "kdl_secret_id")
    secret_key = _read_secret("KDL_SECRET_KEY", "KDL_SECRET_KEY_FILE", "kdl_secret_key")
    if secret_id and secret_key:
        return secret_id, secret_key
    if secret_id or secret_key:
        raise RankFetchError("ciweimao proxy failed: incomplete kdl secret")
    return None


def _acquire_kdl() -> str:
    secrets = _kdl_secrets()
    if secrets is None:
        raise RankFetchError("ciweimao proxy failed: missing kdl secret")
    secret_id, secret_key = secrets
    try:
        import kdl
    except ImportError:
        raise RankFetchError("ciweimao missing module: kdl")
    auth_mode = os.getenv("CIWEIMAO_KDL_AUTH_MODE", "required").strip().lower()
    if auth_mode not in {"auto", "required", "whitelist"}:
        raise RankFetchError("ciweimao proxy failed: auth mode")
    try:
        client = kdl.Client(kdl.Auth(secret_id, secret_key))
    except Exception:
        raise RankFetchError("ciweimao proxy failed: client")
    username = ""
    password = ""
    if auth_mode != "whitelist":
        try:
            payload = client.get_proxy_authorization(plain_text=1, sign_type="hmacsha1")
        except Exception:
            if auth_mode == "required":
                raise RankFetchError("ciweimao proxy failed: authorization")
            payload = {}
        username = str((payload or {}).get("username", "")).strip()
        password = str((payload or {}).get("password", "")).strip()
        if bool(username) != bool(password):
            raise RankFetchError("ciweimao proxy failed: authorization")
        if auth_mode == "required" and not username:
            raise RankFetchError("ciweimao proxy failed: authorization")
    params = {"num": 1, "format": "json", "sign_type": "hmacsha1", "pt": 1}
    area = os.getenv("CIWEIMAO_KDL_AREA", "").strip()
    if area:
        params["area"] = area
    try:
        result = client.get_dps(**params)
    except Exception:
        raise RankFetchError("ciweimao proxy failed: acquire")
    proxies = result if isinstance(result, list) else [result]
    if not proxies or not proxies[0]:
        raise RankFetchError("ciweimao proxy failed: acquire")
    return build_proxy_url(str(proxies[0]), username, password)


def resolve_proxy(*, fresh: bool = False) -> str | None:
    """Return the proxy for this process. ``None`` only when provider is direct."""
    global _LEASE
    if _LEASE and not fresh:
        return _LEASE
    static = os.getenv("CIWEIMAO_PROXY_URL", "").strip()
    provider = os.getenv("CIWEIMAO_PROXY_PROVIDER", "auto").strip().lower()
    if provider in {"direct", "none"}:
        _LEASE = None
        return None
    if provider in {"", "auto"}:
        provider = "static" if static else ("kuaidaili_dps" if _kdl_secrets() else "")
    if provider == "static":
        if not static:
            raise RankFetchError("ciweimao proxy failed: missing CIWEIMAO_PROXY_URL")
        _LEASE = static
        return _LEASE
    if provider in {"kuaidaili", "kuaidaili_dps", "kdl_dps"}:
        _LEASE = _acquire_kdl()
        return _LEASE
    if not provider:
        raise RankFetchError("ciweimao proxy failed: no egress")
    raise RankFetchError("ciweimao proxy failed: provider")
