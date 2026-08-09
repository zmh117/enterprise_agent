import os
import uuid
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context, Resolve
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from services.data_mcp_server.contracts import (
    SCOPES,
    SERVER_CODE,
    SERVER_VERSION,
    DatabaseRowsResult,
    LokiSearchResult,
    RedisKeysResult,
    RedisValueResult,
    SchemaDirectoryResult,
    TableDescriptionResult,
)
from services.data_mcp_server.runtime import DataToolService
from services.mcp_common import McpTokenVerifier, load_signing_key
from services.mcp_common.http_auth import McpBearerAuthMiddleware
from services.mcp_common.lifespan import install_sync_lifespan_hooks
from services.mcp_common.observability import (
    collect_call_metrics,
    collect_data_generation_health,
    generation_health_status_code,
    safe_observability_failure,
)
from services.mcp_common.platform_store import PlatformRuntimeStore


def _bearer(headers: dict[str, str] | None) -> str:
    authorization = str((headers or {}).get("authorization") or "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return ""
    return token


def create_server(
    *,
    verifier: McpTokenVerifier,
    platform_store: PlatformRuntimeStore,
    data_service: DataToolService,
) -> MCPServer:
    server = MCPServer(
        "Enterprise Data MCP",
        description="Bounded read-only database, Redis, and Loki diagnostics.",
        version=SERVER_VERSION,
    )

    def resolver(tool_name: str):
        required_scope = SCOPES[tool_name]

        async def resolve(ctx: Context) -> Any:
            claims = verifier.verify(
                _bearer(dict(ctx.headers or {})), required_scope=required_scope
            )
            correlation_id = str((ctx.headers or {}).get("x-correlation-id") or uuid.uuid4())
            authorized = platform_store.authorize_tool(
                claims=claims,
                tool_name=tool_name,
                required_scope=required_scope,
                correlation_id=correlation_id,
            )
            return data_service.prepare(authorized)

        return resolve

    resolve_schema_context = resolver("data_schema_directory")
    resolve_describe_context = resolver("data_describe_table")
    resolve_sample_context = resolver("data_sample_rows")
    resolve_redis_get_context = resolver("redis_get")
    resolve_redis_scan_context = resolver("redis_scan_prefix")
    resolve_loki_context = resolver("loki_search")

    @server.tool(name="data_schema_directory", structured_output=True)
    async def data_schema_directory(
        context: Annotated[Any, Resolve(resolve_schema_context)],
        query: Annotated[str, Field(max_length=200)] = "",
        limit: Annotated[int, Field(ge=1, le=100)] = 50,
    ) -> SchemaDirectoryResult:
        """List bounded tables for the exact published database Resource bound to this Job."""
        return await data_service.schema_directory(context, query=query, limit=limit)

    @server.tool(name="data_describe_table", structured_output=True)
    async def data_describe_table(
        table: Annotated[str, Field(min_length=1, max_length=128)],
        context: Annotated[Any, Resolve(resolve_describe_context)],
    ) -> TableDescriptionResult:
        """Describe one allowlisted table without exposing connection configuration."""
        return await data_service.describe_table(context, table=table)

    @server.tool(name="data_sample_rows", structured_output=True)
    async def data_sample_rows(
        table: Annotated[str, Field(min_length=1, max_length=128)],
        context: Annotated[Any, Resolve(resolve_sample_context)],
        columns: Annotated[list[str], Field(max_length=20)] = [],
        filters: Annotated[dict[str, str | int | float | bool], Field(max_length=10)] = {},
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> DatabaseRowsResult:
        """Read a bounded allowlisted sample with equality filters; SQL is never accepted."""
        return await data_service.sample_rows(
            context,
            table=table,
            columns=columns,
            filters=filters,
            limit=limit,
        )

    @server.tool(name="redis_get", structured_output=True)
    async def redis_get(
        key: Annotated[str, Field(min_length=1, max_length=512)],
        context: Annotated[Any, Resolve(resolve_redis_get_context)],
    ) -> RedisValueResult:
        """Read one key inside the exact published Redis prefixes."""
        return await data_service.redis_get(context, key=key)

    @server.tool(name="redis_scan_prefix", structured_output=True)
    async def redis_scan_prefix(
        prefix: Annotated[str, Field(min_length=1, max_length=256)],
        context: Annotated[Any, Resolve(resolve_redis_scan_context)],
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
    ) -> RedisKeysResult:
        """Scan one exact published Redis prefix with a hard result limit."""
        return await data_service.redis_scan_prefix(context, prefix=prefix, limit=limit)

    @server.tool(name="loki_search", structured_output=True)
    async def loki_search(
        service_name: Annotated[str, Field(min_length=1, max_length=128)],
        context: Annotated[Any, Resolve(resolve_loki_context)],
        keyword: Annotated[str, Field(max_length=200)] = "",
        minutes: Annotated[int, Field(ge=1, le=1440)] = 15,
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
    ) -> LokiSearchResult:
        """Run server-built bounded LogQL; free LogQL is never accepted."""
        return await data_service.loki_search(
            context,
            service=service_name,
            keyword=keyword,
            minutes=minutes,
            limit=limit,
        )

    return server


def create_app(
    *,
    verifier: McpTokenVerifier | None = None,
    platform_store: PlatformRuntimeStore | None = None,
    data_service: DataToolService | None = None,
    generation_reconciler: Any | None = None,
):
    supplied_platform_store = platform_store is not None
    verifier = verifier or McpTokenVerifier(
        load_signing_key(os.environ.get("MCP_TOKEN_SIGNING_KEY_FILE", "")),
        audience=SERVER_CODE,
    )
    platform_store = platform_store or PlatformRuntimeStore.from_environment(
        server_code=SERVER_CODE
    )
    if data_service is None:
        if supplied_platform_store:
            raise RuntimeError("Custom platform_store requires an explicit data_service")
        from services.data_mcp_server.runtime import build_default_data_service

        data_service = build_default_data_service(platform_store)
        from services.data_mcp_server.generation import DataGenerationReconciler

        generation_reconciler = DataGenerationReconciler(
            platform_store,
            data_service.resolver,
            poll_seconds=float(os.environ.get("DATA_MCP_RECONCILE_SECONDS", "2")),
        )
    server = create_server(
        verifier=verifier,
        platform_store=platform_store,
        data_service=data_service,
    )
    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        max_request_body_size=256 * 1024,
        host=os.environ.get("DATA_MCP_HOST", "0.0.0.0"),
    )

    async def health(request: Request) -> JSONResponse:
        del request
        try:
            snapshot = collect_data_generation_health(platform_store.query, generation_reconciler)
        except Exception:
            return JSONResponse(
                {
                    "status": "degraded",
                    "server_code": SERVER_CODE,
                    "server_version": SERVER_VERSION,
                    "platform_status": "degraded",
                    "generation_status": "unavailable",
                    "error_code": "platform_observability_unavailable",
                    "provider_query_executed": False,
                },
                status_code=503,
            )
        generation_status = str(snapshot["generation_status"])
        return JSONResponse(
            {
                "status": "ok" if generation_status != "degraded" else "degraded",
                "server_code": SERVER_CODE,
                "server_version": SERVER_VERSION,
                "platform_status": "ready",
                "provider_query_executed": False,
                **snapshot,
            },
            status_code=generation_health_status_code(snapshot),
        )

    async def metrics(request: Request) -> JSONResponse:
        del request
        try:
            return JSONResponse(
                collect_call_metrics(
                    platform_store.query,
                    server_code=SERVER_CODE,
                    server_version=SERVER_VERSION,
                )
            )
        except Exception:
            return JSONResponse(
                safe_observability_failure(
                    server_code=SERVER_CODE,
                    server_version=SERVER_VERSION,
                ),
                status_code=503,
            )

    app.routes.insert(0, Route("/health", health, methods=["GET"]))
    app.routes.insert(1, Route("/metrics", metrics, methods=["GET"]))
    if generation_reconciler is not None:
        install_sync_lifespan_hooks(
            app,
            start=generation_reconciler.start,
            close=generation_reconciler.close,
        )
    return McpBearerAuthMiddleware(app, verifier, platform_store)
