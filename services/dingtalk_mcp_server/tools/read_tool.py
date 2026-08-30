from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from app.modules.mcp_audit import McpAuditCoordinator, McpAuditHandle
from app.shared.dingtalk_tool_contracts import DingTalkToolContract
from app.shared.exceptions import AppError
from app.shared.tool_contract import canonical_json
from services.dingtalk_mcp_server.auth.principal import (
    DingTalkPrincipalResolver,
    ResolvedDingTalkPrincipal,
)
from services.dingtalk_mcp_server.errors import DingTalkMcpError, error_code


MAX_TOOL_PAYLOAD_BYTES = 256 * 1024
ReadExecutor = Callable[[ResolvedDingTalkPrincipal, dict[str, Any]], dict[str, Any]]


class DingTalkToolResult(dict[str, Any]):
    def __init__(self, payload: dict[str, Any], audit_handle: McpAuditHandle) -> None:
        super().__init__(payload)
        self.audit_handle = audit_handle


class DingTalkReadToolService:
    def __init__(
        self,
        contract: DingTalkToolContract,
        resolver: DingTalkPrincipalResolver,
        audit: McpAuditCoordinator,
        executor: ReadExecutor,
    ) -> None:
        if not contract.read_only or contract.confirmation_policy != "none":
            raise ValueError("DingTalk read Tool requires a read-only contract")
        self.contract = contract
        self.resolver = resolver
        self.audit = audit
        self.executor = executor

    @property
    def tool_identifier(self) -> str:
        return self.contract.identifier

    @property
    def description(self) -> str:
        return self.contract.description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self.contract.input_schema

    @property
    def output_schema(self) -> dict[str, Any]:
        return self.contract.output_schema

    @property
    def read_only(self) -> bool:
        return self.contract.read_only

    @property
    def destructive(self) -> bool:
        return self.contract.destructive

    @property
    def idempotent(self) -> bool:
        return self.contract.idempotent

    @property
    def open_world(self) -> bool:
        return self.contract.open_world

    def authenticate(self, token: str) -> dict[str, Any]:
        return self.resolver.authenticate(token, self.contract)

    def invoke(
        self,
        *,
        claims: dict[str, Any],
        arguments: dict[str, Any],
        correlation_id: str,
        invocation_id: str,
    ) -> DingTalkToolResult:
        normalized = _validated_payload(arguments, self.contract.input_schema, kind="request")
        request_summary = _safe_payload_summary(normalized)
        context = self.resolver.audit_context(
            claims,
            self.contract,
            invocation_id=invocation_id,
            correlation_id=correlation_id,
        )
        handle = self.audit.begin(context, business_request=request_summary)
        started = time.monotonic()
        try:
            principal = self.resolver.resolve(claims, self.contract)
            self.audit.append_event(
                handle,
                event_kind="AUTHORIZATION",
                status="SUCCEEDED",
                authorization_decision="ALLOW",
                authorization_reason="principal_identity_snapshot_and_tool_grant_allowed",
                business_request={"stage": "dingtalk_principal_resolve"},
            )
            output = _validated_payload(
                self.executor(principal, normalized),
                self.contract.output_schema,
                kind="response",
            )
            self.audit.complete(
                handle,
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
                business_response=_safe_payload_summary(output),
            )
            return DingTalkToolResult(output, handle)
        except AppError as exc:
            setattr(exc, "mcp_audit_handle", handle)
            self.audit.complete(
                handle,
                status="DENIED",
                error_code=error_code(exc),
                duration_ms=int((time.monotonic() - started) * 1000),
                business_response={"error_code": error_code(exc)},
            )
            raise
        except Exception as exc:
            wrapped = DingTalkMcpError(
                "DingTalk read Tool failed safely",
                safe_message="钉钉只读查询暂时不可用",
                error_code="dingtalk_read_failed",
            )
            setattr(wrapped, "mcp_audit_handle", handle)
            self.audit.complete(
                handle,
                status="FAILED",
                error_code=wrapped.error_code,
                duration_ms=int((time.monotonic() - started) * 1000),
                business_response={"error_code": wrapped.error_code},
            )
            raise wrapped from exc


def _validated_payload(
    value: object,
    schema: dict[str, Any],
    *,
    kind: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DingTalkMcpError(
            f"DingTalk Tool {kind} is not an object",
            safe_message="钉钉工具参数或结果无效",
            error_code=f"dingtalk_{kind}_invalid",
        )
    try:
        encoded = canonical_json(value)
    except ValueError as exc:
        raise DingTalkMcpError(
            f"DingTalk Tool {kind} is not canonical JSON",
            safe_message="钉钉工具参数或结果无效",
            error_code=f"dingtalk_{kind}_invalid",
        ) from exc
    if len(encoded.encode("utf-8")) > MAX_TOOL_PAYLOAD_BYTES:
        raise DingTalkMcpError(
            f"DingTalk Tool {kind} exceeded byte limit",
            safe_message="钉钉工具参数或结果超过大小限制",
            error_code=f"dingtalk_{kind}_too_large",
        )
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        raise DingTalkMcpError(
            f"DingTalk Tool {kind} failed schema validation",
            safe_message="钉钉工具参数或结果不符合固定合同",
            error_code=f"dingtalk_{kind}_invalid",
        )
    return dict(value)


def _safe_payload_summary(value: dict[str, Any]) -> dict[str, Any]:
    encoded = canonical_json(value).encode("utf-8")
    list_counts = {str(key): len(item) for key, item in value.items() if isinstance(item, list)}
    return {
        "field_names": sorted(str(key)[:128] for key in value)[:64],
        "list_counts": list_counts,
        "payload_bytes": len(encoded),
        "payload_hash": hashlib.sha256(encoded).hexdigest(),
    }
