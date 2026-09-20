"""管理员知识存储配置合同；模型不能提供地址，配置只包含凭据引用。"""

import ipaddress
import json
import re
from typing import Any
from urllib.parse import urlsplit

from app.modules.knowledge.domain.governance import KnowledgeGovernanceError, strict_object


DEFAULT_QDRANT = "http://knowledge-qdrant:6333"


def _text(value: Any, maximum: int = 128) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or value != value.strip()
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError
    return str(value)


def _host(value: Any) -> str:
    value = _text(value, 253).lower()
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", value):
            raise ValueError from None
        if any(not part or len(part) > 63 for part in value.split(".")):
            raise ValueError
    else:
        if address.is_link_local or address.is_multicast or address.is_unspecified:
            raise ValueError
    return str(value)


def _reference(value: Any, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    value = _text(value, 256)
    if not re.fullmatch(r"secret://platform/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError
    return str(value)


def storage_config(value: Any) -> dict[str, Any] | None:
    """None 保留原发布 hash 与部署连接；显式配置必须完整，不接受 DSN 或密码。"""
    if value is None:
        return None
    try:
        if not isinstance(value, dict) or set(value) != {"postgres", "qdrant"}:
            raise ValueError
        pg, vector = value["postgres"], value["qdrant"]
        if not isinstance(pg, dict):
            raise ValueError
        if pg == {"mode": "platform"}:
            postgres = dict(pg)
        else:
            if set(pg) != {
                "mode",
                "host",
                "port",
                "database",
                "username",
                "password_ref",
                "sslmode",
            }:
                raise ValueError
            if (
                pg["mode"] != "external"
                or type(pg["port"]) is not int
                or not 1 <= pg["port"] <= 65535
            ):
                raise ValueError
            if pg["sslmode"] not in {"disable", "require", "verify-full"}:
                raise ValueError
            postgres = {
                "mode": "external",
                "host": _host(pg["host"]),
                "port": pg["port"],
                "database": _text(pg["database"]),
                "username": _text(pg["username"]),
                "password_ref": _reference(pg["password_ref"]),
                "sslmode": pg["sslmode"],
            }
        if not isinstance(vector, dict) or set(vector) != {"url", "api_key_ref"}:
            raise ValueError
        parsed = urlsplit(_text(vector["url"], 512))
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError
        host = _host(parsed.hostname)
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        authority = f"[{host}]" if ":" in host else host
        if port is not None:
            authority += f":{port}"
        return {
            "postgres": postgres,
            "qdrant": {
                "url": f"{parsed.scheme}://{authority}",
                "api_key_ref": _reference(vector["api_key_ref"], optional=True),
            },
        }
    except (ValueError, TypeError, KeyError):
        raise KnowledgeGovernanceError("knowledge_storage_config_invalid") from None


def stored_config(value: Any) -> dict[str, Any] | None:
    try:
        return storage_config(json.loads(value, object_pairs_hook=strict_object) if value else None)
    except (ValueError, TypeError, RecursionError):
        raise KnowledgeGovernanceError("knowledge_storage_config_invalid") from None
