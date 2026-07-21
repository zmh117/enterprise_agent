from __future__ import annotations

from typing import Any


TOOL_PROVIDERS: tuple[dict[str, Any], ...] = (
    {
        "code": "database",
        "name": "Database",
        "available": True,
        "dialects": ["postgresql", "mysql", "sqlserver"],
        "config_schema": {
            "required": ["host", "port", "database", "username", "host_allowlist"],
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer"},
                "database": {"type": "string"},
                "username": {"type": "string"},
                "schema": {"type": "string"},
                "host_allowlist": {"type": "array", "items": {"type": "string"}},
            },
        },
        "secret_fields": ["password"],
        "probe": "SELECT 1",
    },
    {
        "code": "redis",
        "name": "Redis",
        "available": True,
        "dialects": [],
        "config_schema": {
            "required": ["host", "port", "host_allowlist"],
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer"},
                "database": {"type": "integer"},
                "username": {"type": "string"},
                "tls": {"type": "boolean"},
                "host_allowlist": {"type": "array", "items": {"type": "string"}},
            },
        },
        "secret_fields": ["password"],
        "probe": "PING",
    },
    {
        "code": "loki",
        "name": "Loki",
        "available": True,
        "dialects": [],
        "config_schema": {
            "required": ["base_url", "host_allowlist"],
            "properties": {
                "base_url": {"type": "string", "format": "uri"},
                "tenant_id": {"type": "string"},
                "host_allowlist": {"type": "array", "items": {"type": "string"}},
            },
        },
        "secret_fields": ["token"],
        "probe": "GET /ready",
    },
)
