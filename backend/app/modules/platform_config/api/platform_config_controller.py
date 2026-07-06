from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.bootstrap import Container
from app.shared.exceptions import AppError, NotFound, PermissionDenied


def _container(request: Request) -> Container:
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, Container):
        raise RuntimeError("Application container is not initialized")
    return container


def _actor(request: Request) -> str:
    return (
        request.headers.get("x-admin-user-id") or request.headers.get("x-agent-user-id") or ""
    ).strip()


def _correlation_id(request: Request) -> str:
    return request.headers.get("x-correlation-id", "").strip()


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


def build_platform_config_router() -> APIRouter:
    router = APIRouter(prefix="/api/platform", tags=["platform-config"])

    @router.get("/environments")
    def list_environments(
        request: Request,
        include_disabled: bool = Query(default=True),
    ) -> dict[str, Any]:
        service = _container(request).platform_config_service
        return {"environments": service.list_environments(include_disabled=include_disabled)}

    @router.post("/environments")
    async def upsert_environment(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            entity = _container(request).platform_config_service.upsert_environment(
                payload,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"environment": entity}

    @router.post("/environments/{code}/enable")
    def enable_environment(request: Request, code: str) -> dict[str, Any]:
        return _set_environment_status(request, code, "enabled")

    @router.post("/environments/{code}/disable")
    def disable_environment(request: Request, code: str) -> dict[str, Any]:
        return _set_environment_status(request, code, "disabled")

    @router.get("/bases")
    def list_bases(
        request: Request,
        environment_code: str | None = None,
        include_disabled: bool = Query(default=True),
    ) -> dict[str, Any]:
        service = _container(request).platform_config_service
        return {
            "bases": service.list_bases(
                environment_code=environment_code,
                include_disabled=include_disabled,
            )
        }

    @router.post("/bases")
    async def upsert_base(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            entity = _container(request).platform_config_service.upsert_base(
                payload,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"base": entity}

    @router.post("/bases/{environment_code}/{code}/enable")
    def enable_base(request: Request, environment_code: str, code: str) -> dict[str, Any]:
        return _set_base_status(request, environment_code, code, "enabled")

    @router.post("/bases/{environment_code}/{code}/disable")
    def disable_base(request: Request, environment_code: str, code: str) -> dict[str, Any]:
        return _set_base_status(request, environment_code, code, "disabled")

    @router.get("/workshops")
    def list_workshops(
        request: Request,
        environment_code: str | None = None,
        base_code: str | None = None,
        include_disabled: bool = Query(default=True),
    ) -> dict[str, Any]:
        service = _container(request).platform_config_service
        return {
            "workshops": service.list_workshops(
                environment_code=environment_code,
                base_code=base_code,
                include_disabled=include_disabled,
            )
        }

    @router.post("/workshops")
    async def upsert_workshop(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            entity = _container(request).platform_config_service.upsert_workshop(
                payload,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"workshop": entity}

    @router.post("/workshops/{environment_code}/{base_code}/{code}/enable")
    def enable_workshop(
        request: Request, environment_code: str, base_code: str, code: str
    ) -> dict[str, Any]:
        return _set_workshop_status(request, environment_code, base_code, code, "enabled")

    @router.post("/workshops/{environment_code}/{base_code}/{code}/disable")
    def disable_workshop(
        request: Request, environment_code: str, base_code: str, code: str
    ) -> dict[str, Any]:
        return _set_workshop_status(request, environment_code, base_code, code, "disabled")

    @router.get("/secret-references")
    def list_secret_references(
        request: Request,
        include_disabled: bool = Query(default=True),
    ) -> dict[str, Any]:
        service = _container(request).platform_config_service
        return {
            "secret_references": service.list_secret_references(include_disabled=include_disabled)
        }

    @router.post("/secret-references")
    async def upsert_secret_reference(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            entity = _container(request).platform_config_service.upsert_secret_reference(
                payload,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"secret_reference": entity}

    @router.get("/resource-bindings")
    def list_resource_bindings(
        request: Request,
        include_disabled: bool = Query(default=True),
    ) -> dict[str, Any]:
        service = _container(request).platform_config_service
        return {
            "resource_bindings": service.list_resource_bindings(include_disabled=include_disabled)
        }

    @router.post("/resource-bindings")
    async def upsert_resource_binding(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            entity = _container(request).platform_config_service.upsert_resource_binding(
                payload,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"resource_binding": entity}

    @router.post("/resource-bindings/{code}/enable")
    def enable_resource_binding(request: Request, code: str) -> dict[str, Any]:
        return _set_resource_binding_status(request, code, "enabled")

    @router.post("/resource-bindings/{code}/disable")
    def disable_resource_binding(request: Request, code: str) -> dict[str, Any]:
        return _set_resource_binding_status(request, code, "disabled")

    @router.get("/access-grants")
    def list_access_grants(
        request: Request,
        include_disabled: bool = Query(default=True),
    ) -> dict[str, Any]:
        service = _container(request).platform_config_service
        return {"access_grants": service.list_access_grants(include_disabled=include_disabled)}

    @router.post("/access-grants")
    async def upsert_access_grant(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            entity = _container(request).platform_config_service.upsert_access_grant(
                payload,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"access_grant": entity}

    @router.post("/access-grants/{grant_id}/enable")
    def enable_access_grant(request: Request, grant_id: str) -> dict[str, Any]:
        return _set_access_grant_status(request, grant_id, "enabled")

    @router.post("/access-grants/{grant_id}/disable")
    def disable_access_grant(request: Request, grant_id: str) -> dict[str, Any]:
        return _set_access_grant_status(request, grant_id, "disabled")

    @router.post("/import/topology-yaml")
    async def import_topology_yaml(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            yaml_text = payload.get("yaml")
            path = payload.get("path")
            if path and not Path(str(path)).is_absolute():
                path = Path(__file__).resolve().parents[4] / str(path)
            result = _container(request).platform_config_service.import_topology_yaml(
                yaml_text=str(yaml_text) if yaml_text is not None else None,
                path=path,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"import": result}

    @router.get("/topology-snapshot")
    def topology_snapshot(request: Request) -> dict[str, Any]:
        return {"snapshot": _container(request).platform_config_service.public_snapshot()}

    return router


def _set_environment_status(request: Request, code: str, status: str) -> dict[str, Any]:
    try:
        entity = _container(request).platform_config_service.set_environment_status(
            code,
            status,
            actor_id=_actor(request),
            correlation_id=_correlation_id(request),
        )
    except Exception as exc:
        raise _handle(exc) from exc
    return {"environment": entity}


def _set_base_status(
    request: Request, environment_code: str, code: str, status: str
) -> dict[str, Any]:
    try:
        entity = _container(request).platform_config_service.set_base_status(
            environment_code=environment_code,
            code=code,
            status=status,
            actor_id=_actor(request),
            correlation_id=_correlation_id(request),
        )
    except Exception as exc:
        raise _handle(exc) from exc
    return {"base": entity}


def _set_workshop_status(
    request: Request, environment_code: str, base_code: str, code: str, status: str
) -> dict[str, Any]:
    try:
        entity = _container(request).platform_config_service.set_workshop_status(
            environment_code=environment_code,
            base_code=base_code,
            code=code,
            status=status,
            actor_id=_actor(request),
            correlation_id=_correlation_id(request),
        )
    except Exception as exc:
        raise _handle(exc) from exc
    return {"workshop": entity}


def _set_resource_binding_status(request: Request, code: str, status: str) -> dict[str, Any]:
    try:
        entity = _container(request).platform_config_service.set_resource_binding_status(
            code,
            status,
            actor_id=_actor(request),
            correlation_id=_correlation_id(request),
        )
    except Exception as exc:
        raise _handle(exc) from exc
    return {"resource_binding": entity}


def _set_access_grant_status(request: Request, grant_id: str, status: str) -> dict[str, Any]:
    try:
        entity = _container(request).platform_config_service.set_access_grant_status(
            grant_id,
            status,
            actor_id=_actor(request),
            correlation_id=_correlation_id(request),
        )
    except Exception as exc:
        raise _handle(exc) from exc
    return {"access_grant": entity}
