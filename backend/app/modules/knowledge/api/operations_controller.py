"""知识运维管理 API；不在请求线程执行构建或采集。"""

from typing import Any
from fastapi import APIRouter, Request

from app.modules.identity.api.dependencies import current_principal, require_action
from app.modules.knowledge.api.controller import actor, invoke, payload, services
from app.modules.knowledge.application.operations import KnowledgeOperations


def operations(request: Request) -> KnowledgeOperations:
    return services(request).operations()


def build_knowledge_operations_router() -> APIRouter:
    router = APIRouter(prefix="/api/platform/knowledge/operations", tags=["knowledge"])

    @router.get("")
    def snapshot(request: Request) -> dict[str, Any]:
        require_action(request, resource_type="platform_config", resource_code="*", action="read")
        return operations(request).snapshot()

    @router.post("", status_code=202)
    async def submit(request: Request) -> Any:
        user_id = actor(request)
        value = await payload(
            request, {"kind", "request_key"}, frozenset({"binding_id", "first_day", "last_day"})
        )
        return await invoke(operations(request).submit, actor_id=user_id, **value)

    @router.get("/events")
    async def events(
        request: Request,
        operation_id: str | None = None,
        service: str | None = None,
        after: str | None = None,
    ) -> Any:
        require_action(request, resource_type="platform_config", resource_code="*", action="read")
        return await invoke(
            operations(request).events,
            operation_id=operation_id,
            service=service,
            after=after,
        )

    @router.post("/{operation_id}/retry", status_code=202)
    async def retry(operation_id: str, request: Request) -> Any:
        user_id = actor(request)
        await payload(request, set())
        return await invoke(operations(request).retry, actor_id=user_id, operation_id=operation_id)

    @router.post("/plans")
    async def configure(request: Request) -> Any:
        user_id = actor(request)
        value = await payload(
            request, {"code", "source_code", "configuration", "expected_revision"}
        )
        return await invoke(operations(request).configure, actor_id=user_id, **value)

    @router.get("/plans/{binding_id}/configuration")
    async def configuration(binding_id: str, request: Request) -> Any:
        require_action(request, resource_type="platform_config", resource_code="*", action="manage")
        user_id = current_principal(request).user_id
        return await invoke(
            operations(request).configuration, actor_id=user_id, binding_id=binding_id
        )

    @router.post("/plans/{binding_id}/schedule")
    async def schedule(binding_id: str, request: Request) -> Any:
        user_id = actor(request)
        value = await payload(request, {"enabled", "expected_revision"})
        return await invoke(
            operations(request).schedule, actor_id=user_id, binding_id=binding_id, **value
        )

    return router
