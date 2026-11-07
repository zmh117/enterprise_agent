"""Code-knowledge management: registered IDs only, existing admin and CSRF boundaries."""

from typing import Any
from fastapi import APIRouter, Request

from app.modules.identity.api.dependencies import require_action
from app.modules.knowledge.api.controller import actor, invoke, payload, services


def build_code_operations_router() -> APIRouter:
    router = APIRouter(prefix="/api/platform/knowledge/code", tags=["knowledge"])

    @router.get("/checkouts")
    async def checkout_snapshot(request: Request) -> Any:
        require_action(request, resource_type="platform_config", resource_code="*", action="manage")
        return await invoke(services(request).code_checkouts().snapshot)

    @router.get("/checkouts/{job_id}")
    async def checkout_detail(job_id: str, request: Request) -> Any:
        require_action(request, resource_type="platform_config", resource_code="*", action="manage")
        return await invoke(services(request).code_checkouts().get, job_id=job_id)

    @router.post("/checkouts/browse", status_code=202)
    async def browse_svn(request: Request) -> Any:
        user = actor(request)
        value = await payload(request, {"url", "revision", "request_key"})
        return await invoke(
            services(request).code_checkouts().submit_browse, actor_id=user, **value
        )

    @router.post("/checkouts", status_code=202)
    async def checkout_svn(request: Request) -> Any:
        user = actor(request)
        value = await payload(request, {"browse_job_id", "paths", "folder", "request_key"})
        return await invoke(
            services(request).code_checkouts().submit_checkout, actor_id=user, **value
        )

    @router.post("/sources/{source_id}/plan")
    async def plan(source_id: str, request: Request) -> Any:
        user = actor(request)
        value = await payload(
            request,
            {
                "expected_plan_revision",
                "application_publication_id",
                "service_account_id",
                "schedule_enabled",
                "demand_enabled",
                "local_time",
                "timezone",
            },
        )
        return await invoke(
            services(request).code_operations().configure_plan,
            actor_id=user,
            source_id=source_id,
            **value,
        )

    @router.post("/sources/{source_id}/versions", status_code=202)
    async def version(source_id: str, request: Request) -> Any:
        user = actor(request)
        value = await payload(request, {"revision"})
        return await invoke(
            services(request).code_operations().request_version,
            actor_id=user,
            source_id=source_id,
            **value,
        )

    @router.post("/sources/{source_id}/sites")
    async def site(source_id: str, request: Request) -> Any:
        user = actor(request)
        value = await payload(request, {"site_id", "snapshot_id", "expected_plan_revision"})
        return await invoke(
            services(request).code_operations().bind_site,
            actor_id=user,
            source_id=source_id,
            **value,
        )

    @router.post("/sources/{source_id}/retry", status_code=202)
    async def retry_source(source_id: str, request: Request) -> Any:
        user = actor(request)
        await payload(request, set())
        return await invoke(
            services(request).code_operations().retry_collection, actor_id=user, source_id=source_id
        )

    @router.get("")
    def snapshot(request: Request) -> dict[str, Any]:
        require_action(request, resource_type="platform_config", resource_code="*", action="read")
        return services(request).code_operations().snapshot()

    @router.get("/builds/{build_id}")
    async def detail(build_id: str, request: Request, after: str = "") -> Any:
        require_action(request, resource_type="platform_config", resource_code="*", action="manage")
        return await invoke(
            services(request).code_operations().details, build_id=build_id, after=after
        )

    @router.post("/builds", status_code=202)
    async def start(request: Request) -> Any:
        user = actor(request)
        value = await payload(
            request,
            {"source_id", "source_snapshot_id", "application_publication_id", "service_account_id"},
        )
        return await invoke(services(request).code_operations().start, actor_id=user, **value)

    @router.post("/builds/{build_id}/review")
    async def review(build_id: str, request: Request) -> Any:
        user = actor(request)
        value = await payload(
            request, {"review_reference", "processing_hash", "candidate_digest", "checked_unit_ids"}
        )
        return await invoke(
            services(request).code_operations().review, actor_id=user, build_id=build_id, **value
        )

    @router.post("/builds/{build_id}/retry", status_code=202)
    async def retry(build_id: str, request: Request) -> Any:
        user = actor(request)
        await payload(request, set())
        return await invoke(
            services(request).code_operations().retry, actor_id=user, build_id=build_id
        )

    @router.post("/sources/{source_id}/rollback")
    async def rollback(source_id: str, request: Request) -> Any:
        user = actor(request)
        value = await payload(request, {"snapshot_id", "expected_current"})
        return await invoke(
            services(request).code_operations().rollback,
            actor_id=user,
            source_id=source_id,
            **value,
        )

    return router
