import os
import uuid
from typing import Annotated, Any, Literal, Protocol

from mcp.server import MCPServer
from mcp.server.mcpserver import Context, Resolve
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from services.mcp_common import AuthorizedToolContext, McpTokenVerifier, load_signing_key
from services.mcp_common.http_auth import McpBearerAuthMiddleware
from services.mcp_common.observability import (
    collect_call_metrics,
    safe_observability_failure,
)
from services.mcp_common.platform_store import PlatformRuntimeStore
from services.ones_mcp_server.contracts import (
    SEARCH_SCOPE,
    SERVER_CODE,
    SERVER_VERSION,
    OnesWorkItemSearchResult,
)


class OnesWorkItemSearchService(Protocol):
    async def search(
        self,
        *,
        context: Any,
        keyword: str,
        issue_type: Literal["demand", "task", "defect"],
        limit: int,
    ) -> OnesWorkItemSearchResult: ...


class UnconfiguredOnesWorkItemSearchService:
    async def search(
        self,
        *,
        context: AuthorizedToolContext,
        keyword: str,
        issue_type: Literal["demand", "task", "defect"],
        limit: int,
    ) -> OnesWorkItemSearchResult:
        del context, keyword, issue_type, limit
        raise ToolError("ONES provider is not configured")


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
    search_service: OnesWorkItemSearchService | None = None,
) -> MCPServer:
    service = search_service or UnconfiguredOnesWorkItemSearchService()
    server = MCPServer(
        "Enterprise ONES MCP",
        description="Bounded read-only ONES project-management tools.",
        version=SERVER_VERSION,
    )

    async def resolve_search_context(ctx: Context) -> Any:
        claims = verifier.verify(_bearer(dict(ctx.headers or {})), required_scope=SEARCH_SCOPE)
        correlation_id = str((ctx.headers or {}).get("x-correlation-id") or uuid.uuid4())
        authorized = platform_store.authorize_tool(
            claims=claims,
            tool_name="ones_work_item_search",
            required_scope=SEARCH_SCOPE,
            correlation_id=correlation_id,
        )
        prepare = getattr(service, "prepare", None)
        return prepare(authorized) if callable(prepare) else authorized

    @server.tool(name="ones_work_item_search", structured_output=True)
    async def ones_work_item_search(
        keyword: Annotated[str, Field(min_length=1, max_length=200)],
        issue_type: Literal["demand", "task", "defect"],
        limit: Annotated[int, Field(ge=1, le=50)],
        context: Annotated[Any, Resolve(resolve_search_context)],
    ) -> OnesWorkItemSearchResult:
        """Search the current user's frozen default ONES Team for bounded work items."""
        return await service.search(
            context=context,
            keyword=keyword,
            issue_type=issue_type,
            limit=limit,
        )

    return server


def create_app(
    *,
    verifier: McpTokenVerifier | None = None,
    platform_store: PlatformRuntimeStore | None = None,
    search_service: OnesWorkItemSearchService | None = None,
):
    supplied_platform_store = platform_store is not None
    verifier = verifier or McpTokenVerifier(
        load_signing_key(os.environ.get("MCP_TOKEN_SIGNING_KEY_FILE", "")),
        audience=SERVER_CODE,
    )
    platform_store = platform_store or PlatformRuntimeStore.from_environment(
        server_code=SERVER_CODE
    )
    if search_service is None and not supplied_platform_store:
        from services.ones_mcp_server.runtime import build_default_ones_service

        search_service = build_default_ones_service(platform_store)
    server = create_server(
        verifier=verifier,
        platform_store=platform_store,
        search_service=search_service,
    )
    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        max_request_body_size=256 * 1024,
        host=os.environ.get("ONES_MCP_HOST", "0.0.0.0"),
    )

    async def health(request: Request) -> JSONResponse:
        del request
        try:
            platform_store.query.execute_one("select 1 as ready")
            platform_status = "ready"
            status_code = 200
        except Exception:
            platform_status = "degraded"
            status_code = 503
        return JSONResponse(
            {
                "status": "ok" if platform_status == "ready" else "degraded",
                "server_code": SERVER_CODE,
                "server_version": SERVER_VERSION,
                "platform_status": platform_status,
                "provider_query_executed": False,
            },
            status_code=status_code,
        )

    async def metrics(request: Request) -> JSONResponse:
        del request
        try:
            payload = collect_call_metrics(
                platform_store.query,
                server_code=SERVER_CODE,
                server_version=SERVER_VERSION,
            )
            return JSONResponse(payload)
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
    return McpBearerAuthMiddleware(app, verifier, platform_store)
