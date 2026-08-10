from __future__ import annotations

import json
from typing import Annotated, Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request as UrlRequest, build_opener

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.bootstrap import Container
from app.modules.identity.api.dependencies import (
    current_principal,
    require_action,
    require_csrf,
)
from app.shared.exceptions import AppError, NonRetryableExecutionError, NotFound, PermissionDenied


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


def _server_read(request: Request) -> str:
    principal = current_principal(request)
    require_action(
        request,
        resource_type="mcp_server",
        resource_code="*",
        action="read",
    )
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


class _ResourceFormBase(_StrictRequest):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0)


class _DatabaseResourceForm(_ResourceFormBase):
    kind: Literal["DATABASE"]
    provider: Literal["mysql", "postgresql", "sqlserver", "oracle"]
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    database_name: str = Field(min_length=1, max_length=128)
    schema_name: str = Field(default="", max_length=128)
    username: str = Field(min_length=1, max_length=128)
    credential_id: str = Field(min_length=1, max_length=200)
    allowed_tables: list[str] = Field(min_length=1, max_length=200)
    max_rows: int = Field(default=200, ge=1, le=1000)
    timeout_seconds: int = Field(default=10, ge=1, le=30)
    tls: bool = True

    @field_validator("allowed_tables")
    @classmethod
    def validate_tables(cls, value: list[str]) -> list[str]:
        normalized = sorted({item.strip() for item in value if item.strip()})
        if not normalized or any(len(item) > 200 for item in normalized):
            raise ValueError("必须填写有效的允许表名")
        return normalized


class _RedisResourceForm(_ResourceFormBase):
    kind: Literal["REDIS"]
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=6379, ge=1, le=65535)
    redis_database: int = Field(default=0, ge=0, le=15)
    username: str = Field(default="", max_length=128)
    credential_id: str = Field(default="", max_length=200)
    key_prefixes: list[str] = Field(min_length=1, max_length=100)
    scan_limit: int = Field(default=100, ge=1, le=500)
    timeout_seconds: int = Field(default=10, ge=1, le=30)
    tls: bool = True

    @field_validator("key_prefixes")
    @classmethod
    def validate_prefixes(cls, value: list[str]) -> list[str]:
        normalized = sorted({item.strip() for item in value if item.strip()})
        if not normalized or any(len(item) > 200 for item in normalized):
            raise ValueError("必须填写有效的 Key 前缀")
        return normalized


class _LokiResourceForm(_ResourceFormBase):
    kind: Literal["LOKI"]
    base_url: str = Field(min_length=1, max_length=500)
    tenant_id: str = Field(default="", max_length=200)
    credential_id: str = Field(default="", max_length=200)
    label_scope: dict[str, str] = Field(min_length=1, max_length=20)
    max_minutes: int = Field(default=60, ge=1, le=1440)
    max_lines: int = Field(default=1000, ge=1, le=5000)
    timeout_seconds: int = Field(default=10, ge=1, le=30)

    @field_validator("label_scope")
    @classmethod
    def validate_labels(cls, value: dict[str, str]) -> dict[str, str]:
        if any(
            not key.strip()
            or len(key) > 128
            or not item.strip()
            or len(item) > 256
            for key, item in value.items()
        ):
            raise ValueError("必须填写有效的标签范围")
        return {key.strip(): item.strip() for key, item in sorted(value.items())}


_ResourceForm = Annotated[
    _DatabaseResourceForm | _RedisResourceForm | _LokiResourceForm,
    Field(discriminator="kind"),
]


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


def _credential_ref(container: Container, credential_id: str, *, required: bool) -> str:
    if not credential_id:
        if required:
            raise ValueError("Credential is required")
        return ""
    row = container.database.execute_one(
        """
        select id, ref, status, active_version
          from platform_secret
         where id = ?
        """,
        (credential_id,),
    )
    if (
        row is None
        or str(row["status"]) != "enabled"
        or int(row.get("active_version") or 0) < 1
        or not str(row.get("ref") or "").startswith("secret://platform/")
    ):
        raise NonRetryableExecutionError(
            "Credential selection is unavailable",
            safe_message="选择的 Credential 不可用，请刷新后重试",
            error_code="credential_unavailable",
        )
    return str(row["ref"])


def _credential_id(container: Container, secret_ref: str) -> str:
    if not secret_ref:
        return ""
    row = container.database.execute_one(
        "select id from platform_secret where ref = ?",
        (secret_ref,),
    )
    return str((row or {}).get("id") or "")


def _manifest_from_form(container: Container, payload: _ResourceForm) -> dict[str, Any]:
    base: dict[str, Any] = {
        "api_version": "enterprise-agent/v1",
        "kind": payload.kind,
        "metadata": {"code": payload.code, "name": payload.name},
    }
    if isinstance(payload, _DatabaseResourceForm):
        base["spec"] = {
            "provider": payload.provider,
            "host": payload.host.strip(),
            "port": payload.port,
            "database": payload.database_name.strip(),
            "schema": payload.schema_name.strip(),
            "username": payload.username.strip(),
            "password_ref": _credential_ref(
                container, payload.credential_id, required=True
            ),
            "allowed_tables": payload.allowed_tables,
            "max_rows": payload.max_rows,
            "timeout_seconds": payload.timeout_seconds,
            "tls": payload.tls,
        }
    elif isinstance(payload, _RedisResourceForm):
        base["spec"] = {
            "host": payload.host.strip(),
            "port": payload.port,
            "database": payload.redis_database,
            "username": payload.username.strip(),
            "password_ref": _credential_ref(
                container, payload.credential_id, required=False
            ),
            "key_prefixes": payload.key_prefixes,
            "scan_limit": payload.scan_limit,
            "timeout_seconds": payload.timeout_seconds,
            "tls": payload.tls,
        }
    else:
        base["spec"] = {
            "base_url": payload.base_url.strip(),
            "tenant_id": payload.tenant_id.strip(),
            "auth_ref": _credential_ref(
                container, payload.credential_id, required=False
            ),
            "label_scope": payload.label_scope,
            "max_minutes": payload.max_minutes,
            "max_lines": payload.max_lines,
            "timeout_seconds": payload.timeout_seconds,
        }
    return base


def _resource_form(container: Container, code: str) -> dict[str, Any]:
    resource = container.database.execute_one(
        "select * from mcp_resource where code = ?", (code,)
    )
    if resource is None:
        raise NotFound("MCP Resource not found", safe_message="资源不存在")
    stored = container.database.execute_one(
        """
        select manifest_json
          from mcp_resource_draft
         where resource_id = ? and status in ('DRAFT', 'VERIFIED')
         order by draft_revision desc limit 1
        """,
        (resource["id"],),
    ) or container.database.execute_one(
        """
        select manifest_json
          from mcp_resource_revision
         where resource_id = ?
         order by revision desc limit 1
        """,
        (resource["id"],),
    )
    if stored is None:
        raise NotFound("MCP Resource form not found", safe_message="资源配置不存在")
    manifest = json.loads(str(stored["manifest_json"]))
    spec = dict(manifest.get("spec") or {})
    common = {
        "kind": str(manifest["kind"]),
        "code": str(manifest["metadata"]["code"]),
        "name": str(manifest["metadata"]["name"]),
        "expected_revision": int(resource["revision"]),
    }
    kind = common["kind"]
    if kind == "DATABASE":
        return {
            **common,
            "provider": str(spec.get("provider") or "postgresql"),
            "host": str(spec.get("host") or ""),
            "port": int(spec.get("port") or 5432),
            "database_name": str(spec.get("database") or ""),
            "schema_name": str(spec.get("schema") or ""),
            "username": str(spec.get("username") or ""),
            "credential_id": _credential_id(container, str(spec.get("password_ref") or "")),
            "allowed_tables": list(spec.get("allowed_tables") or []),
            "max_rows": int(spec.get("max_rows") or 200),
            "timeout_seconds": int(spec.get("timeout_seconds") or 10),
            "tls": bool(spec.get("tls", True)),
        }
    if kind == "REDIS":
        return {
            **common,
            "host": str(spec.get("host") or ""),
            "port": int(spec.get("port") or 6379),
            "redis_database": int(spec.get("database") or 0),
            "username": str(spec.get("username") or ""),
            "credential_id": _credential_id(container, str(spec.get("password_ref") or "")),
            "key_prefixes": list(spec.get("key_prefixes") or []),
            "scan_limit": int(spec.get("scan_limit") or 100),
            "timeout_seconds": int(spec.get("timeout_seconds") or 10),
            "tls": bool(spec.get("tls", True)),
        }
    return {
        **common,
        "base_url": str(spec.get("base_url") or ""),
        "tenant_id": str(spec.get("tenant_id") or ""),
        "credential_id": _credential_id(container, str(spec.get("auth_ref") or "")),
        "label_scope": dict(spec.get("label_scope") or {}),
        "max_minutes": int(spec.get("max_minutes") or 60),
        "max_lines": int(spec.get("max_lines") or 1000),
        "timeout_seconds": int(spec.get("timeout_seconds") or 10),
    }


def build_mcp_resource_router() -> APIRouter:
    router = APIRouter(prefix="/api/admin/mcp", tags=["mcp-resource-operations"])

    @router.get("/resource-form-schema")
    def resource_form_schema(request: Request) -> dict[str, Any]:
        _read(request)
        return {
            "schema_version": 1,
            "kinds": [
                {
                    "kind": "DATABASE",
                    "display_name": "Database",
                    "providers": ["mysql", "postgresql", "sqlserver", "oracle"],
                    "credential_required": True,
                },
                {
                    "kind": "REDIS",
                    "display_name": "Redis",
                    "credential_required": False,
                },
                {
                    "kind": "LOKI",
                    "display_name": "Loki",
                    "credential_required": False,
                },
            ],
        }

    @router.get("/resource-credential-candidates")
    def resource_credential_candidates(request: Request) -> dict[str, Any]:
        principal = require_action(
            request, resource_type="mcp_resource", resource_code="*", action="manage"
        )
        require_action(request, resource_type="secret", resource_code="*", action="read")
        del principal
        rows = _container(request).database.execute(
            """
            select id, code, purpose, status, active_version, masked_summary, revision
              from platform_secret
             where status = 'enabled' and active_version > 0
             order by lower(code), id
            """
        )
        return {"items": rows}

    @router.post("/resource-drafts")
    def save_resource_form(
        request: Request,
        payload: _ResourceForm,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        actor = _write(request)
        try:
            manifest = _manifest_from_form(_container(request), payload)
            result = _container(request).mcp_resource_service.apply(
                manifest,
                actor_id=actor,
                expected_revision=payload.expected_revision,
                idempotency_key=idempotency_key,
            )
            return {"resource": result}
        except Exception as exc:
            raise _handle(exc) from exc

    @router.get("/resource-forms/{code}")
    def resource_form(request: Request, code: str) -> dict[str, Any]:
        _read(request)
        try:
            return {"form": _resource_form(_container(request), code)}
        except Exception as exc:
            raise _handle(exc) from exc

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
        _server_read(request)
        container = _container(request)
        publication_counts: dict[str, int] = {}
        publications = container.database.execute(
            """
            select server_code, status, count(*) as publication_count
              from mcp_tool_publication
             group by server_code, status
             order by server_code
            """
        )
        for item in publications:
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
                    "source": "deployment_config",
                    "transport": {
                        "type": "streamable_http",
                        "authentication": "runtime_bearer",
                    },
                    "health": _health(container.settings.mcp.ones_server_url),
                    "active_publications": publication_counts.get("ones-mcp", 0),
                },
                {
                    "server_code": "data-mcp",
                    "source": "deployment_config",
                    "transport": {
                        "type": "streamable_http",
                        "authentication": "runtime_bearer",
                    },
                    "health": _health(container.settings.mcp.data_server_url),
                    "active_publications": publication_counts.get("data-mcp", 0),
                },
            ]
        }

    return router
