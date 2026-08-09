from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from services.mcp_common.contracts import schema_hash


ResourceKind = Literal["DATABASE", "REDIS", "LOKI"]


@dataclass(frozen=True, slots=True)
class McpToolCatalogEntry:
    catalog_key: str
    server_code: Literal["ones-mcp", "data-mcp"]
    server_version: str
    tool_name: str
    required_scope: str
    input_schema: dict[str, Any]
    resource_kind: ResourceKind | None = None

    @property
    def tool_schema_hash(self) -> str:
        return schema_hash(self.input_schema)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "tool_schema_hash": self.tool_schema_hash}


def _object(
    properties: dict[str, dict[str, Any]],
    *,
    title: str,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "title": title,
    }
    if required:
        schema["required"] = list(required)
    return schema


_CATALOG = (
    McpToolCatalogEntry(
        catalog_key="ones-mcp/ones_work_item_search",
        server_code="ones-mcp",
        server_version="0.1.0",
        tool_name="ones_work_item_search",
        required_scope="ones.work_items.search",
        input_schema=_object(
            {
                "keyword": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                    "title": "Keyword",
                },
                "issue_type": {
                    "enum": ["demand", "task", "defect"],
                    "type": "string",
                    "title": "Issue Type",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "title": "Limit",
                },
            },
            title="ones_work_item_searchArguments",
            required=("keyword", "issue_type", "limit"),
        ),
    ),
    McpToolCatalogEntry(
        catalog_key="data-mcp/data_schema_directory",
        server_code="data-mcp",
        server_version="0.1.0",
        tool_name="data_schema_directory",
        required_scope="data.schema.read",
        resource_kind="DATABASE",
        input_schema=_object(
            {
                "query": {
                    "type": "string",
                    "maxLength": 200,
                    "default": "",
                    "title": "Query",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 50,
                    "title": "Limit",
                },
            },
            title="data_schema_directoryArguments",
        ),
    ),
    McpToolCatalogEntry(
        catalog_key="data-mcp/data_describe_table",
        server_code="data-mcp",
        server_version="0.1.0",
        tool_name="data_describe_table",
        required_scope="data.schema.read",
        resource_kind="DATABASE",
        input_schema=_object(
            {
                "table": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "title": "Table",
                }
            },
            title="data_describe_tableArguments",
            required=("table",),
        ),
    ),
    McpToolCatalogEntry(
        catalog_key="data-mcp/data_sample_rows",
        server_code="data-mcp",
        server_version="0.1.0",
        tool_name="data_sample_rows",
        required_scope="data.database.sample",
        resource_kind="DATABASE",
        input_schema=_object(
            {
                "table": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "title": "Table",
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 20,
                    "default": [],
                    "title": "Columns",
                },
                "filters": {
                    "type": "object",
                    "additionalProperties": {
                        "anyOf": [
                            {"type": "string"},
                            {"type": "integer"},
                            {"type": "number"},
                            {"type": "boolean"},
                        ]
                    },
                    "maxProperties": 10,
                    "default": {},
                    "title": "Filters",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                    "title": "Limit",
                },
            },
            title="data_sample_rowsArguments",
            required=("table",),
        ),
    ),
    McpToolCatalogEntry(
        catalog_key="data-mcp/redis_get",
        server_code="data-mcp",
        server_version="0.1.0",
        tool_name="redis_get",
        required_scope="data.redis.read",
        resource_kind="REDIS",
        input_schema=_object(
            {
                "key": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 512,
                    "title": "Key",
                }
            },
            title="redis_getArguments",
            required=("key",),
        ),
    ),
    McpToolCatalogEntry(
        catalog_key="data-mcp/redis_scan_prefix",
        server_code="data-mcp",
        server_version="0.1.0",
        tool_name="redis_scan_prefix",
        required_scope="data.redis.read",
        resource_kind="REDIS",
        input_schema=_object(
            {
                "prefix": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 256,
                    "title": "Prefix",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                    "title": "Limit",
                },
            },
            title="redis_scan_prefixArguments",
            required=("prefix",),
        ),
    ),
    McpToolCatalogEntry(
        catalog_key="data-mcp/loki_search",
        server_code="data-mcp",
        server_version="0.1.0",
        tool_name="loki_search",
        required_scope="data.loki.read",
        resource_kind="LOKI",
        input_schema=_object(
            {
                "service_name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "title": "Service Name",
                },
                "keyword": {
                    "type": "string",
                    "maxLength": 200,
                    "default": "",
                    "title": "Keyword",
                },
                "minutes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1440,
                    "default": 15,
                    "title": "Minutes",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 100,
                    "title": "Limit",
                },
            },
            title="loki_searchArguments",
            required=("service_name",),
        ),
    ),
)

MCP_TOOL_CATALOG = {entry.catalog_key: entry for entry in _CATALOG}


def get_catalog_entry(catalog_key: str) -> McpToolCatalogEntry:
    try:
        return MCP_TOOL_CATALOG[catalog_key]
    except KeyError as exc:
        raise ValueError("MCP Tool is not present in the code-owned catalog") from exc


def catalog_entries() -> tuple[McpToolCatalogEntry, ...]:
    return tuple(_CATALOG)
