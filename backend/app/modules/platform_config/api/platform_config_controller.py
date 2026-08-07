from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.bootstrap import Container
from app.modules.identity.api.dependencies import (
    current_principal,
    optional_legacy_actor,
    require_action,
    require_csrf,
)
from app.shared.exceptions import AppError, NotFound, PermissionDenied


def _container(request: Request) -> Container:
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, Container):
        raise RuntimeError("Application container is not initialized")
    return container


def _actor(request: Request) -> str:
    c = _container(request)
    if (
        c.settings.feature_configuration.unified_identity_enabled
        or c.settings.feature_configuration.web_admin_enabled
    ):
        principal = current_principal(request)
        require_csrf(request, principal)
        return principal.user_id
    return optional_legacy_actor(request)


def _require_management_read(request: Request, *, resource_type: str) -> None:
    c = _container(request)
    if (
        c.settings.feature_configuration.unified_identity_enabled
        or c.settings.feature_configuration.web_admin_enabled
    ):
        require_action(
            request,
            resource_type=resource_type,
            resource_code="*",
            action="read",
        )


def _require_builtin_tool_read(request: Request) -> None:
    c = _container(request)
    if (
        c.settings.feature_configuration.unified_identity_enabled
        or c.settings.feature_configuration.web_admin_enabled
    ):
        require_action(
            request,
            resource_type="builtin_tool",
            resource_code="*",
            action="read",
        )


def _correlation_id(request: Request) -> str:
    return str(
        getattr(request.state, "correlation_id", "") or request.headers.get("x-correlation-id", "")
    ).strip()


def _builtin_tool_error_code(exc: Exception) -> str:
    if isinstance(exc, AppError) and exc.error_code:
        return exc.error_code
    if isinstance(exc, HTTPException):
        return {
            401: "authentication_required",
            403: "builtin_tool_management_denied",
            404: "builtin_tool_not_found",
        }.get(exc.status_code, "builtin_tool_management_failed")
    if isinstance(exc, NotFound):
        return "builtin_tool_not_found"
    if isinstance(exc, PermissionDenied):
        return "builtin_tool_management_denied"
    if isinstance(exc, ValueError):
        return "builtin_tool_manifest_invalid"
    return "builtin_tool_management_failed"


def _builtin_tool_error_status(exc: Exception, error_code: str) -> int:
    if isinstance(exc, HTTPException):
        return exc.status_code
    if isinstance(exc, PermissionDenied):
        return 403
    if isinstance(exc, NotFound):
        return 404
    if error_code in {
        "builtin_tool_release_lifecycle_invalid",
        "builtin_tool_release_dependency_in_use",
        "builtin_tool_publish_idempotency_conflict",
    }:
        return 409
    if error_code in {
        "builtin_tool_verification_missing",
        "builtin_tool_verification_stale",
        "builtin_tool_verification_failed",
    }:
        return 422
    if error_code in {
        "builtin_tool_installation_missing",
        "builtin_tool_installation_drifted",
    }:
        return 503
    if isinstance(exc, (AppError, ValueError)):
        return 400
    return 500


def _builtin_tool_error_message(exc: Exception, status_code: int) -> str:
    if isinstance(exc, AppError):
        return exc.safe_message
    if status_code == 401:
        return "请先登录"
    if status_code == 403:
        return "你无权执行此操作"
    if status_code == 404:
        return "未找到请求的内置工具对象"
    if isinstance(exc, ValueError):
        return "内置工具治理请求参数无效"
    return "内置工具治理操作失败"


def _handle_builtin_tool_rejection(
    request: Request,
    exc: Exception,
    *,
    operation: str,
    entity_type: str,
    entity_id: str,
    actor_id: str | None,
) -> HTTPException:
    correlation_id = _correlation_id(request)
    error_code = _builtin_tool_error_code(exc)
    status_code = _builtin_tool_error_status(exc, error_code)
    details = {
        "operation": operation,
        "entity_type": entity_type,
        "entity_id": entity_id,
    }
    _container(request).audit_service.record(
        "admin.builtin_tool.governance.denied",
        status="DENIED",
        summary="Built-in Tool governance action denied",
        actor_id=actor_id,
        payload={
            **details,
            "error_code": error_code,
            "correlation_id": correlation_id,
        },
    )
    return HTTPException(
        status_code=status_code,
        detail={
            "error": {
                "code": error_code,
                "message": _builtin_tool_error_message(exc, status_code),
                "correlation_id": correlation_id,
                "retryable": status_code in {500, 503},
                "details": details,
            }
        },
    )


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, PermissionDenied):
        return HTTPException(status_code=403, detail=exc.safe_message)
    if isinstance(exc, NotFound):
        return HTTPException(status_code=404, detail=exc.safe_message)
    if isinstance(exc, AppError):
        return HTTPException(status_code=400, detail=exc.safe_message)
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="服务器内部错误")


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
        _require_management_read(request, resource_type="secret")
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

    @router.get("/secrets")
    def list_platform_secrets(
        request: Request,
        include_disabled: bool = Query(default=True),
    ) -> dict[str, Any]:
        _require_management_read(request, resource_type="secret")
        service = _container(request).platform_config_service
        return {"secrets": service.list_platform_secrets(include_disabled=include_disabled)}

    @router.post("/secrets")
    async def create_platform_secret(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            entity = _container(request).platform_config_service.create_platform_secret(
                payload,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"secret": entity}

    @router.get("/secrets/{code}")
    def get_platform_secret(request: Request, code: str) -> dict[str, Any]:
        _require_management_read(request, resource_type="secret")
        try:
            entity = _container(request).platform_config_service.get_platform_secret(code)
        except Exception as exc:
            raise _handle(exc) from exc
        return {"secret": entity}

    @router.get("/secrets/{code}/usage")
    def get_platform_secret_usage(
        request: Request,
        code: str,
    ) -> dict[str, Any]:
        _require_management_read(request, resource_type="secret")
        try:
            usage = _container(request).platform_config_service.get_platform_secret_usage(code)
        except Exception as exc:
            raise _handle(exc) from exc
        return {"usage": usage}

    @router.get("/secrets/legacy-env/report")
    def legacy_env_secret_report(request: Request) -> dict[str, Any]:
        _require_management_read(request, resource_type="secret")
        try:
            report = _container(request).platform_config_service.legacy_env_secret_report()
        except Exception as exc:
            raise _handle(exc) from exc
        return {"report": report}

    @router.post("/secrets/legacy-env/import")
    async def import_legacy_env_secret(
        request: Request,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            result = _container(request).platform_config_service.import_legacy_env_secret(
                payload,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"result": result}

    @router.post("/secrets/{code}/rotate")
    async def rotate_platform_secret(
        request: Request, code: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            entity = _container(request).platform_config_service.rotate_platform_secret(
                code,
                payload,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"secret": entity}

    @router.post("/secrets/{code}/disable")
    def disable_platform_secret(request: Request, code: str) -> dict[str, Any]:
        try:
            entity = _container(request).platform_config_service.disable_platform_secret(
                code,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"secret": entity}

    @router.get("/runtime-config/definitions")
    def list_runtime_config_definitions(
        request: Request,
        include_disabled: bool = Query(default=True),
    ) -> dict[str, Any]:
        _require_management_read(request, resource_type="platform_config")
        service = _container(request).platform_config_service
        service.ensure_runtime_config_definitions()
        return {
            "definitions": service.list_runtime_config_definitions(
                include_disabled=include_disabled
            )
        }

    @router.post("/runtime-config/definitions")
    async def upsert_runtime_config_definition(
        request: Request, payload: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            entity = _container(request).platform_config_service.upsert_runtime_config_definition(
                payload,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"definition": entity}

    @router.get("/runtime-config/values")
    def list_runtime_config_values(
        request: Request,
        include_disabled: bool = Query(default=True),
    ) -> dict[str, Any]:
        _require_management_read(request, resource_type="platform_config")
        service = _container(request).platform_config_service
        return {"values": service.list_runtime_config_values(include_disabled=include_disabled)}

    @router.post("/runtime-config/values")
    async def upsert_runtime_config_value(
        request: Request, payload: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            entity = _container(request).platform_config_service.upsert_runtime_config_value(
                payload,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"value": entity}

    @router.post("/runtime-config/values/{value_id}/disable")
    def disable_runtime_config_value(request: Request, value_id: str) -> dict[str, Any]:
        return _set_runtime_config_value_status(request, value_id, "disabled")

    @router.get("/runtime-config/snapshot")
    def runtime_config_snapshot(
        request: Request,
        service_name: str = "",
        project: str = "",
        environment: str = "",
        base: str = "",
        workshop: str = "",
        connector: str = "",
    ) -> dict[str, Any]:
        _require_management_read(request, resource_type="platform_config")
        scopes = {
            "project": project,
            "environment": environment,
            "base": base,
            "workshop": workshop,
            "connector": connector,
        }
        return {
            "snapshot": _container(request).platform_config_service.runtime_config_snapshot(
                service_name=service_name,
                scopes={key: value for key, value in scopes.items() if value},
            )
        }

    @router.get("/runtime-config/env-migration")
    def runtime_config_env_migration(request: Request) -> dict[str, Any]:
        _require_management_read(request, resource_type="platform_config")
        return {"items": _container(request).platform_config_service.runtime_config_env_migration()}

    @router.get("/runtime-config/features")
    def effective_feature_configuration(request: Request) -> dict[str, Any]:
        if not _container(request).settings.feature_configuration.web_admin_enabled:
            raise HTTPException(status_code=404, detail="Web 管理功能已停用")
        _require_management_read(request, resource_type="platform_config")
        c = _container(request)
        return {
            "features": c.settings.feature_configuration.to_snapshot(
                revision=c.settings.runtime_config_revision,
                config_hash=c.settings.runtime_config_hash,
                source=c.settings.runtime_config_source,
            )
        }

    @router.get("/resource-bindings")
    def list_resource_bindings(
        request: Request,
        include_disabled: bool = Query(default=True),
    ) -> dict[str, Any]:
        _require_management_read(request, resource_type="platform_config")
        service = _container(request).platform_config_service
        return {
            "resource_bindings": service.list_resource_bindings(include_disabled=include_disabled)
        }

    @router.get("/provider-contracts")
    def list_provider_contracts(request: Request) -> dict[str, Any]:
        _require_management_read(
            request,
            resource_type="platform_config",
        )
        return {
            "contracts": (_container(request).platform_config_service.list_provider_contracts())
        }

    @router.get("/builtin-tools")
    def list_builtin_tools(request: Request) -> dict[str, Any]:
        _require_builtin_tool_read(request)
        return {"tools": (_container(request).platform_config_service.handlers.catalog())}

    @router.post("/builtin-tools/reconcile")
    def reconcile_builtin_tools(request: Request) -> dict[str, Any]:
        actor_id: str | None = None
        try:
            actor_id = _actor(request)
            summary = _container(request).platform_config_service.handlers.reconcile(
                actor_id=actor_id,
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle_builtin_tool_rejection(
                request,
                exc,
                operation="reconcile",
                entity_type="builtin_tool_registry",
                entity_id="code",
                actor_id=actor_id,
            ) from exc
        return {"summary": summary}

    @router.get("/builtin-tools/{tool_identifier}")
    def get_builtin_tool(
        request: Request,
        tool_identifier: str,
    ) -> dict[str, Any]:
        _require_builtin_tool_read(request)
        try:
            tool = _container(request).platform_config_service.handlers.detail(tool_identifier)
        except Exception as exc:
            raise _handle(exc) from exc
        return {"tool": tool}

    @router.post("/builtin-tools/{tool_identifier}/verify")
    async def verify_builtin_tool(
        request: Request,
        tool_identifier: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        actor_id: str | None = None
        try:
            actor_id = _actor(request)
            verification = _container(request).platform_config_service.handlers.verify_payload(
                {
                    **payload,
                    "tool_identifier": tool_identifier,
                },
                actor_id=actor_id,
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle_builtin_tool_rejection(
                request,
                exc,
                operation="verify",
                entity_type="builtin_tool",
                entity_id=tool_identifier,
                actor_id=actor_id,
            ) from exc
        return {"verification": verification}

    @router.post("/builtin-tools/{tool_identifier}/publish")
    async def publish_builtin_tool(
        request: Request,
        tool_identifier: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        actor_id: str | None = None
        try:
            actor_id = _actor(request)
            release = _container(
                request
            ).platform_config_service.handlers.publish_builtin_tool_payload(
                {
                    **payload,
                    "tool_identifier": tool_identifier,
                },
                actor_id=actor_id,
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle_builtin_tool_rejection(
                request,
                exc,
                operation="publish",
                entity_type="builtin_tool",
                entity_id=tool_identifier,
                actor_id=actor_id,
            ) from exc
        return {"release": release}

    @router.post("/builtin-tool-releases/{release_id}/lifecycle")
    async def set_builtin_tool_release_lifecycle(
        request: Request,
        release_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        actor_id: str | None = None
        try:
            actor_id = _actor(request)
            release = _container(
                request
            ).platform_config_service.handlers.set_builtin_tool_release_status(
                release_id,
                str(payload.get("status") or ""),
                reason_code=str(payload.get("reason_code") or ""),
                verification_id=str(payload.get("verification_id") or ""),
                actor_id=actor_id,
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle_builtin_tool_rejection(
                request,
                exc,
                operation="lifecycle",
                entity_type="builtin_tool_release",
                entity_id=release_id,
                actor_id=actor_id,
            ) from exc
        return {"release": release}

    @router.get("/resources")
    def list_governed_resources(
        request: Request,
        resource_kind: str = "",
        scope_type: str = "",
        lifecycle_status: str = "",
        revision_status: str = "",
        activation_status: str = "",
    ) -> dict[str, Any]:
        _require_management_read(
            request,
            resource_type="platform_config",
        )
        resources = _container(request).platform_config_service.governed_resources.list_resources()
        filters = {
            "resource_kind": resource_kind.lower(),
            "scope_type": scope_type.lower(),
            "status": lifecycle_status.lower(),
            "activation_status": activation_status.upper(),
        }
        for key, expected in filters.items():
            if expected:
                resources = [
                    item
                    for item in resources
                    if str(item.get(key) or "").lower() == expected.lower()
                ]
        if revision_status:
            expected_revision_status = revision_status.upper()
            resources = [
                item
                for item in resources
                if (
                    str((item.get("published_revision") or {}).get("status") or "NONE")
                    == expected_revision_status
                )
            ]
        return {"resources": resources}

    @router.post("/resources")
    async def create_governed_resource(
        request: Request,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return _container(request).platform_config_service.governed_resources.create_resource(
                payload,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc

    @router.put("/resources/{code}/draft")
    async def save_governed_resource_draft(
        request: Request,
        code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            expected_revision = int(payload.pop("expected_revision", 0))
            draft = _container(request).platform_config_service.governed_resources.save_draft(
                code,
                payload,
                expected_revision=expected_revision,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"draft": draft}

    @router.delete("/resources/{code}/draft")
    def delete_governed_resource_draft(
        request: Request,
        code: str,
        expected_revision: int = Query(gt=0),
    ) -> dict[str, Any]:
        try:
            (
                _container(request).platform_config_service.governed_resources.delete_draft(
                    code,
                    expected_revision=expected_revision,
                    actor_id=_actor(request),
                    correlation_id=_correlation_id(request),
                )
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"deleted": True}

    @router.post("/resources/{code}/verify")
    def verify_governed_resource_draft(
        request: Request,
        code: str,
    ) -> dict[str, Any]:
        try:
            verification = _container(
                request
            ).platform_config_service.governed_resources.verify_draft(
                code,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"verification": verification}

    @router.post("/resources/{code}/loki/test")
    async def test_loki_resource_draft(
        request: Request,
        code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return _container(request).platform_config_service.loki_draft_discovery.test_draft(
                code,
                actor_id=_actor(request),
                minutes=int(payload.get("minutes") or 15),
                limit=int(payload.get("limit") or 64),
            )
        except Exception as exc:
            raise _handle(exc) from exc

    @router.post("/resources/{code}/loki/label-values")
    async def discover_loki_resource_draft_label_values(
        request: Request,
        code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return _container(request).platform_config_service.loki_draft_discovery.label_values(
                code,
                test_session_id=str(payload.get("test_session_id") or ""),
                label=str(payload.get("label") or ""),
                selected_conditions=payload.get("selected_conditions"),
                actor_id=_actor(request),
                minutes=int(payload.get("minutes") or 15),
                limit=int(payload.get("limit") or 100),
            )
        except Exception as exc:
            raise _handle(exc) from exc

    @router.post("/resources/{code}/publish")
    def publish_governed_resource_draft(
        request: Request,
        code: str,
    ) -> dict[str, Any]:
        try:
            revision = _container(request).platform_config_service.governed_resources.publish_draft(
                code,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"revision": revision}

    @router.post("/resources/{code}/draft/from-revision")
    async def create_governed_resource_draft_from_revision(
        request: Request,
        code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            draft = _container(
                request
            ).platform_config_service.governed_resources.create_draft_from_revision(
                code,
                str(payload.get("revision_id") or ""),
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"draft": draft}

    @router.post("/resources/{code}/revisions/{revision_id}/{action}")
    def set_governed_resource_revision_status(
        request: Request,
        code: str,
        revision_id: str,
        action: str,
    ) -> dict[str, Any]:
        if action not in {"disable", "archive"}:
            raise HTTPException(
                status_code=404,
                detail="不支持此资源版本操作",
            )
        target_status = {
            "disable": "DISABLED",
            "archive": "ARCHIVED",
        }[action]
        try:
            revision = _container(
                request
            ).platform_config_service.governed_resources.set_revision_status(
                code,
                revision_id,
                target_status,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"revision": revision}

    @router.post("/resources/{code}/lifecycle/{action}")
    async def set_governed_resource_identity_status(
        request: Request,
        code: str,
        action: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if action not in {"disable", "restore", "archive"}:
            raise HTTPException(
                status_code=404,
                detail="不支持此资源身份操作",
            )
        target_status = {
            "disable": "disabled",
            "restore": "enabled",
            "archive": "archived",
        }[action]
        try:
            resource = _container(
                request
            ).platform_config_service.governed_resources.set_resource_status(
                code,
                target_status,
                expected_revision=int(payload.get("expected_revision") or 0),
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"resource": resource}

    @router.get("/workshop-partition-policies")
    def list_workshop_partition_policies(request: Request) -> dict[str, Any]:
        _require_management_read(request, resource_type="platform_config")
        return {
            "policies": _container(
                request
            ).platform_config_service.workshop_partition_policies.list()
        }

    @router.post("/workshop-partition-policies")
    async def create_workshop_partition_policy(
        request: Request,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            policy = _container(request).platform_config_service.workshop_partition_policies.create(
                payload,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"policy": policy}

    @router.get("/workshop-partition-policies/{code}")
    def get_workshop_partition_policy(
        request: Request,
        code: str,
    ) -> dict[str, Any]:
        _require_management_read(request, resource_type="platform_config")
        try:
            policy = _container(request).platform_config_service.workshop_partition_policies.detail(
                code
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"policy": policy}

    @router.put("/workshop-partition-policies/{code}/draft")
    async def save_workshop_partition_policy_draft(
        request: Request,
        code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            draft = _container(
                request
            ).platform_config_service.workshop_partition_policies.save_draft(
                code,
                expected_draft_revision=int(payload.get("expected_draft_revision") or 0),
                payload={
                    key: payload.get(key)
                    for key in (
                        "database_rule_enabled",
                        "database_table_prefix",
                        "redis_rule_enabled",
                        "redis_prefixes",
                    )
                },
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"draft": draft}

    @router.post("/workshop-partition-policies/{code}/verify")
    async def verify_workshop_partition_policy(
        request: Request,
        code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            verification = _container(
                request
            ).platform_config_service.workshop_partition_policies.verify(
                code,
                expected_draft_revision=int(payload.get("expected_draft_revision") or 0),
                redis_resource_revision_id=str(payload.get("redis_resource_revision_id") or "")
                or None,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"verification": verification}

    @router.post("/workshop-partition-policies/{code}/publish")
    async def publish_workshop_partition_policy(
        request: Request,
        code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            revision = _container(
                request
            ).platform_config_service.workshop_partition_policies.publish(
                code,
                verification_id=str(payload.get("verification_id") or ""),
                expected_policy_revision=int(payload.get("expected_policy_revision") or 0),
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"revision": revision}

    @router.post("/workshop-partition-policies/{code}/draft/from-revision")
    async def copy_workshop_partition_policy_revision(
        request: Request,
        code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            draft = _container(
                request
            ).platform_config_service.workshop_partition_policies.copy_revision_to_draft(
                code,
                source_revision_id=str(payload.get("source_revision_id") or ""),
                expected_policy_revision=int(payload.get("expected_policy_revision") or 0),
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"draft": draft}

    @router.get("/loki-scope-policies")
    def list_loki_scope_policies(request: Request) -> dict[str, Any]:
        _require_management_read(request, resource_type="platform_config")
        return {"policies": _container(request).platform_config_service.loki_scope_policies.list()}

    @router.post("/loki-scope-policies")
    async def create_loki_scope_policy(
        request: Request,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            policy = _container(request).platform_config_service.loki_scope_policies.create(
                payload,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"policy": policy}

    @router.get("/loki-scope-policies/{code}")
    def get_loki_scope_policy(request: Request, code: str) -> dict[str, Any]:
        _require_management_read(request, resource_type="platform_config")
        try:
            policy = _container(request).platform_config_service.loki_scope_policies.detail(code)
        except Exception as exc:
            raise _handle(exc) from exc
        return {"policy": policy}

    @router.put("/loki-scope-policies/{code}/draft")
    async def save_loki_scope_policy_draft(
        request: Request,
        code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            draft = _container(request).platform_config_service.loki_scope_policies.save_draft(
                code,
                expected_draft_revision=int(payload.get("expected_draft_revision") or 0),
                payload={
                    "resource_revision_id": payload.get("resource_revision_id"),
                    "conditions": payload.get("conditions"),
                },
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"draft": draft}

    @router.post("/loki-scope-policies/{code}/verify")
    async def verify_loki_scope_policy(
        request: Request,
        code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            verification = _container(request).platform_config_service.loki_scope_policies.verify(
                code,
                expected_draft_revision=int(payload.get("expected_draft_revision") or 0),
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"verification": verification}

    @router.post("/loki-scope-policies/{code}/publish")
    async def publish_loki_scope_policy(
        request: Request,
        code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            revision = _container(request).platform_config_service.loki_scope_policies.publish(
                code,
                verification_id=str(payload.get("verification_id") or ""),
                expected_policy_revision=int(payload.get("expected_policy_revision") or 0),
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"revision": revision}

    @router.post("/loki-scope-policies/{code}/draft/from-revision")
    async def copy_loki_scope_policy_revision(
        request: Request,
        code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            draft = _container(
                request
            ).platform_config_service.loki_scope_policies.copy_revision_to_draft(
                code,
                source_revision_id=str(payload.get("source_revision_id") or ""),
                expected_policy_revision=int(payload.get("expected_policy_revision") or 0),
                actor_id=_actor(request),
                target_resource_revision_id=(
                    str(payload.get("target_resource_revision_id") or "") or None
                ),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"draft": draft}

    @router.post("/loki-scope-policies/{code}/revisions/{revision_id}/health")
    async def refresh_loki_scope_policy_health(
        request: Request,
        code: str,
        revision_id: str,
    ) -> dict[str, Any]:
        try:
            observation = _container(
                request
            ).platform_config_service.loki_scope_policies.refresh_health(
                code,
                policy_revision_id=revision_id,
                actor_id=_actor(request),
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise _handle(exc) from exc
        return {"observation": observation}

    @router.get("/runtime-generation/status")
    def runtime_generation_status(request: Request) -> dict[str, Any]:
        _require_management_read(
            request,
            resource_type="platform_config",
        )
        from app.modules.platform_config.infrastructure.runtime_generation_repository import (
            RuntimeGenerationRepository,
        )

        return {
            "runtime": RuntimeGenerationRepository(_container(request).database).public_status()
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


def _set_runtime_config_value_status(
    request: Request, value_id: str, status: str
) -> dict[str, Any]:
    try:
        entity = _container(request).platform_config_service.set_runtime_config_value_status(
            value_id,
            status,
            actor_id=_actor(request),
            correlation_id=_correlation_id(request),
        )
    except Exception as exc:
        raise _handle(exc) from exc
    return {"value": entity}
