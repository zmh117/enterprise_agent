"""Code-library checkout management; removed pre-extraction/snapshot/build endpoints."""

from typing import Any
from fastapi import APIRouter, Request

from app.modules.identity.api.dependencies import require_action, current_principal
from app.modules.knowledge.api.controller import actor, invoke, payload, services, container
from app.modules.knowledge.domain.code_answers import utc_time
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_result_authorizer import CodeResultAuthorizer
from app.modules.knowledge.infrastructure.code_result_client import CodeResultClient
from app.modules.agent.infrastructure.runtime_pool_store import database_now


def build_code_operations_router() -> APIRouter:
    router = APIRouter(prefix="/api/platform/knowledge/code", tags=["knowledge"])

    @router.get("/resources/{resource_id}/index-status")
    async def index_status(resource_id: str, request: Request) -> Any:
        require_action(request, resource_type="platform_config", resource_code="*", action="manage")
        return await invoke(
            services(request).code_resources().indexing_status,
            actor_id=current_principal(request).user_id,
            resource_id=resource_id,
        )

    @router.post("/resources/{resource_id}/indexing")
    async def change_indexing(resource_id: str, request: Request) -> Any:
        user = actor(request)
        value = await payload(request, {"paused"})
        return await invoke(
            services(request).code_resources().set_indexing,
            actor_id=user,
            resource_id=resource_id,
            **value,
        )

    @router.post("/resources/{resource_id}/index-tasks/{task_id}/retry")
    async def retry_indexing(resource_id: str, task_id: str, request: Request) -> Any:
        user = actor(request)
        await payload(request, set())
        return await invoke(
            services(request).code_resources().retry_indexing,
            actor_id=user,
            resource_id=resource_id,
            task_id=task_id,
        )

    @router.get("/resources/{resource_id}/checkouts")
    async def checkout_snapshot(resource_id: str, request: Request) -> Any:
        require_action(request, resource_type="platform_config", resource_code="*", action="manage")
        return await invoke(services(request).code_checkouts().snapshot, resource_id=resource_id)

    @router.get("/operations/{operation_id}")
    async def checkout_detail(operation_id: str, request: Request) -> Any:
        require_action(request, resource_type="platform_config", resource_code="*", action="manage")
        user = current_principal(request).user_id

        def read() -> dict[str, Any]:
            jobs = services(request).code_checkouts()
            jobs.admin.require_admin(user)
            operation = jobs.get(operation_id)
            if operation["operation_kind"] != "browse" or operation["state"] != "succeeded":
                return operation
            if utc_time(operation["deadline_at"]) <= database_now(jobs.db):
                return {**operation, "result_expired": True}
            issuer = container(request).service_principal_token_issuer
            if issuer is None:
                raise CodeKnowledgeError("CODE_RESULT_UNAVAILABLE")
            gate = CodeResultAuthorizer(jobs.db, jobs)
            before = gate.authorize(operation_id, operation["claim_version"])
            try:
                result = CodeResultClient(lambda: issuer.issue_code_control().access_token).read(
                    operation_id,
                    operation["claim_version"],
                    result_hash=before["result_hash"],
                    is_directory_preview=True,
                    remaining=(
                        utc_time(operation["deadline_at"]) - database_now(jobs.db)
                    ).total_seconds(),
                )
            except CodeKnowledgeError as exc:
                if exc.code != "CODE_RESULT_EXPIRED":
                    raise
                return {**operation, "result_expired": True}
            jobs.admin.require_admin(user)
            if gate.authorize(operation_id, operation["claim_version"]) != before:
                raise CodeKnowledgeError("CODE_RESULT_DENIED")
            return {**operation, "result": {**operation["result"], **result}}

        return await invoke(read)

    @router.post("/resources/{resource_id}/browse", status_code=202)
    async def browse_svn(resource_id: str, request: Request) -> Any:
        user = actor(request)
        value = await payload(
            request, {"url", "revision", "request_key"}, frozenset({"connection_id"})
        )
        return await invoke(
            services(request).code_checkouts().submit_browse,
            actor_id=user,
            resource_id=resource_id,
            **value,
        )

    router.add_api_route(
        "/resources/{resource_id}/browse-children",
        _browse_svn_children,
        methods=["POST"],
        status_code=202,
    )

    router.add_api_route(
        "/resources/{resource_id}/connections",
        _create_svn_connection,
        methods=["POST"],
        status_code=201,
    )

    @router.post("/resources/{resource_id}/checkouts", status_code=202)
    async def checkout_svn(resource_id: str, request: Request) -> Any:
        user = actor(request)
        value = await payload(request, {"browse_job_id", "paths", "folder", "request_key"})
        return await invoke(
            services(request).code_checkouts().submit_checkout,
            actor_id=user,
            resource_id=resource_id,
            **value,
        )

    return router


async def _create_svn_connection(resource_id: str, request: Request) -> Any:
    from app.modules.knowledge.infrastructure.code_svn_access import CodeSvnAccess

    user = actor(request)
    value = await payload(request, {"url"}, frozenset({"authentication", "username", "password"}))

    def create() -> dict[str, Any]:
        jobs = services(request).code_checkouts()
        jobs.admin.require_admin(user)
        jobs.draft(resource_id)
        return CodeSvnAccess(jobs.db, jobs.registry_file).create(
            resource_id=resource_id,
            actor_id=user,
            platform_config=container(request).platform_config_service,
            **value,
        )

    try:
        return await invoke(create)
    finally:
        value.clear()


async def _browse_svn_children(resource_id: str, request: Request) -> Any:
    user = actor(request)
    value = await payload(request, {"browse_job_id", "path", "request_key"})
    return await invoke(
        services(request).code_checkouts().submit_browse_children,
        actor_id=user,
        resource_id=resource_id,
        **value,
    )
