from __future__ import annotations

from typing import Any

# compatibility with the flat datasource contract; required by the topology-aware platform.
_ADDRESSING_PROPERTIES: dict[str, Any] = {
    "environment": {
        "type": "string",
        "description": "Environment code, e.g. 'sanjiu' or 'mmk'.",
    },
    "base": {
        "type": "string",
        "description": "Base business code, e.g. 'guanlan' (观澜基地).",
    },
    "workshop": {
        "type": "string",
        "description": "Workshop code within a partitioned base, e.g. 'GL001'.",
    },
}
_LOKI_SELECTOR_PROPERTIES: dict[str, Any] = {
    "cluster": {"type": "string"},
    "container": {"type": "string"},
    "region": {"type": "string"},
    "service": {"type": "string"},
    "service_name": {"type": "string"},
    "workshop": {"type": "string"},
}

_PLACEMENT_PROPERTY: dict[str, Any] = {
    "placement": {
        "type": "string",
        "enum": ["cloud", "edge"],
        "description": (
            "Required when the Job exposes both cloud and edge resources; "
            "omit it when the Job has only one or no placement."
        ),
    }
}


TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "get_schema_directory": {
        "description": (
            "返回目标环境、基地或车间允许访问的只读数据库结构目录。"
            "编写 SQL 前应先调用本工具，且只能查询本工具列出的表和字段。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional table-name filter; leave empty for the bounded directory.",
                },
                "limit": {"type": "integer", "minimum": 1},
                **_ADDRESSING_PROPERTIES,
                **_PLACEMENT_PROPERTY,
            },
            "required": ["environment"],
            "additionalProperties": False,
        },
    },
    "query_loki": {
        "description": (
            "使用精确匹配的标签选择器和有界结果数量查询 Loki 日志。"
            "selector 可使用 cluster、service_name、container、region 或 service 等标签，"
            "例如 {'cluster': 'mes-cluster'}。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "object",
                    "properties": _LOKI_SELECTOR_PROPERTIES,
                    "additionalProperties": False,
                    "minProperties": 1,
                },
                "service": {
                    "type": "string",
                    "description": "Backward-compatible shortcut for selector.service.",
                },
                "query": {"type": "string"},
                "minutes": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1},
                **_ADDRESSING_PROPERTIES,
            },
            "required": ["selector"],
            "additionalProperties": False,
        },
    },
    "diagnose_loki_labels": {
        "description": (
            "列出已解析环境、基地或车间范围内可见的有界 Loki 标签名称。"
            "当 Loki 查询无结果或服务标签不明确时使用。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "minutes": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1},
                **_ADDRESSING_PROPERTIES,
            },
            "required": ["environment", "base"],
            "additionalProperties": False,
        },
    },
    "diagnose_loki_label_values": {
        "description": (
            "列出允许的 Loki 标签的有界取值，例如 service、service_name、"
            "container、cluster、region 或 workshop。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "enum": [
                        "cluster",
                        "container",
                        "region",
                        "service",
                        "service_name",
                        "workshop",
                    ],
                },
                "minutes": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1},
                **_ADDRESSING_PROPERTIES,
            },
            "required": ["environment", "base", "label"],
            "additionalProperties": False,
        },
    },
    "diagnose_loki_probe": {
        "description": (
            "使用有界的 Loki 标签选择器和关键词探测无结果原因；"
            "返回 stream_count、line_count 和安全的空结果提示。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "object",
                    "properties": _LOKI_SELECTOR_PROPERTIES,
                    "additionalProperties": False,
                    "minProperties": 1,
                },
                "query": {"type": "string"},
                "minutes": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1},
                **_ADDRESSING_PROPERTIES,
            },
            "required": ["environment", "base", "selector"],
            "additionalProperties": False,
        },
    },
    "query_database": {
        "description": (
            "对唯一解析的 MCP Resource 执行策略允许的只读 SQL。"
            "当 Job 目标包含基地或车间时，应提供结构化定位信息。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "datasource": {"type": "string"},
                "sql": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1},
                **_ADDRESSING_PROPERTIES,
                **_PLACEMENT_PROPERTY,
            },
            "required": ["sql"],
            "additionalProperties": False,
        },
    },
    "query_redis_get": {
        "description": "从唯一解析的 MCP Resource 读取一个策略允许的 Redis Key。",
        "schema": {
            "type": "object",
            "properties": {
                "datasource": {"type": "string"},
                "key": {"type": "string"},
                **_ADDRESSING_PROPERTIES,
                **_PLACEMENT_PROPERTY,
            },
            "required": ["key"],
            "additionalProperties": False,
        },
    },
    "query_redis_scan": {
        "description": "按策略允许的 Redis Key 前缀执行有界扫描。",
        "schema": {
            "type": "object",
            "properties": {
                "datasource": {"type": "string"},
                "pattern": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1},
                **_ADDRESSING_PROPERTIES,
                **_PLACEMENT_PROPERTY,
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
}
