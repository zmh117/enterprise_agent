from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from app.modules.audit.application.audit_service import AuditService
from app.modules.job.infrastructure.repositories import new_id, now_iso
from app.shared.database import Database, operation_unit_of_work
from app.shared.exceptions import NonRetryableExecutionError


MCP_CALL_ID_META_KEY = "enterprise-agent/mcp-call-id"
MCP_AGENT_TOOL_CALL_ID_META_KEY = "enterprise-agent/agent-tool-call-id"
logger = logging.getLogger(__name__)
_EVENT_KINDS = frozenset({"AUTHORIZATION", "RESOURCE", "PROVIDER", "CREDENTIAL"})
_TERMINAL_STATUSES = frozenset({"SUCCEEDED", "FAILED", "DENIED"})
_MCP_AUDIT_COLUMNS = (
    "id",
    "mcp_call_id",
    "parent_audit_id",
    "correlation_id",
    "job_id",
    "session_id",
    "invocation_id",
    "agent_publication_id",
    "application_publication_id",
    "principal_jti",
    "actor_user_id",
    "actor_type",
    "external_identity_id",
    "credential_id",
    "credential_revision",
    "provider",
    "team_id",
    "provider_email",
    "provider_user_id",
    "server_code",
    "tool_identifier",
    "tool_schema_hash",
    "operation",
    "event_kind",
    "attempt",
    "status",
    "error_code",
    "duration_ms",
    "authorization_decision",
    "authorization_reason",
    "resource_code",
    "resource_deployment_id",
    "resource_revision_id",
    "resource_placement",
    "target_type",
    "target_id",
    "target_name",
    "payload_schema_version",
    "tool_request_json",
    "provider_request_json",
    "provider_response_json",
    "tool_response_json",
    "business_request_json",
    "business_response_json",
    "request_truncated",
    "response_truncated",
    "payload_digest",
    "legacy_link_status",
    "audit_event_id",
    "agent_tool_call_id",
    "created_at",
    "completed_at",
)
_FORBIDDEN_AUTH_KEYS = frozenset(
    {
        "authorization",
        "proxy_authorization",
        "cookie",
        "set_cookie",
        "password",
        "passwd",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "api_key",
        "secret",
        "secret_value",
        "private_key",
        "ciphertext",
        "nonce",
        "principal_jwt",
        "principal_token",
        "x_file_principal_token",
        "credential_value",
    }
)


class McpAuditError(NonRetryableExecutionError):
    pass


@dataclass(frozen=True, slots=True)
class McpAuditContext:
    correlation_id: str
    job_id: str
    session_id: str
    invocation_id: str
    actor_user_id: str
    server_code: str
    tool_identifier: str
    tool_schema_hash: str = ""
    agent_publication_id: str = ""
    application_publication_id: str = ""
    operation: str = "read"
    risk_level: str = "low"
    actor_type: Literal["user", "agent", "system"] = "user"
    principal_jti: str = ""
    external_identity_id: str = ""
    credential_id: str = ""
    credential_revision: int | None = None
    provider: str = ""
    team_id: str = ""
    provider_email: str = ""
    provider_user_id: str = ""


@dataclass(frozen=True, slots=True)
class McpAuditHandle:
    mcp_call_id: str
    agent_tool_call_id: str
    root_audit_id: str
    context: McpAuditContext

    def result_meta(self) -> dict[str, str]:
        return {
            MCP_CALL_ID_META_KEY: self.mcp_call_id,
            MCP_AGENT_TOOL_CALL_ID_META_KEY: self.agent_tool_call_id,
        }


@dataclass(frozen=True, slots=True)
class _SerializedBusinessPayload:
    text: str
    truncated: bool
    digest: str


class McpAuditCoordinator:
    """Own one exact Agent Tool fact and its detailed MCP evidence tree."""

    def __init__(
        self,
        database: Database,
        *,
        max_payload_bytes: int,
        audit_service: AuditService | None = None,
    ) -> None:
        if not 1024 <= max_payload_bytes <= 1024 * 1024:
            raise ValueError("MCP audit payload limit is invalid")
        self.database = database
        self.max_payload_bytes = max_payload_bytes
        self.audit_service = audit_service

    def begin(
        self,
        context: McpAuditContext,
        *,
        business_request: dict[str, Any],
    ) -> McpAuditHandle:
        self._validate_context(context)
        request = self._serialize(business_request)
        mcp_call_id = new_id("mcp_call")
        agent_tool_call_id = new_id("tool")
        root_audit_id = new_id("mcp_audit")
        try:
            return self._begin(
                context,
                request=request,
                mcp_call_id=mcp_call_id,
                agent_tool_call_id=agent_tool_call_id,
                root_audit_id=root_audit_id,
            )
        except McpAuditError:
            raise
        except Exception as exc:
            self._log_failure(exc)
            raise self._unavailable() from exc

    @operation_unit_of_work(lambda coordinator: coordinator.database)
    def _begin(
        self,
        context: McpAuditContext,
        *,
        request: _SerializedBusinessPayload,
        mcp_call_id: str,
        agent_tool_call_id: str,
        root_audit_id: str,
    ) -> McpAuditHandle:
        audit_event_id = (
            self.audit_service.record(
                "mcp.operation.started",
                status="STARTED",
                summary="MCP Tool Call root facts persisted",
                job_id=context.job_id,
                actor_id=context.actor_user_id,
                payload={
                    "mcp_call_id": mcp_call_id,
                    "agent_tool_call_id": agent_tool_call_id,
                    "server_code": context.server_code,
                    "tool_identifier": context.tool_identifier,
                    "invocation_id": context.invocation_id,
                },
            )
            if self.audit_service is not None
            else None
        )
        timestamp = now_iso()
        self.database.execute(
            """
            insert into agent_tool_call
              (id, job_id, tool_name, request_payload, response_summary, status,
               duration_ms, risk_level, audit_id, created_at, invocation_id,
               runtime_tool_call_id, tool_origin, server_code, mcp_call_id,
               persisted_by)
            values (?, ?, ?, ?, '{}', 'STARTED', 0, ?, ?, ?, ?, NULL,
                    'mcp', ?, ?, 'mcp_server')
            """,
            (
                agent_tool_call_id,
                context.job_id,
                context.tool_identifier,
                request.text,
                context.risk_level,
                audit_event_id,
                timestamp,
                context.invocation_id,
                context.server_code,
                mcp_call_id,
            ),
        )
        self._insert_audit_row(
            {
                **self._context_values(context),
                "id": root_audit_id,
                "mcp_call_id": mcp_call_id,
                "parent_audit_id": None,
                "event_kind": "TOOL",
                "attempt": 0,
                "status": "STARTED",
                "error_code": "",
                "duration_ms": 0,
                "authorization_decision": "",
                "authorization_reason": "",
                "resource_code": None,
                "resource_deployment_id": None,
                "resource_revision_id": None,
                "resource_placement": None,
                "target_type": "",
                "target_id": "",
                "target_name": "",
                "payload_schema_version": 2,
                "tool_request_json": request.text,
                "provider_request_json": "{}",
                "provider_response_json": "{}",
                "tool_response_json": "{}",
                "business_request_json": request.text,
                "business_response_json": "{}",
                "request_truncated": int(request.truncated),
                "response_truncated": 0,
                "payload_digest": request.digest,
                "legacy_link_status": "LINKED",
                "audit_event_id": audit_event_id,
                "agent_tool_call_id": agent_tool_call_id,
                "created_at": timestamp,
                "completed_at": None,
            }
        )
        return McpAuditHandle(
            mcp_call_id=mcp_call_id,
            agent_tool_call_id=agent_tool_call_id,
            root_audit_id=root_audit_id,
            context=context,
        )

    def append_event(
        self,
        handle: McpAuditHandle,
        *,
        event_kind: Literal["AUTHORIZATION", "RESOURCE", "PROVIDER", "CREDENTIAL"],
        status: Literal["STARTED", "SUCCEEDED", "FAILED", "DENIED"],
        attempt: int = 0,
        error_code: str = "",
        duration_ms: int = 0,
        business_request: dict[str, Any] | None = None,
        business_response: dict[str, Any] | None = None,
        authorization_decision: str = "",
        authorization_reason: str = "",
        resource_code: str = "",
        resource_deployment_id: str = "",
        resource_revision_id: str = "",
        resource_placement: str = "",
        target_type: str = "",
        target_id: str = "",
        target_name: str = "",
        credential_revision: int | None = None,
    ) -> str:
        if event_kind not in _EVENT_KINDS or status not in _TERMINAL_STATUSES | {"STARTED"}:
            raise ValueError("MCP audit event kind or status is invalid")
        try:
            request = self._serialize(business_request or {})
            response = self._serialize(business_response or {})
            return self._append_event(
                handle,
                event_kind=event_kind,
                status=status,
                attempt=max(0, attempt),
                error_code=error_code[:128],
                duration_ms=max(0, duration_ms),
                request=request,
                response=response,
                authorization_decision=authorization_decision[:32],
                authorization_reason=authorization_reason[:512],
                resource_code=resource_code[:128],
                resource_deployment_id=resource_deployment_id[:128],
                resource_revision_id=resource_revision_id[:128],
                resource_placement=resource_placement[:16],
                target_type=target_type[:128],
                target_id=target_id[:256],
                target_name=target_name[:512],
                credential_revision=credential_revision,
            )
        except McpAuditError as exc:
            setattr(exc, "mcp_audit_handle", handle)
            raise
        except Exception as exc:
            self._log_failure(exc)
            unavailable = self._unavailable()
            setattr(unavailable, "mcp_audit_handle", handle)
            raise unavailable from exc

    def enrich_context(
        self,
        handle: McpAuditHandle,
        context: McpAuditContext,
    ) -> McpAuditHandle:
        immutable_fields = (
            "correlation_id",
            "job_id",
            "session_id",
            "invocation_id",
            "actor_user_id",
            "server_code",
            "tool_identifier",
        )
        if any(
            getattr(handle.context, field) != getattr(context, field) for field in immutable_fields
        ):
            conflict = McpAuditError(
                "MCP audit context enrichment changed an immutable identity",
                safe_message="MCP 操作审计上下文不一致",
                error_code="mcp_audit_context_conflict",
            )
            setattr(conflict, "mcp_audit_handle", handle)
            raise conflict
        try:
            self._enrich_context(handle, context)
        except McpAuditError as exc:
            setattr(exc, "mcp_audit_handle", handle)
            raise
        except Exception as exc:
            self._log_failure(exc)
            unavailable = self._unavailable()
            setattr(unavailable, "mcp_audit_handle", handle)
            raise unavailable from exc
        return McpAuditHandle(
            mcp_call_id=handle.mcp_call_id,
            agent_tool_call_id=handle.agent_tool_call_id,
            root_audit_id=handle.root_audit_id,
            context=context,
        )

    @operation_unit_of_work(lambda coordinator: coordinator.database)
    def _enrich_context(
        self,
        handle: McpAuditHandle,
        context: McpAuditContext,
    ) -> None:
        changed = self.database.execute(
            """
            update mcp_operation_audit
               set principal_jti = ?, external_identity_id = ?, credential_id = ?,
                   credential_revision = ?, provider = ?, team_id = ?,
                   provider_email = ?, provider_user_id = ?
             where id = ? and mcp_call_id = ? and status = 'STARTED'
            returning id
            """,
            (
                context.principal_jti or None,
                context.external_identity_id or None,
                context.credential_id or None,
                context.credential_revision,
                context.provider or None,
                context.team_id or None,
                context.provider_email or None,
                context.provider_user_id or None,
                handle.root_audit_id,
                handle.mcp_call_id,
            ),
        )
        if not changed:
            raise McpAuditError(
                "MCP audit root cannot be enriched",
                safe_message="MCP 操作审计根事实不可更新",
                error_code="mcp_audit_conflict",
            )

    @operation_unit_of_work(lambda coordinator: coordinator.database)
    def _append_event(
        self,
        handle: McpAuditHandle,
        **values: Any,
    ) -> str:
        existing = self.database.execute_one(
            """
            select id, status from mcp_operation_audit
             where mcp_call_id = ? and event_kind = ? and attempt = ?
            """,
            (handle.mcp_call_id, values["event_kind"], values["attempt"]),
        )
        if existing is not None:
            if str(existing["status"]) == values["status"]:
                return str(existing["id"])
            raise McpAuditError(
                "MCP audit child event has a conflicting terminal state",
                safe_message="MCP 操作审计状态冲突",
                error_code="mcp_audit_conflict",
            )
        context = handle.context
        request: _SerializedBusinessPayload = values["request"]
        response: _SerializedBusinessPayload = values["response"]
        event_id = new_id("mcp_audit")
        timestamp = now_iso()
        digest = hashlib.sha256(f"{request.digest}:{response.digest}".encode("ascii")).hexdigest()
        self._insert_audit_row(
            {
                **self._context_values(context),
                "id": event_id,
                "mcp_call_id": handle.mcp_call_id,
                "parent_audit_id": handle.root_audit_id,
                "credential_revision": values["credential_revision"]
                if values["credential_revision"] is not None
                else context.credential_revision,
                "event_kind": values["event_kind"],
                "attempt": values["attempt"],
                "status": values["status"],
                "error_code": values["error_code"],
                "duration_ms": values["duration_ms"],
                "authorization_decision": values["authorization_decision"],
                "authorization_reason": values["authorization_reason"],
                "resource_code": values["resource_code"] or None,
                "resource_deployment_id": values["resource_deployment_id"] or None,
                "resource_revision_id": values["resource_revision_id"] or None,
                "resource_placement": values["resource_placement"] or None,
                "target_type": values["target_type"],
                "target_id": values["target_id"],
                "target_name": values["target_name"],
                "payload_schema_version": 2,
                "tool_request_json": "{}",
                "provider_request_json": request.text
                if values["event_kind"] == "PROVIDER"
                else "{}",
                "provider_response_json": response.text
                if values["event_kind"] == "PROVIDER"
                else "{}",
                "tool_response_json": "{}",
                "business_request_json": request.text,
                "business_response_json": response.text,
                "request_truncated": int(request.truncated),
                "response_truncated": int(response.truncated),
                "payload_digest": digest,
                "legacy_link_status": "LINKED",
                "audit_event_id": None,
                "agent_tool_call_id": handle.agent_tool_call_id,
                "created_at": timestamp,
                "completed_at": timestamp if values["status"] in _TERMINAL_STATUSES else None,
            }
        )
        return event_id

    def _insert_audit_row(self, values: dict[str, Any]) -> None:
        if set(values) != set(_MCP_AUDIT_COLUMNS):
            missing = sorted(set(_MCP_AUDIT_COLUMNS) - set(values))
            extra = sorted(set(values) - set(_MCP_AUDIT_COLUMNS))
            raise ValueError(f"MCP audit row shape is invalid missing={missing} extra={extra}")
        columns = ", ".join(_MCP_AUDIT_COLUMNS)
        placeholders = ", ".join("?" for _ in _MCP_AUDIT_COLUMNS)
        self.database.execute(
            f"insert into mcp_operation_audit ({columns}) values ({placeholders})",
            tuple(values[column] for column in _MCP_AUDIT_COLUMNS),
        )

    @staticmethod
    def _context_values(context: McpAuditContext) -> dict[str, Any]:
        return {
            "correlation_id": context.correlation_id,
            "job_id": context.job_id,
            "session_id": context.session_id,
            "invocation_id": context.invocation_id or None,
            "agent_publication_id": context.agent_publication_id or None,
            "application_publication_id": context.application_publication_id or None,
            "principal_jti": context.principal_jti or None,
            "actor_user_id": context.actor_user_id,
            "actor_type": context.actor_type,
            "external_identity_id": context.external_identity_id or None,
            "credential_id": context.credential_id or None,
            "credential_revision": context.credential_revision,
            "provider": context.provider or None,
            "team_id": context.team_id or None,
            "provider_email": context.provider_email or None,
            "provider_user_id": context.provider_user_id or None,
            "server_code": context.server_code,
            "tool_identifier": context.tool_identifier,
            "tool_schema_hash": context.tool_schema_hash,
            "operation": context.operation,
        }

    def complete(
        self,
        handle: McpAuditHandle,
        *,
        status: Literal["SUCCEEDED", "FAILED", "DENIED"],
        business_response: dict[str, Any],
        duration_ms: int,
        error_code: str = "",
    ) -> None:
        if status not in _TERMINAL_STATUSES:
            raise ValueError("MCP audit completion status is invalid")
        try:
            response = self._serialize(business_response)
            self._complete(
                handle,
                status=status,
                response=response,
                duration_ms=max(0, duration_ms),
                error_code=error_code[:128],
            )
        except McpAuditError as exc:
            setattr(exc, "mcp_audit_handle", handle)
            raise
        except Exception as exc:
            self._log_failure(exc)
            unavailable = self._unavailable()
            setattr(unavailable, "mcp_audit_handle", handle)
            raise unavailable from exc

    @operation_unit_of_work(lambda coordinator: coordinator.database)
    def _complete(
        self,
        handle: McpAuditHandle,
        *,
        status: str,
        response: _SerializedBusinessPayload,
        duration_ms: int,
        error_code: str,
    ) -> None:
        current = self.database.execute_one(
            """
            select a.status as tool_status, m.status as audit_status
              from agent_tool_call a
              join mcp_operation_audit m
                on m.agent_tool_call_id = a.id and m.id = ?
             where a.id = ? and a.mcp_call_id = ?
            """,
            (handle.root_audit_id, handle.agent_tool_call_id, handle.mcp_call_id),
        )
        if current is None:
            raise McpAuditError(
                "MCP audit root facts are missing",
                safe_message="MCP 操作审计关联缺失",
                error_code="mcp_audit_link_missing",
            )
        if str(current["tool_status"]) != "STARTED" or str(current["audit_status"]) != "STARTED":
            if str(current["tool_status"]) == status and str(current["audit_status"]) == status:
                return
            raise McpAuditError(
                "MCP audit completion has a conflicting terminal state",
                safe_message="MCP 操作审计状态冲突",
                error_code="mcp_audit_conflict",
            )
        timestamp = now_iso()
        self.database.execute(
            """
            update agent_tool_call
               set response_summary = ?, status = ?, duration_ms = ?
             where id = ? and status = 'STARTED'
            """,
            (response.text, status, duration_ms, handle.agent_tool_call_id),
        )
        self.database.execute(
            """
            update mcp_operation_audit
               set status = ?, error_code = ?, duration_ms = ?,
                   tool_response_json = ?, business_response_json = ?,
                   response_truncated = ?, payload_digest = ?, completed_at = ?
             where id = ? and status = 'STARTED'
            """,
            (
                status,
                error_code,
                duration_ms,
                response.text,
                response.text,
                int(response.truncated),
                response.digest,
                timestamp,
                handle.root_audit_id,
            ),
        )

    @operation_unit_of_work(lambda coordinator: coordinator.database)
    def purge_expired(self, *, retention_days: int, batch_size: int = 500) -> int:
        if not 1 <= retention_days <= 3650 or not 1 <= batch_size <= 5000:
            raise ValueError("MCP audit retention bounds are invalid")
        rows = self.database.execute(
            """
            select id from mcp_operation_audit
             where parent_audit_id is null
               and created_at < ?
             order by created_at, id
             limit ?
            """,
            (_retention_cutoff(retention_days), batch_size),
        )
        for row in rows:
            self.database.execute(
                "delete from mcp_operation_audit where id = ?",
                (str(row["id"]),),
            )
        return len(rows)

    def assert_ready(self) -> None:
        try:
            row = self.database.execute_one(
                """
                select count(*) as column_count
                  from pragma_table_info('mcp_operation_audit')
                 where name in ('mcp_call_id', 'parent_audit_id',
                                'business_request_json', 'completed_at')
                """
                if self.database.engine == "sqlite"
                else """
                select count(*) as column_count
                  from information_schema.columns
                 where table_schema = current_schema()
                   and table_name = 'mcp_operation_audit'
                   and column_name in ('mcp_call_id', 'parent_audit_id',
                                       'business_request_json', 'completed_at')
                """
            )
            if row is None or int(row["column_count"]) != 4:
                raise ValueError("MCP audit schema is not current")
            self.database.execute_one("select 1 as ready from agent_tool_call where 1 = 0")
            if self.database.engine == "postgres":
                privileges = {
                    "agent_tool_call": ("SELECT", "INSERT", "UPDATE"),
                    "mcp_operation_audit": ("SELECT", "INSERT", "UPDATE", "DELETE"),
                }
                for table, required in privileges.items():
                    for privilege in required:
                        allowed = self.database.execute_one(
                            "select has_table_privilege(current_user, ?, ?) as allowed",
                            (f"public.{table}", privilege),
                        )
                        if allowed is None or not bool(allowed["allowed"]):
                            raise ValueError(
                                f"MCP audit database grant is missing: {table}.{privilege}"
                            )
        except Exception as exc:
            self._log_failure(exc)
            raise self._unavailable() from exc

    def _serialize(self, value: dict[str, Any]) -> _SerializedBusinessPayload:
        if not isinstance(value, dict):
            raise McpAuditError(
                "MCP audit business payload must be an object",
                safe_message="MCP 操作审计载荷无效",
                error_code="mcp_audit_payload_invalid",
            )
        self._reject_auth_material(value)
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        if len(encoded) <= self.max_payload_bytes:
            return _SerializedBusinessPayload(encoded.decode("utf-8"), False, digest)
        prefix_bytes = encoded[: max(1, self.max_payload_bytes // 2)]
        while prefix_bytes:
            try:
                prefix = prefix_bytes.decode("utf-8")
                break
            except UnicodeDecodeError:
                prefix_bytes = prefix_bytes[:-1]
        else:
            prefix = ""
        bounded = json.dumps(
            {"truncated": True, "sha256": digest, "utf8_prefix": prefix},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(bounded.encode("utf-8")) > self.max_payload_bytes:
            bounded = json.dumps(
                {"truncated": True, "sha256": digest},
                separators=(",", ":"),
                sort_keys=True,
            )
        return _SerializedBusinessPayload(bounded, True, digest)

    @classmethod
    def reject_auth_material(cls, value: Any) -> None:
        cls._reject_auth_material(value)

    @classmethod
    def _reject_auth_material(cls, value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).strip().lower().replace("-", "_")
                if (
                    normalized in _FORBIDDEN_AUTH_KEYS
                    or normalized.startswith("x_mcp_principal_token_")
                    or normalized.endswith("_password")
                ):
                    raise McpAuditError(
                        "Authentication material appeared in MCP business evidence",
                        safe_message="MCP 业务数据包含禁止保存的认证材料",
                        error_code="mcp_audit_auth_material_forbidden",
                    )
                cls._reject_auth_material(child)
        elif isinstance(value, list):
            for child in value:
                cls._reject_auth_material(child)
        elif isinstance(value, str):
            parsed = urlsplit(value)
            if parsed.scheme and (parsed.username is not None or parsed.password is not None):
                raise McpAuditError(
                    "A credential-bearing URL appeared in MCP business evidence",
                    safe_message="MCP 业务数据包含带认证信息的 URL",
                    error_code="mcp_audit_auth_material_forbidden",
                )

    @staticmethod
    def _validate_context(context: McpAuditContext) -> None:
        required = (
            context.correlation_id,
            context.job_id,
            context.session_id,
            context.invocation_id,
            context.actor_user_id,
            context.server_code,
            context.tool_identifier,
        )
        if any(not str(value).strip() for value in required):
            raise McpAuditError(
                "MCP audit context is incomplete",
                safe_message="MCP 操作审计上下文不完整",
                error_code="mcp_audit_context_invalid",
            )

    @staticmethod
    def _unavailable() -> McpAuditError:
        return McpAuditError(
            "MCP operation audit could not be persisted",
            safe_message="MCP 操作审计不可用，请稍后重试",
            error_code="mcp_audit_unavailable",
        )

    @staticmethod
    def _log_failure(exc: Exception) -> None:
        logger.error(
            "MCP operation audit persistence failed safely error_type=%s",
            type(exc).__name__,
        )


def _retention_cutoff(retention_days: int) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
