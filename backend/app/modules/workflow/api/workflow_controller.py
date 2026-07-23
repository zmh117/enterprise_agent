from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.bootstrap import Container
from app.modules.identity.api.dependencies import (
    current_principal,
    optional_legacy_actor,
    require_csrf,
)
from app.shared.exceptions import AppError, NotFound, PermissionDenied


def _container(request: Request) -> Container:
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, Container):
        raise RuntimeError("Application container is not initialized")
    return container


def _actor(request: Request) -> str:
    features = _container(request).settings.feature_configuration
    if features.unified_identity_enabled or features.web_admin_enabled:
        principal = current_principal(request)
        require_csrf(request, principal)
        return principal.user_id
    return optional_legacy_actor(request)


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionDenied):
        return HTTPException(status_code=403, detail=exc.safe_message)
    if isinstance(exc, NotFound):
        return HTTPException(status_code=404, detail=exc.safe_message)
    if isinstance(exc, AppError):
        return HTTPException(status_code=400, detail=exc.safe_message)
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="Internal server error")


def build_workflow_router() -> APIRouter:
    router = APIRouter(prefix="/api/agent/workflows", tags=["agent-workflows"])

    @router.get("")
    def list_templates(
        request: Request,
        project_code: str | None = None,
        include_disabled: bool = Query(default=True),
    ) -> dict[str, Any]:
        service = _container(request).workflow_service
        return {
            "workflows": service.list_templates(
                project_code=project_code,
                include_disabled=include_disabled,
            )
        }

    @router.post("")
    async def upsert_template(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            template = _container(request).workflow_service.upsert_template(
                payload,
                actor_id=_actor(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"workflow": template}

    @router.post("/{code}/enable")
    def enable_template(request: Request, code: str) -> dict[str, Any]:
        return _set_template_status(request, code, "draft")

    @router.post("/{code}/disable")
    def disable_template(request: Request, code: str) -> dict[str, Any]:
        return _set_template_status(request, code, "disabled")

    @router.get("/{code}/nodes")
    def list_nodes(request: Request, code: str) -> dict[str, Any]:
        try:
            nodes = _container(request).workflow_service.list_nodes(code)
        except Exception as exc:
            raise _handle(exc) from exc
        return {"nodes": nodes}

    @router.post("/{code}/nodes")
    async def upsert_node(request: Request, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            node = _container(request).workflow_service.upsert_node(
                code,
                payload,
                actor_id=_actor(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"node": node}

    @router.get("/{code}/edges")
    def list_edges(request: Request, code: str) -> dict[str, Any]:
        try:
            edges = _container(request).workflow_service.list_edges(code)
        except Exception as exc:
            raise _handle(exc) from exc
        return {"edges": edges}

    @router.post("/{code}/edges")
    async def upsert_edge(request: Request, code: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            edge = _container(request).workflow_service.upsert_edge(
                code,
                payload,
                actor_id=_actor(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"edge": edge}

    @router.post("/{code}/publish")
    def publish(request: Request, code: str) -> dict[str, Any]:
        try:
            publication = _container(request).workflow_service.publish(
                code,
                actor_id=_actor(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"publication": publication}

    @router.get("/{code}/publications/latest")
    def latest_publication(request: Request, code: str) -> dict[str, Any]:
        try:
            publication = _container(request).workflow_service.latest_publication(code)
        except Exception as exc:
            raise _handle(exc) from exc
        return {"publication": publication}

    return router


def _set_template_status(request: Request, code: str, status: str) -> dict[str, Any]:
    try:
        template = _container(request).workflow_service.set_template_status(
            code,
            status,
            actor_id=_actor(request),
        )
    except Exception as exc:
        raise _handle(exc) from exc
    return {"workflow": template}
