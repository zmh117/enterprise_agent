from __future__ import annotations

import time
from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.authorization_center.application import BusinessAuthorizationService
from app.modules.audit.application.summaries import bounded_summary
from app.modules.mcp_tool_runtime.policies import (
    assert_loki_label,
    assert_loki_bounds,
    assert_readonly_sql,
    assert_redis_readonly,
)
from app.modules.mcp_tool_runtime.contracts import (
    ReadOnlyToolExecutor,
    ToolRequestContext,
    ToolResult,
)
from app.modules.job.infrastructure.repositories import AgentRepository
from app.modules.mcp_tool_runtime.job_snapshot import (
    JobMcpToolSnapshotService,
)
from app.modules.permission.application.permission_service import PermissionService
from app.shared.config import ExecutionSettings
from app.shared.exceptions import PermissionDenied, ToolPolicyError
from app.shared.logging import correlation_id_var


class ReadOnlyToolService:
    def __init__(
        self,
        *,
        tool_executor: ReadOnlyToolExecutor,
        permission_service: PermissionService,
        audit_service: AuditService,
        repository: AgentRepository,
        limits: ExecutionSettings,
        business_authorization_service: BusinessAuthorizationService | None = None,
        mcp_tool_snapshot_service: JobMcpToolSnapshotService | None = None,
    ) -> None:
        self.tool_executor = tool_executor
        self.permission_service = permission_service
        self.audit_service = audit_service
        self.repository = repository
        self.limits = limits
        self.business_authorization_service = business_authorization_service
        self.mcp_tool_snapshot_service = mcp_tool_snapshot_service

    def is_tool_visible_for_job(self, *, job_id: str, tool_name: str) -> bool:
        job = self.repository.get_job(job_id)
        exact = self._exact_tool_context(job_id=job_id, tool_name=tool_name)
        if exact is None:
            return False
        _, bindings = exact
        if not bindings or any(
            binding["resource_slot"] and not binding["candidates"] for binding in bindings
        ):
            return False
        # Exposure verifies only the frozen Tool/publication grant. The Agent
        # has not selected a target yet; exact scope authorization is enforced
        # again on every Tool Call before resource resolution.
        if not job.business_application_id:
            try:
                self.permission_service.assert_mcp_tool_use_grant(
                    user_id=job.internal_user_id or job.user_id,
                    tool_identifier=tool_name,
                    project_code=job.project_code,
                )
            except ToolPolicyError:
                return False
            return True
        if self.business_authorization_service is None:
            return False
        return bool(
            self.business_authorization_service.decide(
                user_id=job.internal_user_id or job.user_id,
                application_id=job.business_application_id,
                tool_identifier=tool_name,
                stage="tool_exposure",
            )["allowed"]
        )

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
        persisted_tool_call_id = ""
        try:
            job = self.repository.get_job(job_id)
            expected_user_id = job.internal_user_id or job.user_id
            if expected_user_id != user_id or job.project_code != project_code:
                raise ToolPolicyError(
                    "Tool request identity does not match persisted job",
                    safe_message="工具请求与 Agent 任务不匹配",
                )
            exact = self._exact_tool_context(
                job_id=job_id,
                tool_name=tool_name,
            )
            if exact is None:
                raise ToolPolicyError(
                    "Job has no exact MCP Tool Snapshot",
                    safe_message="此 Job 缺少精确 MCP Tool 快照",
                    error_code="mcp_tool_snapshot_missing",
                )
            if not exact[1]:
                raise ToolPolicyError(
                    f"Tool {tool_name} is not in the Job exact Snapshot",
                    safe_message="此 Job 快照未授权该工具",
                    error_code="mcp_tool_not_in_job_snapshot",
                )
            scope = _addressing_from_arguments(arguments)
            if job.business_application_id:
                if self.business_authorization_service is None:
                    raise ToolPolicyError(
                        "Business authorization service is unavailable",
                        safe_message="业务应用授权服务暂时不可用",
                        error_code="business_authorization_unavailable",
                    )
                try:
                    decision = self.business_authorization_service.require(
                        user_id=user_id,
                        application_id=job.business_application_id,
                        tool_identifier=tool_name,
                        environment=scope.get("environment", ""),
                        base=scope.get("base", ""),
                        workshop=scope.get("workshop", ""),
                        stage="tool_call",
                    )
                except PermissionDenied as exc:
                    raise ToolPolicyError(
                        "Business application tool access denied",
                        safe_message=exc.safe_message,
                        error_code=exc.error_code,
                    ) from exc
                self.audit_service.record(
                    "authorization.business.tool_call",
                    status="SUCCEEDED",
                    summary="Business authorization allowed tool call",
                    job_id=job_id,
                    actor_id=user_id,
                    payload=decision,
                )
            else:
                # Direct Jobs have no application RBAC boundary, so they retain
                # the legacy fail-closed tool/project permission check.
                self.permission_service.assert_mcp_tool_use_grant(
                    user_id=user_id,
                    tool_identifier=tool_name,
                    project_code=project_code,
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
            persisted_tool_call_id = self.repository.add_tool_call(
                job_id=job_id,
                tool_name=tool_name,
                request_payload=bounded_summary(
                    arguments,
                    self.limits.max_tool_response_chars,
                ),
                response_summary={"status": "STARTED"},
                status="STARTED",
                duration_ms=0,
                risk_level=_risk_level(tool_name),
                audit_id=audit_id,
            )
            result = self._execute(
                tool_name,
                {**arguments, **scope},
                job_id=job_id,
                user_id=user_id,
                project_code=project_code,
                tool_call_id=persisted_tool_call_id,
            )
            self.repository.complete_tool_call(
                persisted_tool_call_id,
                response_summary=bounded_summary(
                    _storage_summary(result),
                    self.limits.max_tool_response_chars,
                ),
                status="SUCCEEDED",
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            result.metadata.setdefault(
                "_persisted_tool_call_id",
                persisted_tool_call_id,
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
            if persisted_tool_call_id:
                self.repository.complete_tool_call(
                    persisted_tool_call_id,
                    response_summary={
                        "error": getattr(
                            exc,
                            "safe_message",
                            str(exc),
                        )
                    },
                    status="FAILED",
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
                setattr(
                    exc,
                    "persisted_tool_call_id",
                    persisted_tool_call_id,
                )
            elif record_tool_call:
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

    def _exact_tool_context(
        self,
        *,
        job_id: str,
        tool_name: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
        if self.mcp_tool_snapshot_service is None:
            return None
        return self.mcp_tool_snapshot_service.tool_binding(
            job_id=job_id,
            tool_identifier=tool_name,
        )

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
        tool_call_id: str,
    ) -> ToolResult:
        context = ToolRequestContext(
            job_id=job_id,
            user_id=user_id,
            project_code=project_code,
            correlation_id=correlation_id_var.get(),
            tool_call_id=tool_call_id,
        )
        if tool_name == "get_er_context":
            return self.tool_executor.get_er_context(
                query=str(arguments.get("query", "")),
                context=context,
            )
        if tool_name == "get_business_flow_context":
            return self.tool_executor.get_business_flow_context(
                query=str(arguments.get("query", "")),
                context=context,
            )
        if tool_name == "get_schema_directory":
            addressing = _addressing_from_arguments(arguments)
            if not addressing.get("environment"):
                raise ToolPolicyError(
                    "Schema directory requires environment",
                    safe_message="查询 Schema 目录必须指定环境",
                )
            resource_routing = _resource_routing_from_arguments(arguments)
            return self.tool_executor.get_schema_directory(
                context=context,
                environment=resource_routing.pop("environment"),
                base=resource_routing.pop("base", ""),
                query=str(arguments.get("query", "")),
                limit=int(arguments.get("limit", 50)),
                **resource_routing,
            )
        addressing = _addressing_from_arguments(arguments)
        if tool_name == "query_loki":
            return self.tool_executor.query_loki(
                selector=_loki_selector_from_arguments(arguments),
                query=str(arguments.get("query", "")),
                minutes=int(arguments.get("minutes", 15)),
                limit=int(arguments.get("limit", 100)),
                context=context,
                **addressing,
            )
        if tool_name == "diagnose_loki_labels":
            if not addressing.get("environment"):
                raise ToolPolicyError(
                    "Loki diagnostics require environment",
                    safe_message="Loki 诊断必须指定环境",
                )
            return self.tool_executor.diagnose_loki_labels(
                context=context,
                environment=addressing["environment"],
                base=addressing.get("base", ""),
                workshop=addressing.get("workshop"),
                minutes=int(arguments.get("minutes", 15)),
                limit=int(arguments.get("limit", 100)),
            )
        if tool_name == "diagnose_loki_label_values":
            if not addressing.get("environment"):
                raise ToolPolicyError(
                    "Loki diagnostics require environment",
                    safe_message="Loki 诊断必须指定环境",
                )
            return self.tool_executor.diagnose_loki_label_values(
                context=context,
                environment=addressing["environment"],
                base=addressing.get("base", ""),
                workshop=addressing.get("workshop"),
                label=str(arguments.get("label", "")),
                minutes=int(arguments.get("minutes", 15)),
                limit=int(arguments.get("limit", 100)),
            )
        if tool_name == "diagnose_loki_probe":
            if not addressing.get("environment"):
                raise ToolPolicyError(
                    "Loki diagnostics require environment",
                    safe_message="Loki 诊断必须指定环境",
                )
            return self.tool_executor.diagnose_loki_probe(
                selector=_loki_selector_from_arguments(arguments),
                query=str(arguments.get("query", "")),
                minutes=int(arguments.get("minutes", 15)),
                limit=int(arguments.get("limit", 100)),
                context=context,
                environment=addressing["environment"],
                base=addressing.get("base", ""),
                workshop=addressing.get("workshop"),
            )
        if tool_name == "query_database":
            resource_routing = _resource_routing_from_arguments(arguments)
            return self.tool_executor.query_database(
                datasource=str(arguments.get("datasource", "default")),
                sql=str(arguments["sql"]),
                limit=int(arguments.get("limit", 100)),
                context=context,
                **resource_routing,
            )
        if tool_name == "query_redis_get":
            resource_routing = _resource_routing_from_arguments(arguments)
            return self.tool_executor.query_redis_get(
                datasource=str(arguments.get("datasource", "default")),
                key=str(arguments["key"]),
                context=context,
                **resource_routing,
            )
        if tool_name == "query_redis_scan":
            resource_routing = _resource_routing_from_arguments(arguments)
            return self.tool_executor.query_redis_scan(
                datasource=str(arguments.get("datasource", "default")),
                pattern=str(arguments["pattern"]),
                limit=int(arguments.get("limit", self.limits.redis_scan_limit)),
                context=context,
                **resource_routing,
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


def _placement_from_arguments(
    arguments: dict[str, Any],
) -> str | None:
    value = arguments.get("placement")
    if value is None:
        return None
    placement = str(value).strip().lower()
    if placement not in {"cloud", "edge"}:
        raise ToolPolicyError(
            "Resource placement must be cloud or edge",
            safe_message="资源位置只能选择 cloud 或 edge",
            error_code="resource_placement_invalid",
        )
    return placement


def _resource_routing_from_arguments(
    arguments: dict[str, Any],
) -> dict[str, str]:
    routing = _addressing_from_arguments(arguments)
    placement = _placement_from_arguments(arguments)
    if placement:
        routing["placement"] = placement
    return routing


def assert_loki_diagnostic_bounds(arguments: dict[str, Any], limits: ExecutionSettings) -> None:
    minutes = int(arguments.get("minutes", 15))
    limit = int(arguments.get("limit", 100))
    if minutes <= 0 or minutes > limits.max_loki_minutes:
        raise ToolPolicyError(
            "Loki time range exceeds configured maximum",
            safe_message="Loki 查询时间范围超过配置上限",
        )
    if limit <= 0 or limit > limits.max_loki_lines:
        raise ToolPolicyError(
            "Loki result size exceeds configured maximum",
            safe_message="Loki 查询结果数量超过配置上限",
        )


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
        raise ToolPolicyError(
            "Loki selector must be an object",
            safe_message="Loki 选择器必须是对象",
        )
    normalized: dict[str, str] = {}
    for key, value in selector.items():
        if not isinstance(value, str):
            raise ToolPolicyError(
                "Loki selector values must be strings",
                safe_message="Loki 选择器值必须是文本",
            )
        normalized[str(key)] = value.strip()
    return normalized
