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
    "get_er_context": {
        "description": "Search compact ER graph context for relevant tables, fields, enums, and relationships.",
        "schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "get_business_flow_context": {
        "description": "Search compact business-flow context for relevant process nodes and flow evidence.",
        "schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "get_schema_directory": {
        "description": (
            "Return the allowed read-only schema directory for a target environment/base/workshop. "
            "Use this before writing SQL. Only query tables and columns listed by this tool."
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
            "Query bounded Loki logs with exact-match label selectors and a small result limit. "
            "Use selector for labels such as cluster, service_name, container, region, or service; "
            "for example {'cluster': 'mes-cluster'}."
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
            "List bounded Loki label names visible for the resolved environment/base/workshop. "
            "Use this when a Loki query returns no logs or the correct service label is unclear."
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
            "List bounded values for an allowed Loki label such as service, service_name, "
            "container, cluster, region, or workshop."
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
            "Probe a bounded Loki selector and keyword to explain empty results. "
            "Returns stream_count, line_count, and safe empty-result hints."
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
            "Run policy-approved read-only SQL against the uniquely resolved MCP Resource. "
            "Provide structured addressing when a Job target includes a base or workshop."
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
        "description": "Read one approved Redis key from the uniquely resolved MCP Resource.",
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
        "description": "Scan approved Redis key prefixes with a bounded limit.",
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
