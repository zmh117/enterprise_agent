from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.modules.agent.infrastructure.tool_manifest import TOOL_DEFINITIONS


_RESOURCE_KINDS = {
    "get_schema_directory": "database",
    "query_database": "database",
    "query_redis_get": "redis",
    "query_redis_scan": "redis",
    "query_loki": "loki",
    "diagnose_loki_labels": "loki",
    "diagnose_loki_label_values": "loki",
    "diagnose_loki_probe": "loki",
}


@dataclass(frozen=True, slots=True)
class McpToolDefinition:
    identifier: str
    description: str
    input_schema: dict[str, Any]
    schema_hash: str
    resource_kind: str = ""
    read_only: bool = True


def mcp_tool_schema_hash(input_schema: dict[str, Any]) -> str:
    encoded = json.dumps(
        input_schema,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


MCP_TOOL_MANIFEST: dict[str, McpToolDefinition] = {
    identifier: McpToolDefinition(
        identifier=identifier,
        description=str(value["description"]),
        input_schema=dict(value["schema"]),
        schema_hash=mcp_tool_schema_hash(dict(value["schema"])),
        resource_kind=_RESOURCE_KINDS.get(identifier, ""),
    )
    for identifier, value in TOOL_DEFINITIONS.items()
}


def require_mcp_tool(identifier: str) -> McpToolDefinition:
    try:
        return MCP_TOOL_MANIFEST[identifier]
    except KeyError as exc:
        raise KeyError(f"Unknown MCP tool: {identifier}") from exc
