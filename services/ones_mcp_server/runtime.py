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
from app.modules.mcp_audit import McpAuditContext, McpAuditCoordinator, McpAuditHandle
from app.modules.mcp_tool_runtime.job_snapshot import JobMcpToolSnapshotService
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.database import Database, assert_external_io_allowed
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


class OnesSearchResult(dict[str, Any]):
    def __init__(self, payload: dict[str, Any], audit_handle: McpAuditHandle) -> None:
        super().__init__(payload)
        self.audit_handle = audit_handle


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

    def audit_context(
        self,
        claims: dict[str, Any],
        *,
        invocation_id: str,
        correlation_id: str,
    ) -> McpAuditContext:
        job = self.database.execute_one(
            """
            select id, session_id, retry_count, internal_user_id,
                   agent_publication_id, business_application_publication_id
              from agent_job
             where id = ? and status = 'RUNNING'
            """,
            (claims["job_id"],),
        )
        if job is None or str(job["internal_user_id"]) != str(claims["sub"]):
            raise self._denied("ones_principal_provenance_mismatch")
        expected_invocation_id = f"{job['id']}.attempt-{int(job['retry_count'])}"
        effective_invocation_id = invocation_id or expected_invocation_id
        if (
            effective_invocation_id != expected_invocation_id
            or str(job["session_id"]) != str(claims["session_id"])
            or str(job["agent_publication_id"]) != str(claims["agent_publication_id"])
            or str(job["business_application_publication_id"])
            != str(claims["application_publication_id"])
        ):
            raise self._denied("ones_principal_provenance_mismatch")
        definition = MCP_TOOL_MANIFEST[TOOL_IDENTIFIER]
        return McpAuditContext(
            correlation_id=(correlation_id.strip() or f"job:{job['id']}")[:128],
            job_id=str(job["id"]),
            session_id=str(job["session_id"]),
            invocation_id=effective_invocation_id,
            actor_user_id=str(claims["sub"]),
            server_code=SERVER_CODE,
            tool_identifier=TOOL_IDENTIFIER,
            tool_schema_hash=definition.schema_hash,
            agent_publication_id=str(job["agent_publication_id"]),
            application_publication_id=str(job["business_application_publication_id"]),
            provider="ones",
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
        McpAuditCoordinator.reject_auth_material(parsed)
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
        audit: McpAuditCoordinator,
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
        invocation_id: str = "",
    ) -> OnesSearchResult:
        tool_request = self._validate_arguments(arguments)
        base_context = self.resolver.audit_context(
            claims,
            invocation_id=invocation_id,
            correlation_id=correlation_id,
        )
        handle = self.audit.begin(
            base_context,
            business_request=tool_request,
        )
        started = time.monotonic()
        authorization_persisted = False
        try:
            principal = self.resolver.resolve(claims)
            handle = self.audit.enrich_context(
                handle,
                replace(
                    base_context,
                    principal_jti=principal.principal_jti,
                    external_identity_id=principal.external_identity_id,
                    credential_id=principal.credential.id,
                    credential_revision=principal.credential.revision,
                    provider="ones",
                    team_id=principal.team_id,
                    provider_email=principal.provider_email,
                    provider_user_id=principal.provider_user_id,
                ),
            )
            self.audit.append_event(
                handle,
                event_kind="AUTHORIZATION",
                status="SUCCEEDED",
                authorization_decision="ALLOW",
                authorization_reason="principal_identity_and_scope_allowed",
                business_request={"stage": "ones_principal_resolve"},
            )
            authorization_persisted = True
            output = self._search_with_refresh(
                claims=claims,
                handle=handle,
                principal=principal,
                tool_request=tool_request,
            )
            self.audit.complete(
                handle,
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                business_response=output,
            )
            return OnesSearchResult(output, handle)
        except AppError as exc:
            setattr(exc, "mcp_audit_handle", handle)
            if getattr(exc, "error_code", "") == "mcp_audit_unavailable":
                raise
            if not authorization_persisted:
                self.audit.append_event(
                    handle,
                    event_kind="AUTHORIZATION",
                    status="DENIED",
                    error_code=_error_code(exc),
                    authorization_decision="DENY",
                    authorization_reason=_error_code(exc),
                    business_request={"stage": "ones_principal_resolve"},
                )
            self.audit.complete(
                handle,
                status="DENIED" if not authorization_persisted else "FAILED",
                error_code=_error_code(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
                business_response={
                    "error": str(exc.safe_message),
                    "error_code": _error_code(exc),
                },
            )
            raise

    def _search_with_refresh(
        self,
        *,
        claims: dict[str, Any],
        handle: McpAuditHandle,
        principal: ResolvedOnesPrincipal,
        tool_request: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return self._provider_attempt(handle, principal, tool_request, attempt=0)
        except OnesProviderUnauthorized:
            pass
        original_revision = principal.credential.revision
        lock = self._lock_for(principal.credential.id)
        with lock:
            current = self.resolver.resolve(claims)
            if current.credential.revision == original_revision:
                self._refresh_credential(handle, current)
            refreshed = self.resolver.resolve(claims)
        try:
            output = self._provider_attempt(handle, refreshed, tool_request, attempt=1)
        except OnesProviderUnauthorized:
            self.credentials.mark_reauth_required(
                credential_id=refreshed.credential.id,
                expected_revision=refreshed.credential.revision,
                error_code="ones_provider_unauthorized_after_refresh",
            )
            self.audit.append_event(
                handle,
                event_kind="CREDENTIAL",
                attempt=1,
                status="FAILED",
                error_code="ones_provider_unauthorized_after_refresh",
                credential_revision=refreshed.credential.revision,
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
        handle: McpAuditHandle,
        principal: ResolvedOnesPrincipal,
        tool_request: dict[str, Any],
        *,
        attempt: int,
    ) -> dict[str, Any]:
        started = time.monotonic()
        provider_request = {
            "query": WORK_ITEM_SEARCH_DOCUMENT,
            "variables": {
                **tool_request,
                "user_id": principal.provider_user_id,
                "team_id": principal.team_id,
            },
        }
        try:
            actual_request, provider_response, output = self.provider.search(
                principal,
                tool_request,
            )
            self.audit.append_event(
                handle,
                event_kind="PROVIDER",
                attempt=attempt,
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                business_request=actual_request,
                business_response={"provider_response": provider_response, "tool": output},
                credential_revision=principal.credential.revision,
            )
            if attempt == 0:
                self.credentials.mark_used(
                    credential_id=principal.credential.id,
                    expected_revision=principal.credential.revision,
                )
            return output
        except AppError as exc:
            self.audit.append_event(
                handle,
                event_kind="PROVIDER",
                attempt=attempt,
                status="FAILED",
                error_code=str(getattr(exc, "error_code", "") or "ones_provider_failed"),
                duration_ms=int((time.monotonic() - started) * 1000),
                business_request=provider_request,
                credential_revision=principal.credential.revision,
            )
            raise

    def _refresh_credential(
        self,
        handle: McpAuditHandle,
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
            self.audit.append_event(
                handle,
                event_kind="CREDENTIAL",
                attempt=0,
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                business_request={
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
            self.audit.append_event(
                handle,
                event_kind="CREDENTIAL",
                attempt=0,
                status="FAILED",
                error_code=str(getattr(exc, "error_code", "") or "ones_credential_refresh_failed"),
                duration_ms=int((time.monotonic() - started) * 1000),
                business_request={
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


def _error_code(exc: Exception) -> str:
    return str(getattr(exc, "error_code", "") or "ones_mcp_failed")[:128]


assert REQUIRED_SCOPE == ONES_SEARCH_SCOPE
assert ONES_SEARCH_TOOL == TOOL_IDENTIFIER
assert LOGIN_PATH.endswith("/auth/login")
