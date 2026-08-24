from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.shared.database import assert_external_io_allowed


OFFICIAL_PROVIDER_HOST = "api.deepseek.com"
ANTHROPIC_PATH_SUFFIX = "/anthropic"
INTERNAL_GATEWAY_BASE_PATH = "/api"


class ProviderUrlError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def normalize_provider_base_url(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def provider_models_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    path = parsed.path or ""
    if (parsed.hostname or "").lower() == OFFICIAL_PROVIDER_HOST:
        prefix = path[: -len(ANTHROPIC_PATH_SUFFIX)]
        models_path = f"{prefix}/models"
    else:
        models_path = f"{path.rstrip('/')}/v1/models"
    return urlunsplit((parsed.scheme, parsed.netloc, models_path, "", ""))


def validate_provider_base_url(
    value: str,
    *,
    allowed_hosts: frozenset[str] | set[str],
    validate_dns: bool,
    dns_resolver: Callable[..., list[tuple[Any, ...]]] | None = None,
) -> None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ProviderUrlError("模型提供方地址无效") from exc
    host = (parsed.hostname or "").lower()
    if (
        not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
    ):
        raise ProviderUrlError(_scheme_shape_message(parsed.scheme, host, allowed_hosts))
    if host not in {item.strip().lower() for item in allowed_hosts if str(item).strip()}:
        raise ProviderUrlError("仅允许部署白名单中的模型提供方主机")
    path = parsed.path or ""
    path_parts = path.split("/")
    if "//" in path or any(part in {".", ".."} for part in path_parts):
        raise ProviderUrlError("模型提供方地址路径无效")
    official = host == OFFICIAL_PROVIDER_HOST
    if official:
        _validate_official_provider_url(parsed, port, path)
    else:
        _validate_allowlisted_gateway_url(parsed, path)
    if not validate_dns:
        return
    resolver = dns_resolver or socket.getaddrinfo
    _validate_provider_dns(
        host,
        port or _default_port(parsed.scheme),
        allow_private=not official,
        dns_resolver=resolver,
    )


def _scheme_shape_message(scheme: str, host: str, allowed_hosts: frozenset[str] | set[str]) -> str:
    allowlisted = {
        item.strip().lower() for item in allowed_hosts if str(item).strip()
    } - {OFFICIAL_PROVIDER_HOST}
    if host and host in allowlisted:
        return "必须是不包含凭据、查询参数或片段的 HTTP 或 HTTPS 地址"
    if scheme == "http":
        return "必须是不包含凭据、查询参数或片段的 HTTPS 地址"
    return "必须是不包含凭据、查询参数或片段的 HTTPS 地址"


def _validate_official_provider_url(parsed: Any, port: int | None, path: str) -> None:
    if parsed.scheme != "https" or port not in {None, 443}:
        if parsed.scheme != "https":
            raise ProviderUrlError("必须是不包含凭据、查询参数或片段的 HTTPS 地址")
        raise ProviderUrlError("模型提供方地址只允许使用 443 端口")
    if (
        not path.endswith(ANTHROPIC_PATH_SUFFIX)
        or "//" in path
        or any(part in {".", ".."} for part in path.split("/"))
    ):
        raise ProviderUrlError("DeepSeek Base URL 必须以 /anthropic 结尾")


def _validate_allowlisted_gateway_url(parsed: Any, path: str) -> None:
    if parsed.scheme not in {"http", "https"}:
        raise ProviderUrlError("必须是不包含凭据、查询参数或片段的 HTTP 或 HTTPS 地址")
    if path != INTERNAL_GATEWAY_BASE_PATH:
        raise ProviderUrlError("内部模型网关 Base URL 路径必须为 /api")


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _validate_provider_dns(
    host: str,
    port: int,
    *,
    allow_private: bool,
    dns_resolver: Callable[..., list[tuple[Any, ...]]],
) -> None:
    assert_external_io_allowed("model.dns")
    try:
        answers = dns_resolver(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ProviderUrlError("无法解析模型提供方主机") from exc
    addresses = {str(item[4][0]) for item in answers if item and len(item) >= 5}
    if not addresses:
        raise ProviderUrlError("无法解析模型提供方主机")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ProviderUrlError("模型提供方 DNS 结果无效") from exc
        if ip.is_unspecified or ip.is_multicast or ip.is_reserved:
            raise ProviderUrlError("模型提供方主机解析到了不允许的网络")
        if allow_private:
            if ip.is_loopback:
                raise ProviderUrlError("模型提供方主机解析到了不允许的网络")
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            raise ProviderUrlError("模型提供方主机解析到了不允许的网络")
