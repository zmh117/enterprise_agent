from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request as UrlRequest, build_opener

from fastapi import APIRouter, HTTPException, Request

from app.bootstrap import Container
from app.modules.identity.api.dependencies import (
    current_principal,
    require_action,
    require_csrf,
)
from app.shared.exceptions import AppError, NotFound, PermissionDenied
from services.data_mcp_server.contracts import SCOPES as DATA_SCOPES
from services.ones_mcp_server.contracts import SEARCH_SCOPE


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Any:
        return None


def _health(url: str) -> dict[str, Any]:
    health_url = url.removesuffix("/mcp").rstrip("/") + "/health"
    try:
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        with opener.open(
            UrlRequest(health_url, headers={"Accept": "application/json"}),
            timeout=3,
        ) as response:
            raw = response.read(64 * 1024 + 1)
    except HTTPError as exc:
        raw = exc.read(64 * 1024 + 1)
    except (URLError, TimeoutError, OSError):
        return {"status": "unavailable"}
    try:
        if len(raw) > 64 * 1024:
            raise ValueError("MCP health response is too large")
        payload = json.loads(raw.decode())
        if (
            not isinstance(payload, dict)
            or payload.get("status") not in {"ok", "degraded"}
            or payload.get("server_code") not in {"ones-mcp", "data-mcp"}
        ):
            raise ValueError("MCP health response is invalid")
        return {
            key: payload[key]
            for key in (
                "status",
                "server_code",
                "server_version",
                "generation_status",
                "active_generation_count",
                "building_generation_count",
                "failed_generation_count",
            )
            if key in payload
        }
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return {"status": "unavailable"}


def _container(request: Request) -> Container:
    value = getattr(request.app.state, "container", None)
    if not isinstance(value, Container):
        raise RuntimeError("Application container is not initialized")
    return value


def _read(request: Request) -> str:
    principal = current_principal(request)
    require_action(
        request,
        resource_type="mcp_resource",
        resource_code="*",
        action="read",
    )
    return principal.user_id


def _write(request: Request) -> str:
    principal = current_principal(request)
    require_csrf(request, principal)
    require_action(
        request,
        resource_type="mcp_resource",
        resource_code="*",
        action="manage",
    )
    return principal.user_id


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionDenied):
        return HTTPException(
            status_code=403,
            detail={"code": exc.error_code or "permission_denied", "message": exc.safe_message},
        )
    if isinstance(exc, NotFound):
        return HTTPException(
            status_code=404,
            detail={"code": exc.error_code or "not_found", "message": exc.safe_message},
        )
    if isinstance(exc, AppError):
        status = 409 if exc.error_code in {"revision_conflict", "mcp_idempotency_conflict"} else 422
        return HTTPException(
            status_code=status,
            detail={"code": exc.error_code or "mcp_resource_rejected", "message": exc.safe_message},
        )
    if isinstance(exc, (TypeError, ValueError)):
        return HTTPException(
            status_code=422, detail={"code": "manifest_invalid", "message": "资源声明文件无效"}
        )
    return HTTPException(
        status_code=500, detail={"code": "mcp_resource_failed", "message": "资源操作失败"}
    )


def build_mcp_resource_router() -> APIRouter:
    router = APIRouter(prefix="/api/admin/mcp", tags=["mcp-resource-operations"])

    @router.post("/resources/plan")
    def plan(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        _read(request)
        try:
            return {"plan": _container(request).mcp_resource_service.plan(payload["manifest"])}
        except Exception as exc:
            raise _handle(exc) from exc

    @router.post("/resources/apply")
    def apply_resource(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        actor = _write(request)
        try:
            result = _container(request).mcp_resource_service.apply(
                payload["manifest"],
                actor_id=actor,
                expected_revision=int(payload["expected_revision"]),
                idempotency_key=str(payload["idempotency_key"]),
            )
            return {"resource": result}
        except Exception as exc:
            raise _handle(exc) from exc

    @router.post("/resources/{code}/verify")
    def verify(request: Request, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        actor = _write(request)
        try:
            result = _container(request).mcp_resource_service.verify(
                code,
                actor_id=actor,
                expected_revision=int(payload["expected_revision"]),
            )
            return {"verification": result}
        except Exception as exc:
            raise _handle(exc) from exc

    @router.post("/resources/{code}/publish")
    def publish(request: Request, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        actor = _write(request)
        try:
            result = _container(request).mcp_resource_service.publish(
                code,
                actor_id=actor,
                expected_revision=int(payload["expected_revision"]),
                idempotency_key=str(payload["idempotency_key"]),
            )
            return {"deployment": result}
        except Exception as exc:
            raise _handle(exc) from exc

    @router.post("/resources/{code}/unpublish")
    def unpublish(request: Request, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        actor = _write(request)
        try:
            result = _container(request).mcp_resource_service.unpublish(
                code,
                actor_id=actor,
                expected_revision=int(payload["expected_revision"]),
            )
            return {"deployment": result}
        except Exception as exc:
            raise _handle(exc) from exc

    @router.post("/resources/{code}/draft-from-revision")
    def draft_from_revision(request: Request, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        actor = _write(request)
        try:
            result = _container(request).mcp_resource_service.draft_from_revision(
                code,
                str(payload["resource_revision_id"]),
                actor_id=actor,
                expected_revision=int(payload["expected_revision"]),
                idempotency_key=str(payload["idempotency_key"]),
            )
            return {"resource": result}
        except Exception as exc:
            raise _handle(exc) from exc

    @router.get("/resources")
    def resources(request: Request) -> dict[str, Any]:
        _read(request)
        return {"resources": _container(request).mcp_resource_service.list_status()}

    @router.get("/resources/{code}")
    def resource(request: Request, code: str) -> dict[str, Any]:
        _read(request)
        try:
            return {"resource": _container(request).mcp_resource_service.status(code)}
        except Exception as exc:
            raise _handle(exc) from exc

    @router.get("/tools")
    def tools(request: Request) -> dict[str, Any]:
        _read(request)
        database = _container(request).database
        counts = database.execute(
            """
            select server_code, tool_name, tool_schema_hash, status, count(*) as publication_count
              from mcp_tool_publication
             group by server_code, tool_name, tool_schema_hash, status
             order by server_code, tool_name
            """
        )
        return {
            "servers": [
                {
                    "server_code": "ones-mcp",
                    "version": "0.1.0",
                    "tools": [{"name": "ones_work_item_search", "scope": SEARCH_SCOPE}],
                },
                {
                    "server_code": "data-mcp",
                    "version": "0.1.0",
                    "tools": [
                        {"name": name, "scope": scope}
                        for name, scope in sorted(DATA_SCOPES.items())
                    ],
                },
            ],
            "publications": counts,
        }

    @router.get("/status")
    def status(request: Request) -> dict[str, Any]:
        _read(request)
        container = _container(request)
        tools_payload = tools(request)
        publication_counts: dict[str, int] = {}
        for item in tools_payload["publications"]:
            if str(item["status"]) != "ACTIVE":
                continue
            server_code = str(item["server_code"])
            publication_counts[server_code] = publication_counts.get(server_code, 0) + int(
                item["publication_count"]
            )
        return {
            "servers": [
                {
                    "server_code": "ones-mcp",
                    "health": _health(container.settings.mcp.ones_server_url),
                    "active_publications": publication_counts.get("ones-mcp", 0),
                },
                {
                    "server_code": "data-mcp",
                    "health": _health(container.settings.mcp.data_server_url),
                    "active_publications": publication_counts.get("data-mcp", 0),
                },
            ]
        }

    return router
