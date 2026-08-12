from __future__ import annotations

import json
import logging
import socket
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from app.modules.identity.application.ones_identity import OnesIdentityVerifier
from app.modules.identity.application.principal_jwt import (
    ONES_SEARCH_SCOPE,
    ONES_SEARCH_TOOL,
    PrincipalTokenVerifier,
)
from app.modules.identity.infrastructure.external_identity_credentials import (
    ExternalIdentityCredentialRepository,
    ResolvedExternalCredential,
)
from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.modules.mcp_tool_runtime.job_snapshot import JobMcpToolSnapshotService
from app.shared.database import Database, assert_external_io_allowed, operation_unit_of_work
from app.shared.exceptions import AppError, NonRetryableExecutionError, RetryableExecutionError
from services.ones_mcp_server.contracts import (
    ISSUE_TYPES,
    LOGIN_PATH,
    PROVIDER_HEADERS,
    REQUIRED_SCOPE,
    SERVER_CODE,
    TOOL_IDENTIFIER,
    WORK_ITEM_SEARCH_DOCUMENT,
    WORK_ITEM_SEARCH_PATH,
    ProviderTarget,
)


_FORBIDDEN_BUSINESS_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "password",
        "token",
        "access_token",
        "refresh_token",
        "ciphertext",
        "nonce",
        "private_key",
        "principal_jwt",
        "principal_token",
    }
)
logger = logging.getLogger(__name__)


class PrincipalBusinessAuthorizationPort(Protocol):
    def require(
        self,
        *,
        user_id: str,
        application_id: str,
        tool_identifier: str,
        stage: str,
    ) -> dict[str, Any]: ...


class OnesMcpError(NonRetryableExecutionError):
    pass


class OnesProviderUnauthorized(OnesMcpError):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedOnesPrincipal:
    job_id: str
    session_id: str
    actor_user_id: str
    principal_jti: str
    external_identity_id: str
    provider_user_id: str
    provider_email: str
    team_id: str
    credential: ResolvedExternalCredential


@dataclass(frozen=True, slots=True)
class AuditContext:
    correlation_id: str
    principal: ResolvedOnesPrincipal


class McpOperationAuditRepository:
    """Persist complete bounded business evidence while rejecting auth material."""

    def __init__(
        self,
        database: Database,
        *,
        max_payload_bytes: int,
        platform_audit_service: Any | None = None,
    ) -> None:
        if not 1024 <= max_payload_bytes <= 1024 * 1024:
            raise ValueError("MCP audit payload limit is invalid")
        self.database = database
        self.max_payload_bytes = max_payload_bytes
        self.platform_audit_service = platform_audit_service

    @operation_unit_of_work(lambda repository: repository.database)
    def record(
        self,
        context: AuditContext,
        *,
        operation: str,
        event_kind: str,
        attempt: int,
        status: str,
        error_code: str = "",
        duration_ms: int = 0,
        tool_request: dict[str, Any] | None = None,
        provider_request: dict[str, Any] | None = None,
        provider_response: dict[str, Any] | None = None,
        tool_response: dict[str, Any] | None = None,
    ) -> str:
        values = (
            tool_request or {},
            provider_request or {},
            provider_response or {},
            tool_response or {},
        )
        serialized = tuple(self._business_json(value) for value in values)
        principal = context.principal
        audit_id = new_id("mcp_audit")
        try:
            platform_audit_id = (
                self.platform_audit_service.record(
                    "mcp.operation",
                    status=status,
                    summary="ONES MCP operation evidence persisted",
                    job_id=principal.job_id,
                    actor_id=principal.actor_user_id,
                    payload={
                        "mcp_operation_audit_id": audit_id,
                        "correlation_id": context.correlation_id,
                        "principal_jti": principal.principal_jti,
                        "external_identity_id": principal.external_identity_id,
                        "credential_revision": principal.credential.revision,
                        "server_code": SERVER_CODE,
                        "tool_identifier": TOOL_IDENTIFIER,
                        "operation": operation,
                        "event_kind": event_kind,
                        "attempt": attempt,
                        "status": status,
                        "error_code": error_code[:128],
                    },
                )
                if self.platform_audit_service is not None
                else None
            )
            self.database.execute(
                """
                insert into mcp_operation_audit
                  (id, correlation_id, job_id, session_id, principal_jti,
                   actor_user_id, actor_type, external_identity_id,
                   credential_id, credential_revision, provider, team_id,
                   provider_email, provider_user_id, server_code,
                   tool_identifier, operation, event_kind, attempt, status,
                   error_code, duration_ms, payload_schema_version,
                   tool_request_json, provider_request_json,
                   provider_response_json, tool_response_json, audit_event_id,
                   created_at)
                values (?, ?, ?, ?, ?, ?, 'user', ?, ?, ?, 'ones', ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    context.correlation_id,
                    principal.job_id,
                    principal.session_id,
                    principal.principal_jti,
                    principal.actor_user_id,
                    principal.external_identity_id,
                    principal.credential.id,
                    principal.credential.revision,
                    principal.team_id,
                    principal.provider_email,
                    principal.provider_user_id,
                    SERVER_CODE,
                    TOOL_IDENTIFIER,
                    operation,
                    event_kind,
                    max(0, attempt),
                    status,
                    error_code[:128],
                    max(0, duration_ms),
                    *serialized,
                    platform_audit_id,
                    now_iso(),
                ),
            )
        except Exception as exc:
            logger.error(
                "MCP operation audit persistence failed safely error_type=%s",
                type(exc).__name__,
            )
            raise OnesMcpError(
                "MCP operation audit could not be persisted",
                safe_message="ONES 查询审计不可用，请稍后重试",
                error_code="mcp_audit_unavailable",
            ) from exc
        return audit_id

    def purge_expired(self, *, retention_days: int) -> int:
        if not 1 <= retention_days <= 3650:
            raise ValueError("MCP operation audit retention is invalid")
        cutoff = time.time() - retention_days * 24 * 60 * 60
        cutoff_iso = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(cutoff))
        deleted = self.database.execute(
            "delete from mcp_operation_audit where created_at < ? returning id",
            (cutoff_iso,),
        )
        return len(deleted)

    def _business_json(self, value: dict[str, Any]) -> str:
        if not isinstance(value, dict):
            raise OnesMcpError(
                "MCP audit business payload must be an object",
                safe_message="ONES 查询审计载荷无效",
                error_code="mcp_audit_payload_invalid",
            )
        self._reject_secret_fields(value)
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(serialized.encode("utf-8")) > self.max_payload_bytes:
            raise OnesMcpError(
                "MCP audit business payload exceeds its bound",
                safe_message="ONES 查询审计载荷超限",
                error_code="mcp_audit_payload_too_large",
            )
        return serialized

    @classmethod
    def _reject_secret_fields(cls, value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).strip().lower() in _FORBIDDEN_BUSINESS_KEYS:
                    raise OnesMcpError(
                        "Authentication material appeared in a business payload",
                        safe_message="ONES 返回了无效业务数据",
                        error_code="ones_provider_secret_violation",
                    )
                cls._reject_secret_fields(child)
        elif isinstance(value, list):
            for child in value:
                cls._reject_secret_fields(child)


class OnesPrincipalResolver:
    def __init__(
        self,
        database: Database,
        verifier: PrincipalTokenVerifier,
        snapshot_service: JobMcpToolSnapshotService,
        business_authorization_service: PrincipalBusinessAuthorizationPort,
        credential_repository: ExternalIdentityCredentialRepository,
    ) -> None:
        self.database = database
        self.verifier = verifier
        self.snapshot_service = snapshot_service
        self.business_authorization_service = business_authorization_service
        self.credential_repository = credential_repository

    def authenticate(self, token: str) -> dict[str, Any]:
        return self.verifier.verify_for_running_job(
            token,
            self.database,
            required_scope=ONES_SEARCH_SCOPE,
        )

    def resolve(self, claims: dict[str, Any]) -> ResolvedOnesPrincipal:
        job = self.database.execute_one(
            """
            select j.id, j.session_id, j.project_code, j.internal_user_id,
                   j.business_application_id,
                   j.agent_publication_id,
                   j.business_application_publication_id,
                   s.application_publication_id,
                   u.status as user_status,
                   u.account_type as user_account_type
              from agent_job j
              join agent_session s on s.id = j.session_id
              join app_user u on u.id = j.internal_user_id
             where j.id = ? and j.status = 'RUNNING'
            """,
            (claims["job_id"],),
        )
        if (
            job is None
            or str(job["internal_user_id"]) != claims["sub"]
            or str(job["session_id"]) != claims["session_id"]
            or str(job["agent_publication_id"]) != claims["agent_publication_id"]
            or str(job["business_application_publication_id"])
            != claims["application_publication_id"]
            or str(job["application_publication_id"]) != claims["application_publication_id"]
        ):
            raise self._denied("ones_principal_provenance_mismatch")
        if str(job["user_status"]) != "enabled" or str(job["user_account_type"]) != "human":
            raise self._denied("ones_principal_user_inactive")
        verified = self.snapshot_service.verify(str(job["id"]))
        snapshot = verified["snapshot"]
        matches = [
            item
            for item in snapshot.get("tools") or []
            if isinstance(item, dict)
            and item.get("server_code") == SERVER_CODE
            and item.get("tool_identifier") == TOOL_IDENTIFIER
        ]
        if (
            len(matches) != 1
            or str(verified.get("authorization_hash") or "") != claims["authorization_hash"]
        ):
            raise self._denied("ones_principal_snapshot_denied")
        self.business_authorization_service.require(
            user_id=claims["sub"],
            application_id=str(job["business_application_id"]),
            tool_identifier=TOOL_IDENTIFIER,
            stage="ones_principal_resolve",
        )
        identities = self.database.execute(
            """
            select * from user_external_identity
             where user_id = ? and provider = 'ones' and status = 'enabled'
             order by id
            """,
            (claims["sub"],),
        )
        if len(identities) != 1:
            raise self._denied(
                "ones_identity_missing" if not identities else "ones_identity_ambiguous"
            )
        identity = identities[0]
        try:
            metadata = json.loads(str(identity.get("metadata_json") or "{}"))
        except json.JSONDecodeError:
            raise self._denied("ones_identity_invalid") from None
        team_ids = metadata.get("team_uuids") if isinstance(metadata, dict) else None
        default_team_id = (
            str(metadata.get("default_team_id") or "").strip() if isinstance(metadata, dict) else ""
        )
        if (
            not isinstance(team_ids, list)
            or not default_team_id
            or team_ids.count(default_team_id) != 1
        ):
            raise self._denied("ones_default_team_invalid")
        credential_row = self.credential_repository.get_by_identity(str(identity["id"]))
        if credential_row is None or str(credential_row.get("status")) != "ACTIVE":
            raise self._denied("ones_credential_reverification_required")
        credential = self.credential_repository.resolve_active(str(credential_row["id"]))
        if credential.provider != "ones":
            raise self._denied("ones_credential_provider_mismatch")
        return ResolvedOnesPrincipal(
            job_id=str(job["id"]),
            session_id=str(job["session_id"]),
            actor_user_id=claims["sub"],
            principal_jti=claims["jti"],
            external_identity_id=str(identity["id"]),
            provider_user_id=str(identity["external_subject_id"]),
            provider_email=credential.secrets.email,
            team_id=default_team_id,
            credential=credential,
        )

    @staticmethod
    def _denied(error_code: str) -> OnesMcpError:
        return OnesMcpError(
            "ONES Principal could not be resolved from current platform facts",
            safe_message="当前用户的 ONES 身份或权限不可用，请重新验证",
            error_code=error_code,
        )


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class OnesProviderClient:
    def __init__(
        self,
        target: ProviderTarget,
        *,
        timeout_seconds: int,
        max_response_bytes: int,
        open_response: Any | None = None,
    ) -> None:
        if not 1 <= timeout_seconds <= 30 or not 1024 <= max_response_bytes <= 1024 * 1024:
            raise ValueError("ONES Provider bounds are invalid")
        self.target = target
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self._open_response = open_response
        self._opener = build_opener(ProxyHandler({}), _NoRedirectHandler())

    def search(
        self,
        principal: ResolvedOnesPrincipal,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        variables = {
            "keyword": arguments["keyword"],
            "issue_type": arguments["issue_type"],
            "limit": arguments["limit"],
            "user_id": principal.provider_user_id,
            "team_id": principal.team_id,
        }
        provider_request = {
            "query": WORK_ITEM_SEARCH_DOCUMENT,
            "variables": variables,
        }
        payload = self._post(
            WORK_ITEM_SEARCH_PATH,
            provider_request,
            headers={
                PROVIDER_HEADERS["token"]: principal.credential.secrets.token,
                PROVIDER_HEADERS["user"]: principal.provider_user_id,
            },
        )
        output = self._parse_search(payload, limit=int(arguments["limit"]))
        return provider_request, payload, output

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        assert_external_io_allowed("ones_mcp.provider")
        request = Request(
            self.target.base_url + path,
            data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            headers={"Accept": "application/json", "Content-Type": "application/json", **headers},
            method="POST",
        )
        try:
            if self._open_response is not None:
                response = self._open_response(request, float(self.timeout_seconds))
            else:
                response = self._opener.open(request, timeout=float(self.timeout_seconds))
            with response:
                if int(getattr(response, "status", 200)) != 200:
                    raise self._status_error(int(response.status))
                raw = response.read(self.max_response_bytes + 1)
        except HTTPError as exc:
            raise self._status_error(int(exc.code)) from None
        except (URLError, TimeoutError, socket.timeout, OSError):
            raise RetryableExecutionError(
                "ONES Provider request failed",
                safe_message="ONES 查询暂时不可用",
                error_code="ones_provider_unavailable",
            ) from None
        if len(raw) > self.max_response_bytes:
            raise self._invalid_response("ones_provider_response_too_large")
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise self._invalid_response("ones_provider_response_invalid") from None
        if not isinstance(parsed, dict):
            raise self._invalid_response("ones_provider_response_invalid")
        McpOperationAuditRepository._reject_secret_fields(parsed)
        return parsed

    @staticmethod
    def _parse_search(payload: dict[str, Any], *, limit: int) -> dict[str, Any]:
        if set(payload) != {"data"} or not isinstance(payload.get("data"), dict):
            raise OnesProviderClient._invalid_response("ones_provider_schema_invalid")
        data = payload["data"]
        if set(data) != {"workItems"} or not isinstance(data.get("workItems"), dict):
            raise OnesProviderClient._invalid_response("ones_provider_schema_invalid")
        work_items = data["workItems"]
        if set(work_items) != {"items", "total", "truncated"}:
            raise OnesProviderClient._invalid_response("ones_provider_schema_invalid")
        items = work_items.get("items")
        total = work_items.get("total")
        truncated = work_items.get("truncated")
        if (
            not isinstance(items, list)
            or len(items) > limit
            or type(total) is not int
            or total < 0
            or type(truncated) is not bool
        ):
            raise OnesProviderClient._invalid_response("ones_provider_schema_invalid")
        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict) or set(item) != {"number", "name", "type"}:
                raise OnesProviderClient._invalid_response("ones_provider_schema_invalid")
            if (
                type(item.get("number")) is not int
                or not isinstance(item.get("name"), str)
                or len(item["name"]) > 500
                or item.get("type") not in ISSUE_TYPES
            ):
                raise OnesProviderClient._invalid_response("ones_provider_schema_invalid")
            normalized.append(dict(item))
        return {
            "items": normalized,
            "total": total,
            "truncated": truncated,
            "untrusted_data": True,
        }

    @staticmethod
    def _status_error(status: int) -> AppError:
        if status == 401:
            return OnesProviderUnauthorized(
                "ONES Provider rejected its current Token",
                safe_message="ONES 登录状态已失效",
                error_code="ones_provider_unauthorized",
            )
        if status == 403:
            return OnesMcpError(
                "ONES Provider denied Team access",
                safe_message="当前 ONES 身份无权访问该 Team",
                error_code="ones_provider_forbidden",
            )
        if status == 429:
            return RetryableExecutionError(
                "ONES Provider rate limited the request",
                safe_message="ONES 查询过于频繁，请稍后重试",
                error_code="ones_provider_rate_limited",
            )
        if 300 <= status < 400:
            return OnesMcpError(
                "ONES Provider redirect was rejected",
                safe_message="ONES 返回了无效重定向",
                error_code="ones_provider_redirect_rejected",
            )
        if status >= 500:
            return RetryableExecutionError(
                "ONES Provider is unavailable",
                safe_message="ONES 查询暂时不可用",
                error_code="ones_provider_unavailable",
            )
        return OnesMcpError(
            "ONES Provider returned an unsupported status",
            safe_message="ONES 返回了无效响应",
            error_code="ones_provider_response_invalid",
        )

    @staticmethod
    def _invalid_response(error_code: str) -> OnesMcpError:
        return OnesMcpError(
            "ONES Provider response did not match the fixed schema",
            safe_message="ONES 返回了无效业务数据",
            error_code=error_code,
        )


class OnesWorkItemSearchService:
    def __init__(
        self,
        resolver: OnesPrincipalResolver,
        provider: OnesProviderClient,
        login_verifier: OnesIdentityVerifier,
        credentials: ExternalIdentityCredentialRepository,
        audit: McpOperationAuditRepository,
    ) -> None:
        self.resolver = resolver
        self.provider = provider
        self.login_verifier = login_verifier
        self.credentials = credentials
        self.audit = audit
        self._locks_guard = threading.Lock()
        self._credential_locks: dict[str, threading.Lock] = {}

    def authenticate(self, token: str) -> dict[str, Any]:
        return self.resolver.authenticate(token)

    def search(
        self,
        *,
        claims: dict[str, Any],
        arguments: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        tool_request = self._validate_arguments(arguments)
        principal = self.resolver.resolve(claims)
        audit_context = AuditContext(
            correlation_id=(correlation_id.strip() or f"job:{principal.job_id}")[:128],
            principal=principal,
        )
        started = time.monotonic()
        try:
            output = self._search_with_refresh(
                claims=claims,
                context=audit_context,
                tool_request=tool_request,
            )
            self.audit.record(
                audit_context,
                operation="read",
                event_kind="TOOL",
                attempt=0,
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                tool_request=tool_request,
                tool_response=output,
            )
            return output
        except AppError as exc:
            if getattr(exc, "error_code", "") != "mcp_audit_unavailable":
                self.audit.record(
                    audit_context,
                    operation="read",
                    event_kind="TOOL",
                    attempt=0,
                    status="FAILED",
                    error_code=str(getattr(exc, "error_code", "") or "ones_mcp_failed"),
                    duration_ms=int((time.monotonic() - started) * 1000),
                    tool_request=tool_request,
                )
            raise

    def _search_with_refresh(
        self,
        *,
        claims: dict[str, Any],
        context: AuditContext,
        tool_request: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return self._provider_attempt(context, tool_request, attempt=0)
        except OnesProviderUnauthorized:
            pass
        original_revision = context.principal.credential.revision
        lock = self._lock_for(context.principal.credential.id)
        with lock:
            current = self.resolver.resolve(claims)
            if current.credential.revision == original_revision:
                self._refresh_credential(context, current)
            refreshed = self.resolver.resolve(claims)
        retry_context = AuditContext(context.correlation_id, refreshed)
        try:
            output = self._provider_attempt(retry_context, tool_request, attempt=1)
        except OnesProviderUnauthorized:
            self.credentials.mark_reauth_required(
                credential_id=refreshed.credential.id,
                expected_revision=refreshed.credential.revision,
                error_code="ones_provider_unauthorized_after_refresh",
            )
            self.audit.record(
                retry_context,
                operation="credential_refresh",
                event_kind="CREDENTIAL",
                attempt=1,
                status="FAILED",
                error_code="ones_provider_unauthorized_after_refresh",
            )
            raise OnesMcpError(
                "ONES Provider rejected the refreshed Token",
                safe_message="ONES 身份需要本人重新验证",
                error_code="ones_credential_reverification_required",
            ) from None
        self.credentials.mark_used(
            credential_id=refreshed.credential.id,
            expected_revision=refreshed.credential.revision,
        )
        return output

    def _provider_attempt(
        self,
        context: AuditContext,
        tool_request: dict[str, Any],
        *,
        attempt: int,
    ) -> dict[str, Any]:
        started = time.monotonic()
        provider_request = {
            "query": WORK_ITEM_SEARCH_DOCUMENT,
            "variables": {
                **tool_request,
                "user_id": context.principal.provider_user_id,
                "team_id": context.principal.team_id,
            },
        }
        try:
            actual_request, provider_response, output = self.provider.search(
                context.principal,
                tool_request,
            )
            self.audit.record(
                context,
                operation="read",
                event_kind="PROVIDER",
                attempt=attempt,
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                tool_request=tool_request,
                provider_request=actual_request,
                provider_response=provider_response,
                tool_response=output,
            )
            if attempt == 0:
                self.credentials.mark_used(
                    credential_id=context.principal.credential.id,
                    expected_revision=context.principal.credential.revision,
                )
            return output
        except AppError as exc:
            self.audit.record(
                context,
                operation="read",
                event_kind="PROVIDER",
                attempt=attempt,
                status="FAILED",
                error_code=str(getattr(exc, "error_code", "") or "ones_provider_failed"),
                duration_ms=int((time.monotonic() - started) * 1000),
                tool_request=tool_request,
                provider_request=provider_request,
            )
            raise

    def _refresh_credential(
        self,
        context: AuditContext,
        principal: ResolvedOnesPrincipal,
    ) -> None:
        started = time.monotonic()
        try:
            verified = self.login_verifier.verify(
                email=principal.credential.secrets.email,
                password=principal.credential.secrets.password,
            )
            if (
                verified.user_uuid != principal.provider_user_id
                or principal.team_id not in verified.team_uuids
            ):
                raise OnesMcpError(
                    "ONES login identity or Team changed",
                    safe_message="ONES 身份信息已变化，请本人重新验证",
                    error_code="ones_credential_identity_changed",
                )
            rotated = self.credentials.rotate_token(
                credential_id=principal.credential.id,
                expected_revision=principal.credential.revision,
                token=verified.token,
            )
            refreshed_context = AuditContext(
                context.correlation_id,
                replace(
                    principal,
                    credential=self.credentials.resolve_active(principal.credential.id),
                ),
            )
            self.audit.record(
                refreshed_context,
                operation="credential_refresh",
                event_kind="CREDENTIAL",
                attempt=0,
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                tool_request={
                    "provider_email": principal.provider_email,
                    "provider_user_id": principal.provider_user_id,
                    "previous_revision": principal.credential.revision,
                    "revision": int(rotated["revision"]),
                },
            )
        except AppError as exc:
            if getattr(exc, "error_code", "") == "mcp_audit_unavailable":
                raise
            try:
                self.credentials.mark_reauth_required(
                    credential_id=principal.credential.id,
                    expected_revision=principal.credential.revision,
                    error_code=str(
                        getattr(exc, "error_code", "") or "ones_credential_refresh_failed"
                    ),
                )
            except AppError:
                pass
            self.audit.record(
                context,
                operation="credential_refresh",
                event_kind="CREDENTIAL",
                attempt=0,
                status="FAILED",
                error_code=str(getattr(exc, "error_code", "") or "ones_credential_refresh_failed"),
                duration_ms=int((time.monotonic() - started) * 1000),
                tool_request={
                    "provider_email": principal.provider_email,
                    "provider_user_id": principal.provider_user_id,
                    "revision": principal.credential.revision,
                },
            )
            raise OnesMcpError(
                "ONES credential refresh failed",
                safe_message="ONES 身份需要本人重新验证",
                error_code="ones_credential_reverification_required",
            ) from exc

    @staticmethod
    def _validate_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, dict) or set(arguments) != {
            "keyword",
            "issue_type",
            "limit",
        }:
            raise OnesMcpError(
                "ONES Tool input fields are invalid",
                safe_message="ONES 查询参数无效",
                error_code="ones_tool_input_invalid",
            )
        keyword = arguments.get("keyword")
        issue_type = arguments.get("issue_type")
        limit = arguments.get("limit")
        if (
            not isinstance(keyword, str)
            or not 1 <= len(keyword) <= 200
            or issue_type not in ISSUE_TYPES
            or type(limit) is not int
            or not 1 <= limit <= 50
        ):
            raise OnesMcpError(
                "ONES Tool input values are invalid",
                safe_message="ONES 查询参数无效",
                error_code="ones_tool_input_invalid",
            )
        return {"keyword": keyword, "issue_type": issue_type, "limit": limit}

    def _lock_for(self, credential_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._credential_locks.setdefault(credential_id, threading.Lock())


assert REQUIRED_SCOPE == ONES_SEARCH_SCOPE
assert ONES_SEARCH_TOOL == TOOL_IDENTIFIER
assert LOGIN_PATH.endswith("/auth/login")
