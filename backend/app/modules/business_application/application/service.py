from __future__ import annotations

import hashlib
import json
from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.business_application.domain.policies import (
    canonical_json,
    reject_dangerous_content,
    snapshot_hash,
    validate_code,
    validate_delivery,
    validate_environment,
    validate_execution_policy,
    validate_session_policy,
    validate_status,
    validate_trigger,
    verify_snapshot,
)
from app.modules.business_application.domain.runtime import RuntimeReadinessEvaluator
from app.modules.business_application.infrastructure import BusinessApplicationRepository
from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.mcp_tool_publications import McpToolPublicationService
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import NonRetryableExecutionError, NotFound, PermissionDenied


SCHEMA_VERSION = 1
RUNTIME_CONTRACT = {
    "runtime_kind": "typescript-v1",
    "protocol_version": "1.0",
    "execution_request_schema": "AgentExecutionRequestV1",
}


class BusinessApplicationService:
    def __init__(
        self,
        repository: BusinessApplicationRepository,
        authorization: AuthorizationEvaluator,
        audit_service: AuditService,
        mcp_tools: McpToolPublicationService,
        runtime_evaluator: RuntimeReadinessEvaluator,
    ) -> None:
        self.repository = repository
        self.authorization = authorization
        self.audit_service = audit_service
        self.mcp_tools = mcp_tools
        self.runtime_evaluator = runtime_evaluator

    def list_applications(
        self,
        *,
        actor_id: str,
        project_code: str = "",
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        normalized_project = (
            validate_code(project_code, field="project_code") if project_code else ""
        )
        return [
            self._summary(value)
            for value in self.repository.list_applications(
                project_code=normalized_project,
                include_archived=include_archived,
                limit=limit,
                offset=offset,
            )
            if self.authorization.decide(
                user_id=actor_id,
                resource_type="business_application",
                resource_code=str(value["code"]),
                action="read",
            ).allowed
        ]

    def detail(self, *, actor_id: str, code: str) -> dict[str, Any]:
        normalized_code = validate_code(code)
        self._require(actor_id, normalized_code, "read", hide=True)
        return self._detail(self.repository.detail(normalized_code))

    @operation_unit_of_work(lambda service: service.repository.database)
    def create(
        self,
        *,
        actor_id: str,
        code: str,
        name: str,
        description: str,
        project_code: str,
        owner_user_id: str,
        expected_revision: int = 0,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        self._require(actor_id, "*", "create")
        if expected_revision != 0:
            raise NonRetryableExecutionError(
                "New Business Application expected revision must be zero",
                safe_message="业务应用已发生变化，请刷新后重试",
                error_code="revision_conflict",
            )
        normalized: dict[str, Any] = {
            "expected_revision": expected_revision,
            "code": validate_code(code),
            "name": self._name(name),
            "description": self._description(description),
            "project_code": validate_code(project_code, field="project_code"),
            "owner_user_id": owner_user_id.strip(),
        }
        self._validate_owner(normalized["owner_user_id"])
        replay = self._idempotent(
            idempotency_key,
            "application.create",
            actor_id,
            normalized,
        )
        if replay is not None:
            return replay
        application = self.repository.create(
            actor_id=actor_id,
            **{key: value for key, value in normalized.items() if key != "expected_revision"},
        )
        result = self._detail(self.repository.detail(str(application["code"])))
        self._remember(
            idempotency_key,
            "application.create",
            actor_id,
            normalized,
            result,
        )
        self._audit("created", actor_id, application)
        return result

    @operation_unit_of_work(lambda service: service.repository.database)
    def update_metadata(
        self,
        *,
        actor_id: str,
        code: str,
        expected_revision: int,
        name: str,
        description: str,
        project_code: str,
        owner_user_id: str,
        status: str,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        normalized_code = validate_code(code)
        self._require(actor_id, normalized_code, "edit")
        current = self.repository.get_by_code(normalized_code)
        normalized_status = validate_status(status)
        if str(current["status"]) == "archived" and normalized_status != "archived":
            raise self._lifecycle("已归档业务应用不能恢复")
        active = [
            value
            for value in self.repository.list_deployments(str(current["id"]))
            if value["active"]
        ]
        if normalized_status in {"disabled", "archived"} and active:
            raise NonRetryableExecutionError(
                "Active deployments must be deactivated first",
                safe_message="请先停用所有活动环境，再变更应用生命周期",
                error_code="dependency_in_use",
            )
        if normalized_status == "archived" and str(current["status"]) != "disabled":
            raise self._lifecycle("业务应用必须先停用才能归档")
        self._validate_owner(owner_user_id.strip())
        request = {
            "code": normalized_code,
            "expected_revision": expected_revision,
            "name": name.strip(),
            "description": description.strip(),
            "project_code": project_code.strip(),
            "owner_user_id": owner_user_id.strip(),
            "status": normalized_status,
        }
        replay = self._idempotent(
            idempotency_key,
            "application.update",
            actor_id,
            request,
        )
        if replay is not None:
            return replay
        if int(current["revision"]) != expected_revision:
            raise NonRetryableExecutionError(
                "Business Application revision conflict",
                safe_message="业务应用已发生变化，请刷新后重试",
                error_code="revision_conflict",
                diagnostics={"current_revision": int(current["revision"])},
            )
        updated = self.repository.update_metadata(
            code=normalized_code,
            expected_revision=expected_revision,
            name=self._name(name),
            description=self._description(description),
            project_code=validate_code(project_code, field="project_code"),
            owner_user_id=owner_user_id.strip(),
            status=normalized_status,
        )
        self._audit("updated", actor_id, updated)
        response = self._detail(self.repository.detail(normalized_code))
        self._remember(
            idempotency_key,
            "application.update",
            actor_id,
            request,
            response,
        )
        return response

    @operation_unit_of_work(lambda service: service.repository.database)
    def save_draft(
        self,
        *,
        actor_id: str,
        code: str,
        expected_revision: int,
        payload: dict[str, Any],
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        normalized_code = validate_code(code)
        self._require(actor_id, normalized_code, "edit")
        application = self.repository.get_by_code(normalized_code)
        if str(application["status"]) != "enabled":
            raise self._lifecycle("只有已启用的业务应用可以编辑")
        reject_dangerous_content(payload)
        normalized = self._normalize_draft(payload)
        request = {
            "code": normalized_code,
            "expected_revision": expected_revision,
            "draft": normalized,
        }
        replay = self._idempotent(
            idempotency_key,
            "application.save_draft",
            actor_id,
            request,
        )
        if replay is not None:
            return replay
        revision = self.repository.save_revision(
            application=application,
            expected_revision=expected_revision,
            actor_id=actor_id,
            config_hash=snapshot_hash(normalized),
            agent_publication_id=str(normalized["agent_publication_id"]),
            session_policy=dict(normalized["session_policy"]),
            execution_policy=dict(normalized["execution_policy"]),
            triggers=list(normalized["triggers"]),
            deliveries=list(normalized["deliveries"]),
            mcp_tool_publication_ids=list(normalized["mcp_tool_publication_ids"]),
        )
        self._remember(
            idempotency_key,
            "application.save_draft",
            actor_id,
            request,
            revision,
        )
        self._audit("draft_saved", actor_id, application, revision=revision)
        return revision

    @operation_unit_of_work(lambda service: service.repository.database)
    def validate(
        self,
        *,
        actor_id: str,
        code: str,
        revision_id: str = "",
        expected_revision: int,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        normalized_code = validate_code(code)
        self._require(actor_id, normalized_code, "edit")
        application = self.repository.get_by_code(normalized_code)
        request = {
            "code": normalized_code,
            "revision_id": revision_id,
            "expected_revision": expected_revision,
        }
        replay = self._idempotent(
            idempotency_key,
            "application.validate",
            actor_id,
            request,
        )
        if replay is not None:
            return replay
        if int(application["revision"]) != expected_revision:
            raise NonRetryableExecutionError(
                "Business Application revision conflict",
                safe_message="业务应用已发生变化，请刷新后重试",
                error_code="revision_conflict",
                diagnostics={"current_revision": int(application["revision"])},
            )
        revision = (
            self.repository.get_revision(revision_id)
            if revision_id
            else self.repository.latest_revision(str(application["id"]))
        )
        if revision is None or str(revision["application_id"]) != str(application["id"]):
            raise NotFound(
                "Business Application revision not found",
                safe_message="未找到业务应用修订版本",
            )
        errors, _ = self._prepare_publication(application, revision)
        result = self.repository.set_validation(
            str(revision["id"]), valid=not errors, errors=errors
        )
        self._remember(
            idempotency_key,
            "application.validate",
            actor_id,
            request,
            result,
        )
        self._audit("validated", actor_id, application, revision=result)
        return result

    @operation_unit_of_work(lambda service: service.repository.database)
    def publish(
        self,
        *,
        actor_id: str,
        code: str,
        revision_id: str,
        expected_revision: int,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        normalized_code = validate_code(code)
        self._require(actor_id, normalized_code, "publish")
        application = self.repository.get_by_code(normalized_code)
        if str(application["status"]) != "enabled":
            raise self._lifecycle("只有已启用的业务应用可以发布")
        revision = self.repository.get_revision(revision_id)
        if str(revision["application_id"]) != str(application["id"]):
            raise NotFound(
                "Business Application revision not found",
                safe_message="未找到业务应用修订版本",
            )
        request = {
            "code": normalized_code,
            "revision_id": revision_id,
            "expected_revision": expected_revision,
        }
        replay = self._idempotent(
            idempotency_key,
            "application.publish",
            actor_id,
            request,
        )
        if replay is not None:
            return replay
        if int(application["revision"]) != expected_revision:
            raise NonRetryableExecutionError(
                "Business Application revision conflict",
                safe_message="业务应用已发生变化，请刷新后重试",
                error_code="revision_conflict",
                diagnostics={"current_revision": int(application["revision"])},
            )
        errors, components = self._prepare_publication(application, revision)
        self.repository.set_validation(revision_id, valid=not errors, errors=errors)
        if errors:
            raise NonRetryableExecutionError(
                "Business Application publication validation failed",
                safe_message="业务应用校验失败",
                error_code="validation_failed",
                field_errors=errors,
            )
        snapshot = self._snapshot(application, revision, components)
        publication = self.repository.create_publication(
            application_id=str(application["id"]),
            revision_id=revision_id,
            revision=int(revision["revision"]),
            snapshot=snapshot,
            config_hash=snapshot_hash(snapshot),
            actor_id=actor_id,
            tool_publication_ids=list(revision["mcp_tool_publication_ids"]),
        )
        self._remember(
            idempotency_key,
            "application.publish",
            actor_id,
            request,
            publication,
        )
        self._audit("published", actor_id, application, publication=publication)
        return publication

    def publications(self, *, actor_id: str, code: str) -> list[dict[str, Any]]:
        normalized_code = validate_code(code)
        self._require(actor_id, normalized_code, "read", hide=True)
        application = self.repository.get_by_code(normalized_code)
        return [
            self._publication_state(item, application)
            for item in self.repository.list_publications(str(application["id"]))
        ]

    @operation_unit_of_work(lambda service: service.repository.database)
    def activate(
        self,
        *,
        actor_id: str,
        code: str,
        environment: str,
        publication_id: str,
        expected_revision: int,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        normalized_code = validate_code(code)
        normalized_environment = validate_environment(environment)
        self._require(actor_id, normalized_code, "activate")
        application = self.repository.get_by_code(normalized_code)
        if str(application["status"]) != "enabled":
            raise self._lifecycle("只有已启用的业务应用可以激活")
        publication = self._verified_publication(publication_id, application)
        request = {
            "code": normalized_code,
            "environment": normalized_environment,
            "publication_id": publication_id,
            "expected_revision": expected_revision,
        }
        replay = self._idempotent(
            idempotency_key,
            "application.activate",
            actor_id,
            request,
        )
        if replay is not None:
            return replay
        self._revalidate_snapshot(dict(publication["snapshot"]))
        readiness_errors = self.runtime_evaluator.activation_errors(dict(publication["snapshot"]))
        if readiness_errors:
            raise NonRetryableExecutionError(
                "Application publication is not runtime ready",
                safe_message="业务应用发布版本尚未满足运行条件",
                error_code="runtime_not_ready",
                field_errors=readiness_errors,
            )
        deployment = self.repository.activate(
            application_id=str(application["id"]),
            environment=normalized_environment,
            publication_id=publication_id,
            expected_revision=expected_revision,
            actor_id=actor_id,
            triggers=list(publication["snapshot"].get("triggers") or []),
        )
        self._remember(
            idempotency_key,
            "application.activate",
            actor_id,
            request,
            deployment,
        )
        self._audit("activated", actor_id, application, publication=publication)
        return self._deployment_state(deployment, publication)

    @operation_unit_of_work(lambda service: service.repository.database)
    def deactivate(
        self,
        *,
        actor_id: str,
        code: str,
        environment: str,
        expected_revision: int,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        normalized_code = validate_code(code)
        normalized_environment = validate_environment(environment)
        self._require(actor_id, normalized_code, "activate")
        application = self.repository.get_by_code(normalized_code)
        request = {
            "code": normalized_code,
            "environment": normalized_environment,
            "expected_revision": expected_revision,
        }
        replay = self._idempotent(
            idempotency_key,
            "application.deactivate",
            actor_id,
            request,
        )
        if replay is not None:
            return replay
        deployment = self.repository.deactivate(
            application_id=str(application["id"]),
            environment=normalized_environment,
            expected_revision=expected_revision,
            actor_id=actor_id,
        )
        self._remember(
            idempotency_key,
            "application.deactivate",
            actor_id,
            request,
            deployment,
        )
        self._audit("deactivated", actor_id, application)
        return self._deployment_state(deployment, None)

    def effective(self, *, actor_id: str, code: str, environment: str) -> dict[str, Any]:
        normalized_code = validate_code(code)
        self._require(actor_id, normalized_code, "read", hide=True)
        application = self.repository.get_by_code(normalized_code)
        deployment = self.repository.get_deployment(
            str(application["id"]), validate_environment(environment)
        )
        if deployment is None or not deployment["active"] or not deployment["publication_id"]:
            raise NotFound("Active deployment not found", safe_message="应用环境尚未激活")
        publication = self._verified_publication(str(deployment["publication_id"]), application)
        self._revalidate_snapshot(dict(publication["snapshot"]))
        readiness = self.runtime_evaluator.evaluate(
            snapshot=dict(publication["snapshot"]), deployment=deployment
        )
        return {
            "application": self._summary(application),
            "deployment": {**deployment, **readiness.to_dict()},
            "publication": {**publication, **readiness.to_dict()},
            **readiness.to_dict(),
        }

    def catalog(self, *, actor_id: str, code: str) -> dict[str, Any]:
        normalized_code = validate_code(code)
        self._require(actor_id, normalized_code, "read", hide=True)
        application = self.repository.get_by_code(normalized_code)
        agents = self.repository.database.execute(
            """
            select p.id, d.code, p.revision, d.project_code, d.status, p.config_hash
              from agent_publication p
              join agent_definition d on d.id = p.agent_id
             where d.status = 'enabled' and d.project_code = ?
             order by d.code, p.revision desc
            """,
            (application["project_code"],),
        )
        tools_by_agent: dict[str, list[dict[str, Any]]] = {}
        for agent in agents:
            tools_by_agent[str(agent["id"])] = self.repository.database.execute(
                """
                select t.id, mt.code, mt.name, t.server_code, t.server_version,
                       t.tool_name, t.required_scope, t.tool_schema_hash,
                       t.resource_kind, t.resource_code, t.resource_deployment_id,
                       t.resource_revision_id, t.config_hash, t.status
                  from agent_publication_mcp_tool b
                  join mcp_tool_publication t on t.id = b.tool_publication_id
                  join mcp_tool mt on mt.id = t.tool_id
                 where b.agent_publication_id = ?
                 order by mt.code
                """,
                (agent["id"],),
            )
        connectors = self.repository.database.execute(
            """
            select id, connector_type, name, enabled, allow_ingress, allow_delivery
              from integration_connector where enabled = 1 order by name, id
            """
        )
        return {
            "agents": agents,
            "mcp_tools_by_agent_publication": tools_by_agent,
            "connectors": connectors,
            "runtime_contract": dict(RUNTIME_CONTRACT),
        }

    def _normalize_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "agent_publication_id",
            "mcp_tool_publication_ids",
            "session_policy",
            "execution_policy",
            "triggers",
            "deliveries",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise NonRetryableExecutionError(
                "Unknown Application Draft fields",
                safe_message="业务应用配置无效",
                error_code="validation_failed",
                field_errors=[{"field": key, "message": "未知或已退役字段"} for key in unknown],
            )
        agent_publication_id = str(payload.get("agent_publication_id") or "").strip()
        if not agent_publication_id:
            raise self._field_error("agent_publication_id", "必须选择 Agent 发布版本")
        raw_tool_ids = payload.get("mcp_tool_publication_ids") or []
        if not isinstance(raw_tool_ids, list) or len(raw_tool_ids) > 100:
            raise self._field_error("mcp_tool_publication_ids", "必须是最多 100 项的列表")
        tool_ids = list(dict.fromkeys(str(item).strip() for item in raw_tool_ids))
        if any(not item for item in tool_ids):
            raise self._field_error("mcp_tool_publication_ids", "发布版本 ID 无效")
        triggers = [
            validate_trigger(dict(item), index)
            for index, item in enumerate(payload.get("triggers") or [])
        ]
        deliveries = [
            validate_delivery(dict(item), index)
            for index, item in enumerate(payload.get("deliveries") or [])
        ]
        return {
            "agent_publication_id": agent_publication_id,
            "mcp_tool_publication_ids": tool_ids,
            "session_policy": validate_session_policy(dict(payload.get("session_policy") or {})),
            "execution_policy": validate_execution_policy(
                dict(payload.get("execution_policy") or {})
            ),
            "triggers": triggers,
            "deliveries": deliveries,
            "runtime_contract": dict(RUNTIME_CONTRACT),
        }

    def _prepare_publication(
        self,
        application: dict[str, Any],
        revision: dict[str, Any],
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        errors: list[dict[str, str]] = []
        components: dict[str, Any] = {}
        try:
            agent = self._agent_publication(
                str(revision.get("agent_publication_id") or ""),
                str(application["project_code"]),
            )
            components["agent"] = agent
        except (NotFound, NonRetryableExecutionError) as exc:
            errors.append(
                {
                    "field": "agent_publication_id",
                    "message": getattr(exc, "safe_message", "Agent 发布版本不可用"),
                }
            )
        try:
            tools = self.mcp_tools.prepare_application_selection(
                str(revision.get("agent_publication_id") or ""),
                list(revision.get("mcp_tool_publication_ids") or []),
            )
            components["mcp_tools"] = [self._safe_tool(item) for item in tools]
        except (NotFound, NonRetryableExecutionError, ValueError) as exc:
            errors.append(
                {
                    "field": "mcp_tool_publication_ids",
                    "message": getattr(exc, "safe_message", "MCP Tool 发布版本不可用"),
                }
            )
        errors.extend(self._validate_connectors(revision))
        preview = self._snapshot(application, revision, components)
        errors.extend(self.runtime_evaluator.activation_errors(preview))
        return errors, components

    def _agent_publication(self, publication_id: str, project_code: str) -> dict[str, Any]:
        row = self.repository.database.execute_one(
            """
            select p.*, d.code, d.project_code, d.status definition_status
              from agent_publication p
              join agent_definition d on d.id = p.agent_id
             where p.id = ?
            """,
            (publication_id,),
        )
        if row is None:
            raise NotFound("Agent Publication not found", safe_message="Agent 发布版本不存在")
        if str(row["definition_status"]) != "enabled":
            raise NonRetryableExecutionError(
                "Agent is not enabled",
                safe_message="Agent 已停用",
                error_code="agent_disabled",
            )
        if str(row["project_code"]) != project_code:
            raise NonRetryableExecutionError(
                "Agent project does not match Application",
                safe_message="Agent 与业务应用不属于同一项目",
                error_code="project_scope_mismatch",
            )
        snapshot = self._json(row.get("snapshot_json"))
        if snapshot_hash(snapshot) != str(row["config_hash"]):
            raise NonRetryableExecutionError(
                "Agent Publication integrity failed",
                safe_message="Agent 发布版本完整性校验失败",
                error_code="agent_publication_integrity_failed",
            )
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "code": row["code"],
            "revision": int(row["revision"]),
            "config_hash": row["config_hash"],
        }

    def _validate_connectors(self, revision: dict[str, Any]) -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []
        seen_routes: set[tuple[str, str, str]] = set()
        for index, trigger in enumerate(revision.get("triggers") or []):
            if not trigger.get("enabled", True):
                continue
            row = self.repository.database.execute_one(
                """
                select id from integration_connector
                 where id = ? and enabled = 1 and allow_ingress = 1
                """,
                (trigger["connector_id"],),
            )
            if row is None:
                errors.append(
                    {"field": f"triggers.{index}.connector_id", "message": "入口连接器不可用"}
                )
            route = (
                str(trigger["trigger_type"]),
                str(trigger["connector_id"]),
                str(trigger["normalized_routing_key"]),
            )
            if route in seen_routes:
                errors.append({"field": f"triggers.{index}.routing_key", "message": "入口路由重复"})
            seen_routes.add(route)
            service_account = str(trigger.get("service_account_user_id") or "")
            if service_account:
                user = self.repository.database.execute_one(
                    "select id from app_user where id = ? and status = 'enabled'",
                    (service_account,),
                )
                if user is None:
                    errors.append(
                        {
                            "field": f"triggers.{index}.service_account_user_id",
                            "message": "服务账号不可用",
                        }
                    )
        for index, delivery in enumerate(revision.get("deliveries") or []):
            if not delivery.get("enabled", True):
                continue
            capability_column = (
                "allow_ingress"
                if str(delivery.get("delivery_type") or "") == "reply_original"
                else "allow_delivery"
            )
            row = self.repository.database.execute_one(
                f"""
                select id from integration_connector
                 where id = ? and enabled = 1 and {capability_column} = 1
                """,
                (delivery["connector_id"],),
            )
            if row is None:
                errors.append(
                    {
                        "field": f"deliveries.{index}.connector_id",
                        "message": "投递连接器不可用",
                    }
                )
        return errors

    def _snapshot(
        self,
        application: dict[str, Any],
        revision: dict[str, Any],
        components: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "application": {
                "id": application["id"],
                "code": application["code"],
                "project_code": application["project_code"],
                "definition_revision": int(application["revision"]),
            },
            "revision": {
                "id": revision["id"],
                "revision": int(revision["revision"]),
                "config_hash": revision["config_hash"],
            },
            "agent": dict(components.get("agent") or {}),
            "mcp_tools": list(components.get("mcp_tools") or []),
            "resources": [
                {
                    "kind": tool["resource_kind"],
                    "code": tool["resource_code"],
                    "deployment_id": tool["resource_deployment_id"],
                    "revision_id": tool["resource_revision_id"],
                }
                for tool in components.get("mcp_tools") or []
                if tool.get("resource_kind")
            ],
            "session_policy": dict(revision.get("session_policy") or {}),
            "execution_policy": dict(revision.get("execution_policy") or {}),
            "triggers": [self._safe_trigger(item) for item in revision.get("triggers") or []],
            "deliveries": [self._safe_delivery(item) for item in revision.get("deliveries") or []],
            "runtime_contract": dict(RUNTIME_CONTRACT),
        }

    def _verified_publication(
        self, publication_id: str, application: dict[str, Any]
    ) -> dict[str, Any]:
        publication = self.repository.get_publication(publication_id)
        if str(publication["application_id"]) != str(application["id"]):
            raise NotFound(
                "Business Application publication not found",
                safe_message="未找到业务应用发布版本",
            )
        if int(publication["schema_version"]) != SCHEMA_VERSION or not verify_snapshot(
            publication["snapshot"], str(publication["config_hash"])
        ):
            raise NonRetryableExecutionError(
                "Business Application publication integrity failed",
                safe_message="业务应用发布版本完整性校验失败",
                error_code="publication_integrity_failed",
            )
        if dict(publication["snapshot"].get("runtime_contract") or {}) != RUNTIME_CONTRACT:
            raise NonRetryableExecutionError(
                "Business Application runtime contract is unsupported",
                safe_message="业务应用运行时契约不受支持",
                error_code="runtime_contract_unsupported",
            )
        return publication

    def _revalidate_snapshot(self, snapshot: dict[str, Any]) -> None:
        agent = dict(snapshot.get("agent") or {})
        application = dict(snapshot.get("application") or {})
        self._agent_publication(
            str(agent.get("id") or ""), str(application.get("project_code") or "")
        )
        tool_ids = [str(item.get("id") or "") for item in snapshot.get("mcp_tools") or []]
        current = self.mcp_tools.prepare_application_selection(str(agent.get("id") or ""), tool_ids)
        by_id = {str(item["id"]): self._safe_tool(item) for item in current}
        for frozen in snapshot.get("mcp_tools") or []:
            publication_id = str(frozen.get("id") or "")
            if by_id.get(publication_id) != frozen:
                raise NonRetryableExecutionError(
                    "MCP Tool dependency changed",
                    safe_message="MCP Tool 或 Resource 依赖已变化",
                    error_code="mcp_tool_dependency_changed",
                )

    def _summary(self, application: dict[str, Any]) -> dict[str, Any]:
        deployments = application.get("deployments") or self.repository.list_deployments(
            str(application["id"])
        )
        active = next((item for item in deployments if item["active"]), None)
        publication = None
        if active and active.get("publication_id"):
            try:
                publication = self.repository.get_publication(str(active["publication_id"]))
            except NotFound:
                publication = None
        readiness = self.runtime_evaluator.evaluate(
            snapshot=dict((publication or {}).get("snapshot") or {}), deployment=active
        )
        return {
            **application,
            "active_environments": [
                str(item["environment"]) for item in deployments if item["active"]
            ],
            **readiness.to_dict(),
        }

    def _detail(self, application: dict[str, Any]) -> dict[str, Any]:
        publications = [
            self._publication_state(item, application)
            for item in application.get("publications") or []
        ]
        deployments = [
            self._deployment_state(
                item,
                next(
                    (
                        publication
                        for publication in application.get("publications") or []
                        if str(publication["id"]) == str(item.get("publication_id") or "")
                    ),
                    None,
                ),
            )
            for item in application.get("deployments") or []
        ]
        return {
            **self._summary({**application, "deployments": deployments}),
            "draft": application.get("draft"),
            "publications": publications,
            "deployments": deployments,
        }

    def _publication_state(
        self, publication: dict[str, Any], application: dict[str, Any]
    ) -> dict[str, Any]:
        deployment = next(
            (
                item
                for item in self.repository.list_deployments(str(application["id"]))
                if item["active"]
                and str(item.get("publication_id") or "") == str(publication["id"])
            ),
            None,
        )
        readiness = self.runtime_evaluator.evaluate(
            snapshot=dict(publication["snapshot"]), deployment=deployment
        )
        return {**publication, **readiness.to_dict()}

    def _deployment_state(
        self,
        deployment: dict[str, Any],
        publication: dict[str, Any] | None,
    ) -> dict[str, Any]:
        readiness = self.runtime_evaluator.evaluate(
            snapshot=dict((publication or {}).get("snapshot") or {}),
            deployment=deployment,
        )
        return {**deployment, **readiness.to_dict()}

    @staticmethod
    def _safe_tool(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "code": row["code"],
            "server_code": row["server_code"],
            "server_version": row["server_version"],
            "tool_name": row["tool_name"],
            "required_scope": row["required_scope"],
            "tool_schema_hash": row["tool_schema_hash"],
            "resource_kind": row["resource_kind"],
            "resource_code": row["resource_code"],
            "resource_deployment_id": row["resource_deployment_id"],
            "resource_revision_id": row["resource_revision_id"],
            "config_hash": row["config_hash"],
        }

    @staticmethod
    def _safe_trigger(value: dict[str, Any]) -> dict[str, Any]:
        return {
            "trigger_type": value["trigger_type"],
            "connector_id": value["connector_id"],
            "routing_key": value["routing_key"],
            "normalized_routing_key": value["normalized_routing_key"],
            "actor_policy": value["actor_policy"],
            "service_account_user_id": value.get("service_account_user_id") or "",
            "enabled": bool(value.get("enabled", True)),
            "config": dict(value.get("config") or {}),
        }

    @staticmethod
    def _safe_delivery(value: dict[str, Any]) -> dict[str, Any]:
        return {
            "delivery_type": value["delivery_type"],
            "connector_id": value["connector_id"],
            "enabled": bool(value.get("enabled", True)),
            "config": dict(value.get("config") or {}),
        }

    def _validate_owner(self, owner_user_id: str) -> None:
        if not owner_user_id:
            return
        if (
            self.repository.database.execute_one(
                "select id from app_user where id = ? and status = 'enabled'",
                (owner_user_id,),
            )
            is None
        ):
            raise self._field_error("owner_user_id", "负责人不存在或已停用")

    def _require(self, actor_id: str, code: str, action: str, *, hide: bool = False) -> None:
        decision = self.authorization.decide(
            user_id=actor_id,
            resource_type="business_application",
            resource_code=code,
            action=action,
        )
        if not decision.allowed:
            if hide:
                raise NotFound("Business Application not found", safe_message="未找到业务应用")
            raise PermissionDenied(
                "Business Application permission denied",
                safe_message="没有业务应用操作权限",
            )

    def _idempotent(
        self,
        key: str,
        operation: str,
        actor_id: str,
        request: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not key:
            return None
        if len(key) > 128:
            raise self._field_error("idempotency_key", "幂等键长度超出限制")
        row = self.repository.database.execute_one(
            "select * from management_operation_idempotency where idempotency_key = ?",
            (key,),
        )
        if row is None:
            return None
        request_hash = hashlib.sha256(canonical_json(request).encode()).hexdigest()
        if (
            str(row["operation"]) != operation
            or str(row["actor_id"]) != actor_id
            or str(row["request_hash"]) != request_hash
        ):
            raise NonRetryableExecutionError(
                "Management idempotency conflict",
                safe_message="重复请求与原请求不一致",
                error_code="idempotency_conflict",
            )
        return self._json(row["response_json"])

    def _remember(
        self,
        key: str,
        operation: str,
        actor_id: str,
        request: dict[str, Any],
        response: dict[str, Any],
    ) -> None:
        if not key:
            return
        request_hash = hashlib.sha256(canonical_json(request).encode()).hexdigest()
        self.repository.database.execute(
            """
            insert into management_operation_idempotency
              (idempotency_key, operation, actor_id, request_hash, response_json, created_at)
            values (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                key,
                operation,
                actor_id,
                request_hash,
                canonical_json(response),
            ),
        )

    def _audit(
        self,
        event: str,
        actor_id: str,
        application: dict[str, Any],
        *,
        revision: dict[str, Any] | None = None,
        publication: dict[str, Any] | None = None,
    ) -> None:
        self.audit_service.record(
            f"business_application.{event}",
            status="SUCCEEDED",
            summary=f"Business Application {event}",
            actor_id=actor_id,
            payload={
                "application_code": application["code"],
                "application_revision": int(application.get("revision") or 0),
                "draft_revision": int((revision or {}).get("revision") or 0),
                "publication_id": str((publication or {}).get("id") or ""),
                "config_hash": str((publication or revision or {}).get("config_hash") or ""),
            },
        )

    @staticmethod
    def _name(value: str) -> str:
        normalized = value.strip()
        if not 1 <= len(normalized) <= 200:
            raise BusinessApplicationService._field_error("name", "名称长度必须在 1 到 200 之间")
        return normalized

    @staticmethod
    def _description(value: str) -> str:
        normalized = value.strip()
        if len(normalized) > 4000:
            raise BusinessApplicationService._field_error("description", "说明长度不能超过 4000")
        return normalized

    @staticmethod
    def _field_error(field: str, message: str) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            f"{field}: {message}",
            safe_message="业务应用配置无效",
            error_code="validation_failed",
            field_errors=[{"field": field, "message": message}],
        )

    @staticmethod
    def _lifecycle(message: str) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            message,
            safe_message=message,
            error_code="invalid_lifecycle",
        )

    @staticmethod
    def _json(raw: object) -> dict[str, Any]:
        try:
            value = json.loads(str(raw or "{}"))
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
