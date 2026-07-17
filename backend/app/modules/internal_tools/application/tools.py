from __future__ import annotations

import time
from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.audit.application.summaries import bounded_summary
from app.modules.internal_tools.application.policies import (
    assert_loki_label,
    assert_loki_bounds,
    assert_readonly_sql,
    assert_redis_readonly,
)
from app.modules.internal_tools.infrastructure.internal_api_client import (
    InternalApiClient,
    ToolRequestContext,
    ToolResult,
)
from app.modules.job.infrastructure.repositories import AgentRepository
from app.modules.permission.application.permission_service import PermissionService
from app.shared.config import ExecutionSettings
from app.shared.exceptions import ToolPolicyError
from app.shared.logging import correlation_id_var


class ReadOnlyToolService:
    def __init__(
        self,
        *,
        internal_api_client: InternalApiClient,
        permission_service: PermissionService,
        audit_service: AuditService,
        repository: AgentRepository,
        limits: ExecutionSettings,
    ) -> None:
        self.internal_api_client = internal_api_client
        self.permission_service = permission_service
        self.audit_service = audit_service
        self.repository = repository
        self.limits = limits

    def call_tool(
        self,
        *,
        job_id: str,
        user_id: str,
        project_code: str,
        tool_name: str,
        arguments: dict[str, Any],
        record_tool_call: bool = True,
    ) -> ToolResult:
        started = time.monotonic()
        audit_id: str | None = None
        try:
            job = self.repository.get_job(job_id)
            expected_user_id = job.internal_user_id or job.user_id
            if expected_user_id != user_id or job.project_code != project_code:
                raise ToolPolicyError(
                    "Tool request identity does not match persisted job",
                    safe_message="Tool request does not match the Agent job",
                )
            if not self.repository.job_allows_tool(job_id, tool_name):
                raise ToolPolicyError(
                    f"Tool {tool_name} is not assigned to the Agent publication",
                    safe_message="Tool is not assigned to this Agent version",
                )
            scope = _addressing_from_arguments(arguments)
            self.permission_service.assert_tool_allowed(
                user_id=user_id,
                tool_name=tool_name,
                project_code=project_code,
                scope=scope,
            )
            self._assert_tool_policy(tool_name, arguments)
            audit_id = self.audit_service.record(
                "tool.call.allowed",
                status="SUCCEEDED",
                summary=f"Tool {tool_name} allowed",
                job_id=job_id,
                actor_id=user_id,
                payload={"tool": tool_name, "arguments": arguments},
            )
            result = self._execute(
                tool_name,
                arguments,
                job_id=job_id,
                user_id=user_id,
                project_code=project_code,
            )
            if record_tool_call:
                self.repository.add_tool_call(
                    job_id=job_id,
                    tool_name=tool_name,
                    request_payload=bounded_summary(arguments, self.limits.max_tool_response_chars),
                    response_summary=bounded_summary(
                        _storage_summary(result), self.limits.max_tool_response_chars
                    ),
                    status="SUCCEEDED",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    risk_level=_risk_level(tool_name),
                    audit_id=audit_id,
                )
            return result
        except Exception as exc:
            audit_id = self.audit_service.record(
                "tool.call.rejected" if isinstance(exc, ToolPolicyError) else "tool.call.failed",
                status="FAILED",
                summary=getattr(exc, "safe_message", str(exc)),
                job_id=job_id,
                actor_id=user_id,
                payload={"tool": tool_name, "arguments": arguments},
            )
            if record_tool_call:
                self.repository.add_tool_call(
                    job_id=job_id,
                    tool_name=tool_name,
                    request_payload=bounded_summary(arguments, self.limits.max_tool_response_chars),
                    response_summary={"error": getattr(exc, "safe_message", str(exc))},
                    status="FAILED",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    risk_level="medium",
                    audit_id=audit_id,
                )
            raise

    def _assert_tool_policy(self, tool_name: str, arguments: dict[str, Any]) -> None:
        if tool_name == "query_database":
            assert_readonly_sql(str(arguments.get("sql", "")))
        elif tool_name == "query_redis_get":
            assert_redis_readonly("get", limit=None, settings=self.limits)
        elif tool_name == "query_redis_scan":
            assert_redis_readonly(
                "scan",
                limit=int(arguments.get("limit", self.limits.redis_scan_limit)),
                settings=self.limits,
            )
        elif tool_name == "query_loki":
            selector = _loki_selector_from_arguments(arguments)
            assert_loki_bounds(
                selector=selector,
                minutes=int(arguments.get("minutes", 15)),
                limit=int(arguments.get("limit", 100)),
                settings=self.limits,
            )
        elif tool_name == "diagnose_loki_probe":
            selector = _loki_selector_from_arguments(arguments)
            assert_loki_bounds(
                selector=selector,
                minutes=int(arguments.get("minutes", 15)),
                limit=int(arguments.get("limit", 100)),
                settings=self.limits,
            )
        elif tool_name == "diagnose_loki_labels":
            assert_loki_diagnostic_bounds(arguments, self.limits)
        elif tool_name == "diagnose_loki_label_values":
            assert_loki_label(str(arguments.get("label", "")))
            assert_loki_diagnostic_bounds(arguments, self.limits)
        elif tool_name not in {
            "get_er_context",
            "get_business_flow_context",
            "get_schema_directory",
        }:
            raise ToolPolicyError(f"Tool {tool_name} is not registered for read-only MVP")

    def _execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        job_id: str,
        user_id: str,
        project_code: str,
    ) -> ToolResult:
        context = ToolRequestContext(
            job_id=job_id,
            user_id=user_id,
            project_code=project_code,
            correlation_id=correlation_id_var.get(),
        )
        if tool_name == "get_er_context":
            return self.internal_api_client.get_er_context(
                query=str(arguments.get("query", "")),
                context=context,
            )
        if tool_name == "get_business_flow_context":
            return self.internal_api_client.get_business_flow_context(
                query=str(arguments.get("query", "")),
                context=context,
            )
        if tool_name == "get_schema_directory":
            addressing = _addressing_from_arguments(arguments)
            if not addressing.get("environment") or not addressing.get("base"):
                raise ToolPolicyError("Schema directory requires environment and base")
            return self.internal_api_client.get_schema_directory(
                context=context,
                environment=addressing["environment"],
                base=addressing["base"],
                workshop=addressing.get("workshop"),
                query=str(arguments.get("query", "")),
                limit=int(arguments.get("limit", 50)),
            )
        addressing = _addressing_from_arguments(arguments)
        if tool_name == "query_loki":
            return self.internal_api_client.query_loki(
                selector=_loki_selector_from_arguments(arguments),
                query=str(arguments.get("query", "")),
                minutes=int(arguments.get("minutes", 15)),
                limit=int(arguments.get("limit", 100)),
                context=context,
                **addressing,
            )
        if tool_name == "diagnose_loki_labels":
            if not addressing.get("environment") or not addressing.get("base"):
                raise ToolPolicyError("Loki diagnostics require environment and base")
            return self.internal_api_client.diagnose_loki_labels(
                context=context,
                environment=addressing["environment"],
                base=addressing["base"],
                workshop=addressing.get("workshop"),
                minutes=int(arguments.get("minutes", 15)),
                limit=int(arguments.get("limit", 100)),
            )
        if tool_name == "diagnose_loki_label_values":
            if not addressing.get("environment") or not addressing.get("base"):
                raise ToolPolicyError("Loki diagnostics require environment and base")
            return self.internal_api_client.diagnose_loki_label_values(
                context=context,
                environment=addressing["environment"],
                base=addressing["base"],
                workshop=addressing.get("workshop"),
                label=str(arguments.get("label", "")),
                minutes=int(arguments.get("minutes", 15)),
                limit=int(arguments.get("limit", 100)),
            )
        if tool_name == "diagnose_loki_probe":
            if not addressing.get("environment") or not addressing.get("base"):
                raise ToolPolicyError("Loki diagnostics require environment and base")
            return self.internal_api_client.diagnose_loki_probe(
                selector=_loki_selector_from_arguments(arguments),
                query=str(arguments.get("query", "")),
                minutes=int(arguments.get("minutes", 15)),
                limit=int(arguments.get("limit", 100)),
                context=context,
                environment=addressing["environment"],
                base=addressing["base"],
                workshop=addressing.get("workshop"),
            )
        if tool_name == "query_database":
            return self.internal_api_client.query_database(
                datasource=str(arguments.get("datasource", "default")),
                sql=str(arguments["sql"]),
                limit=int(arguments.get("limit", 100)),
                context=context,
                **addressing,
            )
        if tool_name == "query_redis_get":
            return self.internal_api_client.query_redis_get(
                datasource=str(arguments.get("datasource", "default")),
                key=str(arguments["key"]),
                context=context,
                **addressing,
            )
        if tool_name == "query_redis_scan":
            return self.internal_api_client.query_redis_scan(
                datasource=str(arguments.get("datasource", "default")),
                pattern=str(arguments["pattern"]),
                limit=int(arguments.get("limit", self.limits.redis_scan_limit)),
                context=context,
                **addressing,
            )
        raise ToolPolicyError(f"Tool {tool_name} is not registered")


def _storage_summary(result: ToolResult) -> dict[str, Any]:
    if not result.metadata and not result.truncated:
        return result.summary
    return {
        "summary": result.summary,
        "metadata": result.metadata,
        "truncated": result.truncated,
    }


def _addressing_from_arguments(arguments: dict[str, Any]) -> dict[str, str]:
    """Pass structured addressing only when provided, keeping legacy callers intact."""

    addressing: dict[str, str] = {}
    for field in ("environment", "base", "workshop"):
        value = arguments.get(field)
        if value is not None and str(value).strip():
            addressing[field] = str(value).strip()
    return addressing


def assert_loki_diagnostic_bounds(arguments: dict[str, Any], limits: ExecutionSettings) -> None:
    minutes = int(arguments.get("minutes", 15))
    limit = int(arguments.get("limit", 100))
    if minutes <= 0 or minutes > limits.max_loki_minutes:
        raise ToolPolicyError("Loki time range exceeds configured maximum")
    if limit <= 0 or limit > limits.max_loki_lines:
        raise ToolPolicyError("Loki result size exceeds configured maximum")


def _risk_level(tool_name: str) -> str:
    if tool_name.startswith("get_") or tool_name.startswith("diagnose_loki"):
        return "low"
    if tool_name == "query_loki":
        return "low"
    return "medium"


def _loki_selector_from_arguments(arguments: dict[str, Any]) -> dict[str, str]:
    selector = arguments.get("selector")
    if selector is None:
        service = str(arguments.get("service", "")).strip()
        return {"service": service} if service else {}
    if not isinstance(selector, dict):
        raise ToolPolicyError("Loki selector must be an object")
    normalized: dict[str, str] = {}
    for key, value in selector.items():
        if not isinstance(value, str):
            raise ToolPolicyError("Loki selector values must be strings")
        normalized[str(key)] = value.strip()
    return normalized
