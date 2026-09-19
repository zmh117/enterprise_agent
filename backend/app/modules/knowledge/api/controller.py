"""知识 HTTP 入口：参数、身份与响应；服务由启动入口装配。"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from app.bootstrap import Container
from app.modules.identity.api.dependencies import current_principal, require_action, require_csrf
from app.modules.knowledge.domain.governance import strict_object
from app.shared.exceptions import AppError, PermissionDenied

if TYPE_CHECKING:
    from app.modules.knowledge.infrastructure.composition import KnowledgeServices


def container(request: Request) -> Container:
    runtime = getattr(request.app.state, "container", None)
    if not isinstance(runtime, Container):
        raise HTTPException(503, detail="知识管理服务暂不可用")
    return runtime


def services(request: Request) -> KnowledgeServices:
    value = container(request).knowledge_services
    if value is None:
        raise HTTPException(503, detail="知识管理服务暂不可用")
    return value


def actor(request: Request) -> str:
    principal = current_principal(request)
    require_csrf(request, principal)
    require_action(request, resource_type="platform_config", resource_code="*", action="manage")
    return principal.user_id


async def payload(request: Request, fields: set[str]) -> dict[str, Any]:
    raw = bytearray()
    async for part in request.stream():
        raw.extend(part)
        if len(raw) > 8192:
            raise HTTPException(
                413, detail={"error_code": "knowledge_input_invalid", "message": "知识配置请求过大"}
            )
    try:
        value = json.loads(raw, object_pairs_hook=strict_object)
        if not isinstance(value, dict) or set(value) != fields:
            raise ValueError("fields")
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(
            400, detail={"error_code": "knowledge_input_invalid", "message": "知识配置参数无效"}
        ) from None


async def invoke(operation: Any, **arguments: Any) -> Any:
    try:
        return await run_in_threadpool(operation, **arguments)
    except AppError as exc:
        raise HTTPException(
            403 if isinstance(exc, PermissionDenied) else 400,
            detail={
                "error_code": exc.error_code or "knowledge_access_denied",
                "message": exc.safe_message,
            },
        ) from None
    except (ValueError, TypeError):
        raise HTTPException(
            400, detail={"error_code": "knowledge_input_invalid", "message": "知识配置参数无效"}
        ) from None


def build_knowledge_router() -> APIRouter:
    router = APIRouter(prefix="/api/platform/knowledge", tags=["knowledge"])

    @router.get("/sources")
    def sources(request: Request) -> dict[str, Any]:
        require_action(request, resource_type="platform_config", resource_code="*", action="read")
        return services(request).sources().catalog()

    @router.post("/source-bindings")
    async def create_binding(request: Request) -> Any:
        user_id = actor(request)
        value = await payload(
            request,
            {
                "source_id",
                "instance_code",
                "team_id",
                "expected_revision",
                "batch_attested",
                "attestation_hash",
            },
        )
        return await invoke(services(request).sources().create, actor_id=user_id, **value)

    @router.post("/source-bindings/{binding_id}/verify")
    async def verify_binding(binding_id: str, request: Request) -> Any:
        user_id = actor(request)
        value = await payload(request, {"job_id"})
        return await invoke(
            services(request).sources().verify,
            actor_id=user_id,
            binding_id=binding_id,
            **value,
        )

    @router.post("/source-bindings/{binding_id}/revoke")
    async def revoke_binding(binding_id: str, request: Request) -> Any:
        user_id = actor(request)
        await payload(request, set())
        await invoke(services(request).sources().revoke, actor_id=user_id, binding_id=binding_id)
        return {"revoked": True}

    @router.get("/catalog")
    def catalog(request: Request) -> dict[str, Any]:
        require_action(request, resource_type="platform_config", resource_code="*", action="read")
        return services(request).resources().catalog()

    @router.get("/resources")
    def resources(request: Request) -> dict[str, Any]:
        require_action(request, resource_type="platform_config", resource_code="*", action="read")
        return services(request).resources().list_resources()

    @router.post("/resources")
    async def create_resource(request: Request) -> Any:
        user_id = actor(request)
        value = await payload(request, {"knowledge_base_id", "code", "name"})
        return await invoke(services(request).resources().create, actor_id=user_id, **value)

    @router.put("/resources/{resource_id}/draft")
    async def draft_resource(resource_id: str, request: Request) -> Any:
        user_id = actor(request)
        value = await payload(request, {"expected_revision", "index_id"})
        return await invoke(
            services(request).resources().save_draft,
            actor_id=user_id,
            resource_id=resource_id,
            **value,
        )

    @router.post("/resources/{resource_id}/verify")
    async def verify_resource_route(resource_id: str, request: Request) -> Any:
        user_id = actor(request)
        value = await payload(request, {"expected_revision"})
        return await invoke(
            services(request).verify_resource,
            actor_id=user_id,
            resource_id=resource_id,
            **value,
        )

    @router.post("/resources/{resource_id}/publish")
    async def publish_resource(resource_id: str, request: Request) -> Any:
        user_id = actor(request)
        value = await payload(request, {"expected_revision"})
        return await invoke(
            services(request).resources().publish,
            actor_id=user_id,
            resource_id=resource_id,
            **value,
        )

    @router.post("/resources/{resource_id}/status")
    async def status_resource(resource_id: str, request: Request) -> Any:
        user_id = actor(request)
        value = await payload(request, {"expected_revision", "status"})
        return await invoke(
            services(request).resources().set_status,
            actor_id=user_id,
            resource_id=resource_id,
            **value,
        )

    return router
