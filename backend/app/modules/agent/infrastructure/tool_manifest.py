from __future__ import annotations

from typing import Any

from app.shared.resource_role import RESOURCE_ROLE_PATTERN
from app.shared.loki_contract import loki_label_schema, loki_selector_schema, LOKI_MAX_MINUTES
from app.shared.query_result_contract import DATABASE_MAX_ROWS, QUERY_RESULT_TOOLS

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

_PLACEMENT_PROPERTY: dict[str, Any] = {
    "placement": {
        "type": "string",
        "maxLength": 64,
        "pattern": RESOURCE_ROLE_PATTERN,
        "description": (
            "资源角色（不是用户授权角色），可为云、边、cloud、edge 或其他自定义值。"
            "从资源目录原样使用 placement，精确区分同环境/基地/车间的多个实例；"
            "目标不明确时询问用户，不按资源名称猜测，不选择 AMBIGUOUS 条目。"
        ),
    }
}


TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "list_available_tool_resources": {
        "description": (
            "分页列出当前 Job、当前用户和当前业务应用共同授权的数据库、Redis 与 Loki "
            "资源地址摘要。目标不明确或用户询问可用资源时应先调用本工具。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "resource_kind": {
                    "type": "string",
                    "enum": ["database", "redis", "loki"],
                },
                "query": {
                    "type": "string",
                    "maxLength": 128,
                    "description": "Optional filter over safe resource and target codes.",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                "cursor": {"type": "string", "maxLength": 4096},
            },
            "additionalProperties": False,
        },
    },
    "get_schema_directory": {
        "description": (
            "返回目标环境、基地或车间允许访问的只读数据库结构目录。"
            "编写 SQL 前应先调用本工具，且只能查询本工具列出的表和字段。"
            "若返回 next_cursor，请保持目标和 query 不变，将此短分页标识原样放入 cursor 续页；"
            "不要解码、改写或自行构造标识。直到 has_more=false 才表示表目录已读完，"
            "字段截断仍需单独说明；改用关键词查询不等于完成原目录分页。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional table-name filter; leave empty for the bounded directory.",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                "cursor": {"type": "string", "maxLength": 4096},
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
            "可追加任意合法的非固定标签，例如 app、logtype 或自定义标签。"
            "资源固定条件由后端强制注入，selector 不得包含固定标签；{} 表示仅使用固定范围。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "selector": loki_selector_schema(),
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
            "列出已发布资源固定标签范围内可见的有界 Loki 标签名称，支持合法自定义标签。"
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
            "列出任意合法 Loki 标签在已发布资源固定范围内的有界取值，如 app、logtype 或自定义标签。"
            "枚举固定标签也不会扩大资源范围；无匹配返回空列表，不代表无权限。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "label": loki_label_schema(),
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
            "在资源固定范围内追加任意合法非固定标签的精确条件和关键词，探测无结果原因；"
            "固定标签由后端注入，不得重复提交；{} 表示只使用固定范围。"
            "返回 stream_count、line_count 和安全的空结果提示。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "selector": loki_selector_schema(),
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
                "cursor": {"type": "string", "maxLength": 4096},
                **_ADDRESSING_PROPERTIES,
                **_PLACEMENT_PROPERTY,
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
}

# Keep the published schema hash aligned with the Runtime result-file contract.
for _name in QUERY_RESULT_TOOLS:
    TOOL_DEFINITIONS[_name]["description"] += (
        " 成功查询正文写入当前 Job 只读临时文件；根据 result_file 使用 Read/Grep 按需读取，"
        "Job 结束自动删除。complete=false 时不得声称查全。"
    )
    TOOL_DEFINITIONS[_name]["schema"]["description"] = "job-query-result-file-v1"
TOOL_DEFINITIONS["query_database"]["schema"]["properties"]["limit"]["maximum"] = DATABASE_MAX_ROWS
TOOL_DEFINITIONS["query_database"]["description"] += " 默认 100 行，显式最多 10000 行。"
TOOL_DEFINITIONS["list_available_tool_resources"]["description"] += (
    " effective_limits 为实际有效查询上限；Loki 的分钟/行数取平台与已发布资源较小值。"
)
for _name in ("query_loki", "diagnose_loki_probe", "diagnose_loki_labels", "diagnose_loki_label_values"):
    TOOL_DEFINITIONS[_name]["schema"]["properties"]["minutes"]["maximum"] = LOKI_MAX_MINUTES
    TOOL_DEFINITIONS[_name]["description"] += " 先查看资源目录 effective_limits，不得猜测上限或反复超限试探。"
