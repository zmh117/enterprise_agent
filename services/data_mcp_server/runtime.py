from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


try:
    from mcp.server.mcpserver.exceptions import ToolError
except ModuleNotFoundError:
    from mcp.server.fastmcp.exceptions import ToolError

from services.data_mcp_server.contracts import (
    SERVER_CODE,
    SERVER_VERSION,
    ColumnDescription,
    DatabaseRowsResult,
    LokiLine,
    LokiSearchResult,
    RedisKeysResult,
    RedisValueResult,
    SchemaDirectoryResult,
    SchemaTable,
    TableDescriptionResult,
)
from services.mcp_common import AuthorizedToolContext
from services.mcp_common.platform_store import PlatformRuntimeStore
from services.mcp_common.provenance import McpProvenanceRecorder
from services.mcp_common.sensitive_data import sanitize_sensitive_data
from services.mcp_common.secret_crypto import PlatformSecretDecryptor


_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,127}$")


@dataclass(frozen=True, slots=True)
class ResourceRuntime:
    code: str
    kind: str
    revision_id: str
    deployment_id: str
    generation_id: str
    manifest: dict[str, Any]
    secrets: dict[str, str]


@dataclass(frozen=True, slots=True)
class ResolvedDataCall:
    authorized: AuthorizedToolContext
    resource: ResourceRuntime
    provider: Any


class DataProvider(Protocol):
    async def health_check(self) -> None: ...

    async def schema_directory(
        self, query: str, limit: int
    ) -> tuple[list[dict[str, Any]], bool]: ...

    async def describe_table(self, table: str) -> list[dict[str, Any]]: ...

    async def sample_rows(
        self,
        table: str,
        columns: list[str],
        filters: dict[str, Any],
        limit: int,
    ) -> tuple[list[str], list[dict[str, Any]], bool]: ...

    async def redis_get(self, key: str) -> tuple[bool, str]: ...

    async def redis_scan_prefix(self, prefix: str, limit: int) -> tuple[list[str], bool]: ...

    async def loki_search(
        self, service: str, keyword: str, minutes: int, limit: int
    ) -> tuple[list[dict[str, Any]], bool]: ...


ProviderFactory = Any


class DataResourceResolver:
    def __init__(
        self,
        store: PlatformRuntimeStore,
        decryptor: PlatformSecretDecryptor,
        *,
        provider_factory: ProviderFactory | None = None,
    ) -> None:
        self.store = store
        self.decryptor = decryptor
        self.provider_factory = provider_factory or build_provider

    def resolve(self, context: AuthorizedToolContext) -> ResolvedDataCall:
        binding = context.binding
        row = self.store.query.execute_one(
            """
            select r.code, r.kind, r.lifecycle_status,
                   rr.id as revision_id, rr.manifest_json, rr.content_hash,
                   rr.revision_status,
                   d.id as deployment_id, d.status as deployment_status,
                   d.current_generation_id,
                   g.id as generation_id, g.status as generation_status,
                   g.resource_revision_id as generation_revision_id,
                   g.secret_versions_hash
              from mcp_resource_deployment d
              join mcp_resource r on r.id = d.resource_id
              join mcp_resource_revision rr on rr.id = d.resource_revision_id
              join mcp_resource_generation g on g.id = d.current_generation_id
             where d.id = ? and rr.id = ?
            """,
            (binding.resource_deployment_id, binding.resource_revision_id),
        )
        if row is None or any(
            (
                str(row["lifecycle_status"]) != "ENABLED",
                str(row["revision_status"]) != "PUBLISHED",
                str(row["deployment_status"]) != "ACTIVE",
                str(row["generation_status"]) != "ACTIVE",
                str(row["generation_revision_id"]) != binding.resource_revision_id,
                str(row["code"]) != binding.resource_code,
            )
        ):
            raise ToolError("Data MCP Resource is unavailable")
        resource = self._materialize(row)
        return ResolvedDataCall(
            authorized=context,
            resource=resource,
            provider=self.provider_factory(resource),
        )

    def load_building_generation(self, generation_id: str) -> ResourceRuntime:
        row = self.store.query.execute_one(
            """
            select r.code, r.kind, r.lifecycle_status,
                   rr.id as revision_id, rr.manifest_json, rr.content_hash,
                   rr.revision_status,
                   d.id as deployment_id, d.status as deployment_status,
                   d.resource_revision_id as deployment_revision_id,
                   g.id as generation_id, g.status as generation_status,
                   g.resource_revision_id as generation_revision_id,
                   g.secret_versions_hash
              from mcp_resource_generation g
              join mcp_resource_deployment d on d.id = g.deployment_id
              join mcp_resource r on r.id = d.resource_id
              join mcp_resource_revision rr on rr.id = g.resource_revision_id
             where g.id = ?
            """,
            (generation_id,),
        )
        if row is None or any(
            (
                str(row["lifecycle_status"]) != "ENABLED",
                str(row["revision_status"]) != "PUBLISHED",
                str(row["deployment_status"]) != "ACTIVE",
                str(row["generation_status"]) != "VERIFYING",
                str(row["deployment_revision_id"]) != str(row["generation_revision_id"]),
            )
        ):
            raise ToolError("Data MCP generation is not buildable")
        return self._materialize(row)

    def _materialize(self, row: dict[str, Any]) -> ResourceRuntime:
        manifest = _object(row["manifest_json"])
        if hashlib.sha256(_canonical_json(manifest).encode()).hexdigest() != str(
            row["content_hash"]
        ):
            raise ToolError("Data MCP Resource revision integrity failed")
        secret_rows = self.store.query.execute(
            """
            select s.id, s.ref, s.status as secret_status,
                   gv.secret_version, v.ciphertext, v.nonce, v.algorithm, v.status
              from mcp_resource_generation_secret_version gv
              join platform_secret s on s.id = gv.secret_id
              join platform_secret_version v
                on v.secret_id = s.id and v.version = gv.secret_version
             where gv.generation_id = ? order by s.id
            """,
            (row["generation_id"],),
        )
        digest = hashlib.sha256(
            _canonical_json(
                {str(item["id"]): int(item["secret_version"]) for item in secret_rows}
            ).encode()
        ).hexdigest()
        if digest != str(row["secret_versions_hash"]):
            raise ToolError("Data MCP Resource Secret generation integrity failed")
        secrets: dict[str, str] = {}
        for secret in secret_rows:
            if str(secret["secret_status"]) != "enabled" or str(secret["status"]) not in {
                "active",
                "superseded",
                "retired",
            }:
                raise ToolError("Data MCP Resource Secret is unavailable")
            secrets[str(secret["ref"])] = self.decryptor.decrypt(
                secret_id=str(secret["id"]),
                version=int(secret["secret_version"]),
                ciphertext=str(secret["ciphertext"]),
                nonce=str(secret["nonce"]),
                algorithm=str(secret["algorithm"]),
            )
        return ResourceRuntime(
            code=str(row["code"]),
            kind=str(row["kind"]),
            revision_id=str(row["revision_id"]),
            deployment_id=str(row["deployment_id"]),
            generation_id=str(row["generation_id"]),
            manifest=manifest,
            secrets=secrets,
        )


class DataToolService:
    def __init__(
        self,
        resolver: DataResourceResolver,
        recorder: McpProvenanceRecorder,
    ) -> None:
        self.resolver = resolver
        self.recorder = recorder

    def prepare(self, context: AuthorizedToolContext) -> ResolvedDataCall:
        return self.resolver.resolve(context)

    async def schema_directory(
        self, context: ResolvedDataCall, *, query: str, limit: int
    ) -> SchemaDirectoryResult:
        self._kind(context, "DATABASE")
        started = time.monotonic()
        try:
            rows, truncated = await context.provider.schema_directory(query, limit)
            result = SchemaDirectoryResult(
                resource_code=context.resource.code,
                resource_revision_id=context.resource.revision_id,
                tables=tuple(SchemaTable.model_validate(item) for item in rows[:limit]),
                truncated=truncated or len(rows) > limit,
            )
            return self._record(
                context, {"query_length": len(query), "limit": limit}, result, started
            )
        except Exception as exc:
            self._record_failure(
                context, {"query_length": len(query), "limit": limit}, exc, started
            )
            raise

    async def describe_table(
        self, context: ResolvedDataCall, *, table: str
    ) -> TableDescriptionResult:
        self._kind(context, "DATABASE")
        self._allowed_table(context, table)
        started = time.monotonic()
        try:
            columns = await context.provider.describe_table(table)
            result = TableDescriptionResult(
                resource_code=context.resource.code,
                resource_revision_id=context.resource.revision_id,
                table=table,
                columns=tuple(ColumnDescription.model_validate(item) for item in columns[:200]),
                truncated=len(columns) > 200,
            )
            return self._record(context, {"table": table}, result, started)
        except Exception as exc:
            self._record_failure(context, {"table": table}, exc, started)
            raise

    async def sample_rows(
        self,
        context: ResolvedDataCall,
        *,
        table: str,
        columns: list[str],
        filters: dict[str, Any],
        limit: int,
    ) -> DatabaseRowsResult:
        self._kind(context, "DATABASE")
        self._allowed_table(context, table)
        maximum = min(100, int(context.resource.manifest["spec"]["max_rows"]))
        bounded_limit = min(limit, maximum)
        started = time.monotonic()
        try:
            result_columns, rows, truncated = await context.provider.sample_rows(
                table, columns, filters, bounded_limit
            )
            result = DatabaseRowsResult(
                resource_code=context.resource.code,
                resource_revision_id=context.resource.revision_id,
                table=table,
                columns=tuple(result_columns),
                rows=tuple(_bounded_row(row) for row in rows[:bounded_limit]),
                truncated=truncated or len(rows) > bounded_limit,
            )
            return self._record(
                context,
                {
                    "table": table,
                    "columns": columns,
                    "filter_fields": sorted(filters),
                    "limit": bounded_limit,
                },
                result,
                started,
            )
        except Exception as exc:
            self._record_failure(context, {"table": table, "limit": bounded_limit}, exc, started)
            raise

    async def redis_get(self, context: ResolvedDataCall, *, key: str) -> RedisValueResult:
        self._kind(context, "REDIS")
        self._allowed_redis_key(context, key)
        started = time.monotonic()
        try:
            found, value = await context.provider.redis_get(key)
            result = RedisValueResult(
                resource_code=context.resource.code,
                resource_revision_id=context.resource.revision_id,
                key=key,
                found=found,
                value=value[:4000],
                truncated=len(value) > 4000,
            )
            return self._record(context, {"key_hash": _sha(key)}, result, started)
        except Exception as exc:
            self._record_failure(context, {"key_hash": _sha(key)}, exc, started)
            raise

    async def redis_scan_prefix(
        self, context: ResolvedDataCall, *, prefix: str, limit: int
    ) -> RedisKeysResult:
        self._kind(context, "REDIS")
        allowed = tuple(str(item) for item in context.resource.manifest["spec"]["key_prefixes"])
        if prefix not in allowed:
            raise ToolError("Redis prefix is outside the published Resource scope")
        bounded = min(limit, int(context.resource.manifest["spec"]["scan_limit"]), 200)
        started = time.monotonic()
        try:
            keys, truncated = await context.provider.redis_scan_prefix(prefix, bounded)
            result = RedisKeysResult(
                resource_code=context.resource.code,
                resource_revision_id=context.resource.revision_id,
                prefix=prefix,
                keys=tuple(keys[:bounded]),
                truncated=truncated or len(keys) > bounded,
            )
            return self._record(
                context, {"prefix_hash": _sha(prefix), "limit": bounded}, result, started
            )
        except Exception as exc:
            self._record_failure(context, {"prefix_hash": _sha(prefix)}, exc, started)
            raise

    async def loki_search(
        self,
        context: ResolvedDataCall,
        *,
        service: str,
        keyword: str,
        minutes: int,
        limit: int,
    ) -> LokiSearchResult:
        self._kind(context, "LOKI")
        spec = context.resource.manifest["spec"]
        bounded_minutes = min(minutes, int(spec["max_minutes"]))
        bounded_limit = min(limit, int(spec["max_lines"]), 500)
        started = time.monotonic()
        try:
            lines, truncated = await context.provider.loki_search(
                service, keyword, bounded_minutes, bounded_limit
            )
            result = LokiSearchResult(
                resource_code=context.resource.code,
                resource_revision_id=context.resource.revision_id,
                lines=tuple(LokiLine.model_validate(line) for line in lines[:bounded_limit]),
                truncated=truncated or len(lines) > bounded_limit,
            )
            return self._record(
                context,
                {
                    "service_hash": _sha(service),
                    "keyword_hash": _sha(keyword),
                    "minutes": bounded_minutes,
                    "limit": bounded_limit,
                },
                result,
                started,
            )
        except Exception as exc:
            self._record_failure(context, {"service_hash": _sha(service)}, exc, started)
            raise

    def _record(self, context, request_summary, result, started):
        sanitized = type(result).model_validate(sanitize_sensitive_data(result.model_dump()))
        self.recorder.record(
            context=context.authorized,
            request_summary=request_summary,
            result_payload=sanitized.model_dump(),
            status="SUCCEEDED",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return sanitized

    def _record_failure(self, context, request_summary, exc, started) -> None:
        self.recorder.record(
            context=context.authorized,
            request_summary=request_summary,
            result_payload={"error_code": "data_provider_error"},
            status="FAILED",
            duration_ms=int((time.monotonic() - started) * 1000),
            error_code="data_provider_error",
        )

    @staticmethod
    def _kind(context: ResolvedDataCall, expected: str) -> None:
        if context.resource.kind != expected:
            raise ToolError("Tool is not valid for the bound Resource kind")

    @staticmethod
    def _allowed_table(context: ResolvedDataCall, table: str) -> None:
        if not _IDENTIFIER.fullmatch(table):
            raise ToolError("Database identifier is invalid")
        allowed = {str(item) for item in context.resource.manifest["spec"]["allowed_tables"]}
        if table not in allowed:
            raise ToolError("Database table is outside the published Resource scope")

    @staticmethod
    def _allowed_redis_key(context: ResolvedDataCall, key: str) -> None:
        if len(key) > 512 or not any(
            key.startswith(str(prefix))
            for prefix in context.resource.manifest["spec"]["key_prefixes"]
        ):
            raise ToolError("Redis key is outside the published Resource scope")


class DatabaseProvider:
    def __init__(self, resource: ResourceRuntime) -> None:
        self.resource = resource
        self.spec = resource.manifest["spec"]

    async def schema_directory(self, query: str, limit: int):
        return await asyncio.to_thread(self._schema_directory, query, limit)

    async def describe_table(self, table: str):
        return await asyncio.to_thread(self._describe_table, table)

    async def sample_rows(self, table, columns, filters, limit):
        return await asyncio.to_thread(self._sample_rows, table, columns, filters, limit)

    async def health_check(self) -> None:
        await asyncio.to_thread(self._health_check)

    def _health_check(self) -> None:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute("select 1")
            cursor.fetchone()
        finally:
            connection.close()

    async def redis_get(self, key):
        raise ToolError("Database Resource cannot execute Redis operations")

    async def redis_scan_prefix(self, prefix, limit):
        raise ToolError("Database Resource cannot execute Redis operations")

    async def loki_search(self, service, keyword, minutes, limit):
        raise ToolError("Database Resource cannot execute Loki operations")

    def _connect(self):
        provider = self.spec["provider"]
        password = self.resource.secrets[self.spec["password_ref"]]
        timeout = int(self.spec["timeout_seconds"])
        if provider == "mysql":
            import pymysql

            return pymysql.connect(
                host=self.spec["host"],
                port=int(self.spec["port"]),
                user=self.spec["username"],
                password=password,
                database=self.spec["database"],
                connect_timeout=timeout,
                read_timeout=timeout,
                write_timeout=timeout,
                autocommit=True,
                cursorclass=pymysql.cursors.DictCursor,
            )
        if provider == "postgresql":
            import psycopg
            from psycopg.rows import dict_row

            return psycopg.connect(
                host=self.spec["host"],
                port=int(self.spec["port"]),
                user=self.spec["username"],
                password=password,
                dbname=self.spec["database"],
                connect_timeout=timeout,
                autocommit=True,
                row_factory=dict_row,
            )
        if provider == "sqlserver":
            import pymssql

            return pymssql.connect(
                server=self.spec["host"],
                port=str(self.spec["port"]),
                user=self.spec["username"],
                password=password,
                database=self.spec["database"],
                login_timeout=timeout,
                timeout=timeout,
                as_dict=True,
            )
        if provider == "oracle":
            import oracledb

            dsn = oracledb.makedsn(
                self.spec["host"],
                int(self.spec["port"]),
                service_name=self.spec.get("database"),
            )
            return oracledb.connect(
                user=self.spec["username"],
                password=password,
                dsn=dsn,
                tcp_connect_timeout=timeout,
            )
        raise ToolError("Database provider is unsupported")

    def _schema_directory(self, query: str, limit: int):
        allowed = [str(item) for item in self.spec["allowed_tables"]]
        needle = query.lower().strip()
        filtered = [item for item in allowed if not needle or needle in item.lower()]
        return [{"name": item, "comment": ""} for item in filtered[:limit]], len(filtered) > limit

    def _describe_table(self, table: str):
        allowed = {str(item) for item in self.spec["allowed_tables"]}
        if table not in allowed or not _IDENTIFIER.fullmatch(table):
            raise ToolError("Database table is outside the published Resource scope")
        provider = self.spec["provider"]
        schema = self.spec.get("schema") or (
            self.spec["database"] if provider == "mysql" else "public"
        )
        connection = self._connect()
        try:
            cursor = connection.cursor()
            if provider == "oracle":
                cursor.execute(
                    "select column_name, data_type, nullable from all_tab_columns where owner = :1 and table_name = :2 order by column_id",
                    (str(schema).upper(), table.upper()),
                )
                return [
                    {"name": row[0], "data_type": row[1], "nullable": row[2] == "Y", "comment": ""}
                    for row in cursor.fetchall()
                ]
            placeholder = "%s"
            sql = (
                "select column_name, data_type, is_nullable from information_schema.columns "
                f"where table_schema = {placeholder} and table_name = {placeholder} order by ordinal_position"
            )
            cursor.execute(sql, (schema, table))
            rows = cursor.fetchall()
            return [
                {
                    "name": str(_value(row, "column_name", 0)),
                    "data_type": str(_value(row, "data_type", 1)),
                    "nullable": str(_value(row, "is_nullable", 2)).upper() in {"YES", "Y"},
                    "comment": "",
                }
                for row in rows
            ]
        finally:
            connection.close()

    def _sample_rows(self, table, columns, filters, limit):
        description = self._describe_table(table)
        available = {item["name"] for item in description}
        selected = columns or [item["name"] for item in description[:20]]
        if not selected or any(
            item not in available or not _IDENTIFIER.fullmatch(item) for item in selected
        ):
            raise ToolError("Database columns are outside the described table")
        if any(key not in available or not _IDENTIFIER.fullmatch(key) for key in filters):
            raise ToolError("Database filter columns are outside the described table")
        provider = self.spec["provider"]
        quote = (
            (lambda value: f'"{value}"')
            if provider in {"postgresql", "oracle"}
            else (lambda value: f"`{value}`" if provider == "mysql" else f"[{value}]")
        )
        params = list(filters.values())
        if provider == "oracle":
            where = " and ".join(f"{quote(key)} = :{index}" for index, key in enumerate(filters, 1))
            sql = f"select {', '.join(map(quote, selected))} from {quote(table)}"
            if where:
                sql += " where " + where
            sql = f"select * from ({sql}) where rownum <= {int(limit) + 1}"
        elif provider == "sqlserver":
            where = " and ".join(f"{quote(key)} = %s" for key in filters)
            sql = (
                f"select top {int(limit) + 1} {', '.join(map(quote, selected))} from {quote(table)}"
            )
            if where:
                sql += " where " + where
        else:
            where = " and ".join(f"{quote(key)} = %s" for key in filters)
            sql = f"select {', '.join(map(quote, selected))} from {quote(table)}"
            if where:
                sql += " where " + where
            sql += f" limit {int(limit) + 1}"
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(sql, tuple(params))
            fetched = cursor.fetchall()
            rows = [
                {column: _value(row, column, index) for index, column in enumerate(selected)}
                for row in fetched[:limit]
            ]
            return selected, rows, len(fetched) > limit
        finally:
            connection.close()


class RedisProvider:
    def __init__(self, resource: ResourceRuntime) -> None:
        self.resource = resource
        self.spec = resource.manifest["spec"]

    def _client(self):
        import redis

        password_ref = self.spec.get("password_ref")
        return redis.Redis(
            host=self.spec["host"],
            port=int(self.spec["port"]),
            db=int(self.spec["database"]),
            username=self.spec.get("username") or None,
            password=self.resource.secrets.get(password_ref) if password_ref else None,
            ssl=bool(self.spec.get("tls")),
            socket_timeout=int(self.spec["timeout_seconds"]),
            socket_connect_timeout=int(self.spec["timeout_seconds"]),
            decode_responses=True,
        )

    async def health_check(self) -> None:
        def call() -> None:
            client = self._client()
            try:
                if client.ping() is not True:
                    raise ToolError("Redis generation verification failed")
            finally:
                client.close()

        await asyncio.to_thread(call)

    async def redis_get(self, key):
        def call():
            client = self._client()
            value = client.get(key)
            return value is not None, str(value or "")

        return await asyncio.to_thread(call)

    async def redis_scan_prefix(self, prefix, limit):
        def call():
            client = self._client()
            keys: list[str] = []
            cursor = 0
            while True:
                cursor, batch = client.scan(
                    cursor=cursor, match=prefix + "*", count=min(limit + 1, 200)
                )
                keys.extend(str(value) for value in batch)
                if len(keys) > limit or cursor == 0:
                    break
            return keys[:limit], len(keys) > limit or cursor != 0

        return await asyncio.to_thread(call)

    async def schema_directory(self, query, limit):
        raise ToolError("Redis Resource cannot inspect SQL schema")

    async def describe_table(self, table):
        raise ToolError("Redis Resource cannot inspect SQL schema")

    async def sample_rows(self, table, columns, filters, limit):
        raise ToolError("Redis Resource cannot query SQL rows")

    async def loki_search(self, service, keyword, minutes, limit):
        raise ToolError("Redis Resource cannot query Loki")


class LokiProvider:
    def __init__(self, resource: ResourceRuntime) -> None:
        self.resource = resource
        self.spec = resource.manifest["spec"]

    async def health_check(self) -> None:
        url = str(self.spec["base_url"]).rstrip("/") + "/ready"
        headers = {"Accept": "text/plain"}
        if self.spec.get("tenant_id"):
            headers["X-Scope-OrgID"] = str(self.spec["tenant_id"])
        if self.spec.get("auth_ref"):
            headers["Authorization"] = "Bearer " + self.resource.secrets[self.spec["auth_ref"]]

        def call() -> None:
            opener = build_opener(ProxyHandler({}), _NoRedirectHandler())
            try:
                with opener.open(
                    Request(url, headers=headers, method="GET"),
                    timeout=int(self.spec["timeout_seconds"]),
                ) as response:
                    if int(getattr(response, "status", 200)) != 200:
                        raise ToolError("Loki generation verification failed")
                    response.read(4096)
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                raise ToolError("Loki generation verification failed") from exc

        await asyncio.to_thread(call)

    async def loki_search(self, service, keyword, minutes, limit):
        labels = dict(self.spec["label_scope"])
        labels["service"] = service
        selector = ",".join(
            f"{key}={json.dumps(str(value))}" for key, value in sorted(labels.items())
        )
        escaped = keyword.replace("\\", "\\\\").replace('"', '\\"')
        query = "{" + selector + "}" + (f' |= "{escaped}"' if escaped else "")
        end = datetime.now(UTC)
        start = end - timedelta(minutes=minutes)
        headers = {"Accept": "application/json"}
        if self.spec.get("tenant_id"):
            headers["X-Scope-OrgID"] = str(self.spec["tenant_id"])
        if self.spec.get("auth_ref"):
            headers["Authorization"] = "Bearer " + self.resource.secrets[self.spec["auth_ref"]]
        url = (
            str(self.spec["base_url"]).rstrip("/")
            + "/loki/api/v1/query_range?"
            + urlencode(
                {
                    "query": query,
                    "start": int(start.timestamp() * 1e9),
                    "end": int(end.timestamp() * 1e9),
                    "limit": limit + 1,
                    "direction": "backward",
                }
            )
        )

        def call() -> tuple[int, bytes]:
            opener = build_opener(ProxyHandler({}), _NoRedirectHandler())
            try:
                with opener.open(
                    Request(url, headers=headers, method="GET"),
                    timeout=int(self.spec["timeout_seconds"]),
                ) as response:
                    return int(getattr(response, "status", 200)), response.read(1024 * 1024 + 1)
            except HTTPError as exc:
                return int(exc.code), exc.read(1024 * 1024 + 1)
            except (URLError, TimeoutError, OSError) as exc:
                raise ToolError("Loki query is temporarily unavailable") from exc

        status, raw = await asyncio.to_thread(call)
        if status != 200 or len(raw) > 1024 * 1024:
            raise ToolError("Loki query failed or exceeded response limits")
        try:
            streams = json.loads(raw.decode())["data"]["result"]
            lines: list[dict[str, Any]] = []
            for stream in streams:
                stream_labels = {str(k): str(v) for k, v in stream.get("stream", {}).items()}
                for timestamp, line in stream.get("values", []):
                    lines.append(
                        {
                            "timestamp": str(timestamp),
                            "labels": stream_labels,
                            "line": str(line)[:4000],
                        }
                    )
            return lines[:limit], len(lines) > limit
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ToolError("Loki returned an invalid bounded response") from exc

    async def schema_directory(self, query, limit):
        raise ToolError("Loki Resource cannot inspect SQL schema")

    async def describe_table(self, table):
        raise ToolError("Loki Resource cannot inspect SQL schema")

    async def sample_rows(self, table, columns, filters, limit):
        raise ToolError("Loki Resource cannot query SQL rows")

    async def redis_get(self, key):
        raise ToolError("Loki Resource cannot query Redis")

    async def redis_scan_prefix(self, prefix, limit):
        raise ToolError("Loki Resource cannot query Redis")


def build_provider(resource: ResourceRuntime) -> DataProvider:
    if resource.kind == "DATABASE":
        return DatabaseProvider(resource)
    if resource.kind == "REDIS":
        return RedisProvider(resource)
    if resource.kind == "LOKI":
        return LokiProvider(resource)
    raise ToolError("Data MCP Resource kind is unsupported")


def build_default_data_service(store: PlatformRuntimeStore) -> DataToolService:
    resolver = DataResourceResolver(
        store,
        PlatformSecretDecryptor.from_file(os.environ.get("APP_CONFIG_MASTER_KEY_FILE", "")),
    )
    return DataToolService(
        resolver,
        McpProvenanceRecorder(store.query, server_code=SERVER_CODE, server_version=SERVER_VERSION),
    )


def _object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _bounded_row(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key)[:128]: _bounded_value(value) for key, value in row.items()}


def _bounded_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:1000]


def _value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        if key in row:
            return row[key]
        normalized_key = key.casefold()
        for candidate, value in row.items():
            if str(candidate).casefold() == normalized_key:
                return value
        return None
    try:
        return row[index]
    except (IndexError, TypeError):
        return None


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
