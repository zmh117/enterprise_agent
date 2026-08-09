from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request as UrlRequest, build_opener

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.bootstrap import Container
from app.modules.identity.api.dependencies import (
    current_principal,
    require_action,
    require_csrf,
)
from app.shared.exceptions import AppError, NotFound, PermissionDenied


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


def _tool_allowed(request: Request, code: str, *actions: str) -> bool:
    principal = current_principal(request)
    authorization = _container(request).authorization_evaluator
    return any(
        authorization.decide(
            user_id=principal.user_id,
            resource_type="mcp_tool",
            resource_code=code,
            action=action,
        ).allowed
        for action in actions
    )


def _tool_read(request: Request, code: str = "*") -> str:
    principal = current_principal(request)
    if not _tool_allowed(request, code, "read", "manage"):
        if code != "*":
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": "MCP Tool 发布版本不存在"},
            )
        raise HTTPException(status_code=403, detail="你无权执行此操作")
    return principal.user_id


def _tool_write(request: Request, code: str = "*") -> str:
    principal = current_principal(request)
    require_csrf(request, principal)
    if not _tool_allowed(request, code, "manage"):
        if code != "*":
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": "MCP Tool 发布版本不存在"},
            )
        raise HTTPException(status_code=403, detail="你无权执行此操作")
    return principal.user_id


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _CreateToolRequest(_StrictRequest):
    expected_revision: int = Field(ge=0, le=0)
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=128)
    catalog_key: str = Field(min_length=1, max_length=200)
    resource_deployment_id: str = Field(default="", max_length=200)


class _UpdateToolRequest(_StrictRequest):
    expected_revision: int = Field(ge=1)
    catalog_key: str = Field(min_length=1, max_length=200)
    resource_deployment_id: str = Field(default="", max_length=200)


class _ToolRevisionRequest(_StrictRequest):
    expected_revision: int = Field(ge=1)


class _ToolRollbackRequest(_ToolRevisionRequest):
    publication_id: str = Field(min_length=1, max_length=200)


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
        status = (
            409
            if exc.error_code
            in {
                "revision_conflict",
                "mcp_idempotency_conflict",
                "dependency_in_use",
                "mcp_tool_duplicate_publication",
            }
            else 422
        )
        detail: dict[str, Any] = {
            "code": exc.error_code or "mcp_resource_rejected",
            "message": exc.safe_message,
            "field_errors": exc.field_errors,
        }
        current_revision = exc.diagnostics.get("current_revision")
        if isinstance(current_revision, int):
            detail["current_revision"] = current_revision
        return HTTPException(status_code=status, detail=detail)
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
        _tool_read(request)
        service = _container(request).mcp_tool_publication_service
        catalog = service.catalog()
        publications = _container(request).database.execute(
            """
            select server_code, tool_name, tool_schema_hash, status,
                   count(*) as publication_count
              from mcp_tool_publication
             group by server_code, tool_name, tool_schema_hash, status
             order by server_code, tool_name
            """
        )
        return {
            "catalog": catalog,
            "publications": publications,
        }

    @router.get("/tool-publications")
    def tool_publications(request: Request) -> dict[str, Any]:
        current_principal(request)
        values = _container(request).mcp_tool_publication_service.list_tools()
        return {
            "tools": [
                value
                for value in values
                if _tool_allowed(request, str(value["code"]), "read", "manage")
            ],
            "permissions": {"can_create": _tool_allowed(request, "*", "manage")},
        }

    @router.get("/tool-publications/{code}")
    def tool_publication(request: Request, code: str) -> dict[str, Any]:
        _tool_read(request, code)
        try:
            return {"tool": _container(request).mcp_tool_publication_service.get(code)}
        except Exception as exc:
            raise _handle(exc) from exc

    @router.post("/tool-publications")
    def create_tool_publication(
        request: Request,
        payload: _CreateToolRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        actor = _tool_write(request)
        try:
            result = _container(request).mcp_tool_publication_service.create(
                code=payload.code,
                name=payload.name,
                catalog_key=payload.catalog_key,
                resource_deployment_id=payload.resource_deployment_id,
                expected_revision=payload.expected_revision,
                actor_id=actor,
                idempotency_key=idempotency_key,
            )
            return {"tool": result}
        except Exception as exc:
            raise _handle(exc) from exc

    @router.put("/tool-publications/{code}/draft")
    def update_tool_draft(
        request: Request,
        code: str,
        payload: _UpdateToolRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        actor = _tool_write(request, code)
        try:
            result = _container(request).mcp_tool_publication_service.update_draft(
                code,
                expected_revision=payload.expected_revision,
                catalog_key=payload.catalog_key,
                resource_deployment_id=payload.resource_deployment_id,
                actor_id=actor,
                idempotency_key=idempotency_key,
            )
            return {"tool": result}
        except Exception as exc:
            raise _handle(exc) from exc

    @router.post("/tool-publications/{code}/verify")
    def verify_tool_publication(
        request: Request,
        code: str,
        payload: _ToolRevisionRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        actor = _tool_write(request, code)
        try:
            result = _container(request).mcp_tool_publication_service.verify(
                code,
                expected_revision=payload.expected_revision,
                actor_id=actor,
                idempotency_key=idempotency_key,
            )
            return {"verification": result}
        except Exception as exc:
            raise _handle(exc) from exc

    @router.post("/tool-publications/{code}/publish")
    def publish_tool_publication(
        request: Request,
        code: str,
        payload: _ToolRevisionRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        actor = _tool_write(request, code)
        try:
            result = _container(request).mcp_tool_publication_service.publish(
                code,
                expected_revision=payload.expected_revision,
                actor_id=actor,
                idempotency_key=idempotency_key,
            )
            return {"publication": result}
        except Exception as exc:
            raise _handle(exc) from exc

    @router.post("/tool-publications/{code}/disable")
    def disable_tool_publication(
        request: Request,
        code: str,
        payload: _ToolRevisionRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        actor = _tool_write(request, code)
        try:
            result = _container(request).mcp_tool_publication_service.disable(
                code,
                expected_revision=payload.expected_revision,
                actor_id=actor,
                idempotency_key=idempotency_key,
            )
            return {"tool": result}
        except Exception as exc:
            raise _handle(exc) from exc

    @router.post("/tool-publications/{code}/rollback")
    def rollback_tool_publication(
        request: Request,
        code: str,
        payload: _ToolRollbackRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        actor = _tool_write(request, code)
        try:
            result = _container(request).mcp_tool_publication_service.rollback(
                code,
                publication_id=payload.publication_id,
                expected_revision=payload.expected_revision,
                actor_id=actor,
                idempotency_key=idempotency_key,
            )
            return {"publication": result}
        except Exception as exc:
            raise _handle(exc) from exc

    @router.post("/tool-publications/{code}/archive")
    def archive_tool_publication(
        request: Request,
        code: str,
        payload: _ToolRevisionRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        actor = _tool_write(request, code)
        try:
            result = _container(request).mcp_tool_publication_service.archive(
                code,
                expected_revision=payload.expected_revision,
                actor_id=actor,
                idempotency_key=idempotency_key,
            )
            return {"tool": result}
        except Exception as exc:
            raise _handle(exc) from exc

    @router.get("/tool-publications/{publication_id}/usage")
    def tool_publication_usage(request: Request, publication_id: str) -> dict[str, Any]:
        service = _container(request).mcp_tool_publication_service
        try:
            code = service.tool_code_for_publication(publication_id)
        except Exception as exc:
            raise _handle(exc) from exc
        _tool_read(request, code)
        return {"usage": service.usage(publication_id)}

    @router.get("/status")
    def status(request: Request) -> dict[str, Any]:
        _read(request)
        container = _container(request)
        tools_payload = tools(request)
        publication_counts: dict[str, int] = {}
        for item in tools_payload["publications"]:
            if str(item["status"]) != "PUBLISHED":
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
