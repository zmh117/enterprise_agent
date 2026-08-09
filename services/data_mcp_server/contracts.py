from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


SERVER_CODE = "data-mcp"
SERVER_VERSION = "0.1.0"

SCOPES = {
    "data_schema_directory": "data.schema.read",
    "data_describe_table": "data.schema.read",
    "data_sample_rows": "data.database.sample",
    "redis_get": "data.redis.read",
    "redis_scan_prefix": "data.redis.read",
    "loki_search": "data.loki.read",
}


class StrictResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_code: str
    resource_revision_id: str
    truncated: bool = False
    untrusted_data: bool = True


class SchemaTable(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=1, max_length=128)
    comment: str = Field(default="", max_length=500)


class SchemaDirectoryResult(StrictResult):
    tables: tuple[SchemaTable, ...] = Field(max_length=100)


class ColumnDescription(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=1, max_length=128)
    data_type: str = Field(min_length=1, max_length=128)
    nullable: bool
    comment: str = Field(default="", max_length=500)


class TableDescriptionResult(StrictResult):
    table: str
    columns: tuple[ColumnDescription, ...] = Field(max_length=200)


class DatabaseRowsResult(StrictResult):
    table: str
    columns: tuple[str, ...] = Field(max_length=100)
    rows: tuple[dict[str, Any], ...] = Field(max_length=100)


class RedisValueResult(StrictResult):
    key: str
    found: bool
    value_type: str = "string"
    value: str = Field(default="", max_length=4000)


class RedisKeysResult(StrictResult):
    prefix: str
    keys: tuple[str, ...] = Field(max_length=200)


class LokiLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    timestamp: str = Field(max_length=64)
    labels: dict[str, str]
    line: str = Field(max_length=4000)


class LokiSearchResult(StrictResult):
    lines: tuple[LokiLine, ...] = Field(max_length=500)
