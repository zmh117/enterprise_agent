from __future__ import annotations

from typing import Any

from app.modules.agent.infrastructure.runtime_readiness import AgentRuntimeReadinessGuard
from app.modules.audit.application.audit_service import AuditService
from app.modules.business_application.application.ports import (
    AgentPublicationReader,
    ChannelConnectorReader,
    ComponentReference,
    IdentitySubjectReader,
    WorkflowPublicationReader,
)
from app.modules.business_application.application.mcp_tool_composition import (
    ApplicationMcpToolCompositionService,
)
from app.modules.business_application.domain.policies import (
    canonical_json,
    normalize_routing_key,
    publication_document_processing_profile,
    reject_dangerous_content,
    required_file_mcp_tools,
    snapshot_hash,
    validate_code,
    validate_delivery,
    validate_document_processing_profile_code,
    validate_environment,
    validate_execution_policy,
    validate_file_format_policy_version,
    validate_session_policy,
    validate_task_file_attachment_dependency,
    validate_task_file_features,
    validate_task_workspace_retention_period,
    validate_status,
    validate_trigger,
    verify_publication_snapshot,
)
from app.modules.document_processing import (
    DOCLING_LAYOUT_OCR_V1,
    DOCLING_TEXT_V1,
    DocumentProcessingProfileCode,
    document_processing_profile_snapshot,
    document_processing_state,
)
from app.modules.business_application.domain.runtime import (
    RouteResolutionOutcome,
    RuntimeReadiness,
    RuntimeReadinessEvaluator,
    RuntimeReason,
    RuntimeRouteResolution,
    normalize_deployment_environment,
)
from app.modules.business_application.infrastructure import BusinessApplicationRepository
from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import NonRetryableExecutionError, NotFound

SCHEMA_VERSION = 5
WRITABLE_AGENT_RUNTIME_KIND = "python-v1"


class _RetirementMigrationDryRunRollback(Exception):
    def __init__(self, report: dict[str, Any]) -> None:
        super().__init__("rollback validated TypeScript Runtime retirement dry-run")
        self.report = report


def _require_python_runtime_kind(runtime_kind: str) -> None:
    if runtime_kind == WRITABLE_AGENT_RUNTIME_KIND:
        return
    if runtime_kind == "typescript-v1":
        raise NonRetryableExecutionError(
            "TypeScript Agent Runtime Business Application references are retired",
            safe_message=(
                "TypeScript Agent Runtime 已退役；请创建引用 Python Publication 的新版本"
            ),
            error_code="typescript_agent_runtime_retired",
        )
    raise NonRetryableExecutionError(
        "Business Application Agent Runtime is unsupported",
        safe_message="业务应用引用的 Agent Runtime 无效",
        error_code="agent_runtime_kind_unsupported",
    )


def _require_python_agent_publication(agent: ComponentReference) -> None:
    _require_python_runtime_kind(str(agent.runtime_kind or ""))


class BusinessApplicationService:
    def __init__(
        self,
        repository: BusinessApplicationRepository,
        authorization: AuthorizationEvaluator,
        audit_service: AuditService,
        agent_reader: AgentPublicationReader,
        workflow_reader: WorkflowPublicationReader,
        connector_reader: ChannelConnectorReader,
        identity_reader: IdentitySubjectReader,
        runtime_evaluator: RuntimeReadinessEvaluator | None = None,
        mcp_tool_composition_service: ApplicationMcpToolCompositionService | None = None,
        runtime_readiness_guard: AgentRuntimeReadinessGuard | None = None,
        document_layout_ocr_publication_ready: bool = False,
    ) -> None:
        self.repository = repository
        self.authorization = authorization
        self.audit_service = audit_service
        self.agent_reader = agent_reader
        self.workflow_reader = workflow_reader
        self.connector_reader = connector_reader
        self.identity_reader = identity_reader
        self.runtime_evaluator = runtime_evaluator or RuntimeReadinessEvaluator(
            data_plane_enabled=False,
            runtime_environment="local",
        )
        self.runtime_readiness_guard = runtime_readiness_guard
        self.document_layout_ocr_publication_ready = document_layout_ocr_publication_ready
        self.mcp_tool_composition_service = (
            mcp_tool_composition_service
            or ApplicationMcpToolCompositionService(repository.database)
        )

    def list_applications(
        self,
        *,
        actor_id: str,
        project_code: str = "",
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        values = self.repository.list_applications(
            project_codes={project_code} if project_code else None,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )
        return [
            self._summary(value)
            for value in values
            if self.authorization.decide(
                user_id=actor_id,
                resource_type="business_application",
                resource_code=str(value["code"]),
                action="read",
            ).allowed
        ]

    def detail(self, *, actor_id: str, code: str) -> dict[str, Any]:
        application = self.repository.get_by_code(validate_code(code))
        self._require(actor_id, code, "read")
        return self._detail(application)

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
    ) -> dict[str, Any]:
        self._require(actor_id, "*", "create")
        normalized_code = validate_code(code)
        normalized_project = validate_code(project_code, field="project_code")
        self._validate_metadata(name, description, owner_user_id)
        application = self.repository.create(
            code=normalized_code,
            name=name.strip(),
            description=description.strip(),
            project_code=normalized_project,
            owner_user_id=owner_user_id.strip(),
            actor_id=actor_id,
        )
        self._audit("created", actor_id, application)
        return self._detail(application)

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
    ) -> dict[str, Any]:
        normalized_code = validate_code(code)
        self._require(actor_id, normalized_code, "edit")
        self._validate_metadata(name, description, owner_user_id)
        current = self.repository.get_by_code(normalized_code)
        normalized_status = validate_status(status)
        application = self.repository.update_metadata(
            code=normalized_code,
            expected_revision=expected_revision,
            name=name.strip(),
            description=description.strip(),
            project_code=validate_code(project_code, field="project_code"),
            owner_user_id=owner_user_id.strip(),
            status=normalized_status,
        )
        event = "status_changed" if str(current["status"]) != normalized_status else "updated"
        self._audit(event, actor_id, application)
        return self._detail(application)

    @operation_unit_of_work(lambda service: service.repository.database)
    def save_draft(
        self,
        *,
        actor_id: str,
        code: str,
        expected_revision: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_code = validate_code(code)
        self._require(actor_id, normalized_code, "edit")
        application = self.repository.get_by_code(normalized_code)
        if str(application["status"]) == "archived":
            raise NonRetryableExecutionError(
                "Archived Business Application cannot be edited",
                safe_message="已归档的业务应用不能编辑",
                error_code="invalid_lifecycle",
            )
        reject_dangerous_content(payload)
        session_policy = validate_session_policy(dict(payload.get("session_policy") or {}))
        task_workspace_retention_period = validate_task_workspace_retention_period(
            payload.get("task_workspace_retention_period")
        )
        file_format_policy_version = validate_file_format_policy_version(
            payload.get("file_format_policy_version")
        )
        document_processing_profile_code = validate_document_processing_profile_code(
            payload.get("document_processing_profile_code")
        )
        task_file_features = validate_task_file_features(payload.get("task_file_features"))
        validate_task_file_attachment_dependency(
            session_policy=session_policy,
            task_file_features=task_file_features,
        )
        execution_policy = validate_execution_policy(dict(payload.get("execution_policy") or {}))
        triggers = [
            validate_trigger(dict(value), index)
            for index, value in enumerate(payload.get("triggers") or [])
        ]
        deliveries = [
            validate_delivery(dict(value), index)
            for index, value in enumerate(payload.get("deliveries") or [])
        ]
        agent_publication_id = str(payload.get("agent_publication_id") or "").strip()
        if not agent_publication_id:
            raise NonRetryableExecutionError(
                "Business Application requires an Agent Publication",
                safe_message="必须选择 Agent 发布版本",
                error_code="validation_failed",
                field_errors=[
                    {"field": "agent_publication_id", "message": "必须选择 Agent 发布版本"}
                ],
            )
        selected_agent = self.agent_reader.resolve(agent_publication_id)
        _require_python_agent_publication(selected_agent)
        mcp_tools = self.mcp_tool_composition_service.prepare(
            agent_publication_id=agent_publication_id,
            raw_tools=payload.get("mcp_tools") or [],
        )
        document_profile_errors = self._document_processing_compatibility_errors(
            document_processing_profile_code=document_processing_profile_code,
            task_file_features=task_file_features,
            session_policy=session_policy,
            agent=selected_agent,
        )
        file_tool_errors = self.mcp_tool_composition_service.file_feature_errors(
            agent_publication_id=agent_publication_id,
            task_file_features=task_file_features,
            selected_tools=mcp_tools,
        )
        if document_profile_errors or file_tool_errors:
            raise NonRetryableExecutionError(
                "Document processing or task file dependencies are incomplete",
                safe_message="文档处理或任务文件依赖不完整",
                error_code="validation_failed",
                field_errors=[*document_profile_errors, *file_tool_errors],
            )
        compatibility_errors = self._file_policy_compatibility_errors(
            file_format_policy_version=file_format_policy_version,
            task_file_features=task_file_features,
            agent=selected_agent,
        )
        if compatibility_errors:
            raise NonRetryableExecutionError(
                "File format policy is incompatible with the selected publication",
                safe_message="文件格式策略与 Agent Runtime 发布版本不兼容",
                error_code="validation_failed",
                field_errors=compatibility_errors,
            )
        normalized = {
            "agent_publication_id": agent_publication_id,
            "workflow_publication_id": str(payload.get("workflow_publication_id") or "").strip(),
            "task_workspace_retention_period": task_workspace_retention_period,
            "file_format_policy_version": file_format_policy_version,
            "document_processing_profile_code": document_processing_profile_code,
            "task_file_features": task_file_features,
            "session_policy": session_policy,
            "execution_policy": execution_policy,
            "triggers": triggers,
            "deliveries": deliveries,
            "mcp_tools": self.mcp_tool_composition_service.snapshot(mcp_tools),
        }
        revision = self.repository.save_revision(
            code=normalized_code,
            expected_revision=expected_revision,
            actor_id=actor_id,
            config_hash=snapshot_hash(normalized),
            agent_publication_id=str(normalized["agent_publication_id"]),
            workflow_publication_id=str(normalized["workflow_publication_id"]),
            task_workspace_retention_period=task_workspace_retention_period,
            file_format_policy_version=file_format_policy_version,
            document_processing_profile_code=document_processing_profile_code,
            task_file_features=task_file_features,
            session_policy=session_policy,
            execution_policy=execution_policy,
            triggers=triggers,
            deliveries=deliveries,
        )
        self.mcp_tool_composition_service.persist_draft(
            application_revision_id=str(revision["id"]),
            agent_publication_id=str(normalized["agent_publication_id"]),
            tools=mcp_tools,
        )
        if mcp_tools:
            revision = self.repository.get_revision(str(revision["id"]))
        revision = self._revision_with_document_processing(revision)
        self._audit("draft_saved", actor_id, application, revision=revision)
        return revision

    @operation_unit_of_work(lambda service: service.repository.database)
    def validate(
        self,
        *,
        actor_id: str,
        code: str,
        revision_id: str = "",
    ) -> dict[str, Any]:
        normalized_code = validate_code(code)
        self._require(actor_id, normalized_code, "edit")
        application = self.repository.get_by_code(normalized_code)
        revision = (
            self.repository.get_revision(revision_id) if revision_id else application.get("draft")
        )
        if not isinstance(revision, dict) or str(revision["application_id"]) != str(
            application["id"]
        ):
            raise NotFound(
                "Business Application revision not found",
                safe_message="未找到业务应用修订版本",
            )
        errors, _components = self._validate_revision(application, revision)
        result = self.repository.set_validation(
            str(revision["id"]), valid=not errors, errors=errors
        )
        result = self._revision_with_document_processing(result)
        self._audit("validated", actor_id, application, revision=result)
        return result

    def publish(
        self,
        *,
        actor_id: str,
        code: str,
        revision_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        del correlation_id
        normalized_code = validate_code(code)
        self._require(actor_id, normalized_code, "publish")
        application = self.repository.get_by_code(normalized_code)
        revision = self.repository.get_revision(revision_id)
        if str(revision["application_id"]) != str(application["id"]):
            raise NotFound(
                "Business Application revision not found",
                safe_message="未找到业务应用修订版本",
            )
        return self._publish(
            actor_id=actor_id,
            code=normalized_code,
            revision_id=revision_id,
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def _publish(
        self,
        *,
        actor_id: str,
        code: str,
        revision_id: str,
    ) -> dict[str, Any]:
        normalized_code = validate_code(code)
        self._require(actor_id, normalized_code, "publish")
        application = self.repository.get_by_code(normalized_code)
        if str(application["status"]) != "enabled":
            raise NonRetryableExecutionError(
                "Disabled or archived Business Application cannot be published",
                safe_message="只有已启用的业务应用才能发布",
                error_code="invalid_lifecycle",
            )
        revision = self.repository.get_revision(revision_id)
        if str(revision["application_id"]) != str(application["id"]):
            raise NotFound(
                "Business Application revision not found",
                safe_message="未找到业务应用修订版本",
            )
        _require_python_agent_publication(
            self.agent_reader.resolve(str(revision["agent_publication_id"]))
        )
        errors, components = self._validate_revision(application, revision)
        self.repository.set_validation(str(revision["id"]), valid=not errors, errors=errors)
        if errors:
            raise NonRetryableExecutionError(
                "Business Application publication validation failed",
                safe_message="业务应用校验失败",
                error_code="validation_failed",
                field_errors=errors,
            )
        if (
            str(revision.get("document_processing_profile_code") or "")
            == DocumentProcessingProfileCode.DOCLING_LAYOUT_OCR_V1.value
            and not self.document_layout_ocr_publication_ready
        ):
            raise NonRetryableExecutionError(
                "Document layout OCR deployment contract is not ready",
                safe_message="Office 内嵌图片布局 OCR 部署合同尚未就绪",
                error_code="validation_failed",
                field_errors=[
                    {
                        "field": "document_processing_profile_code",
                        "message": "布局 OCR Profile、离线模型或处理依赖尚未按固定摘要就绪",
                    }
                ],
            )
        prepared_mcp_tools = self.mcp_tool_composition_service.prepare(
            agent_publication_id=str(revision["agent_publication_id"]),
            raw_tools=revision.get("mcp_tools") or [],
        )
        snapshot = self._snapshot(application, revision, components)
        snapshot["mcp_tools"] = self.mcp_tool_composition_service.snapshot(prepared_mcp_tools)
        publication_hash = snapshot_hash(snapshot)
        publication = self.repository.create_publication(
            application_id=str(application["id"]),
            revision_id=str(revision["id"]),
            revision=int(revision["revision"]),
            snapshot=snapshot,
            config_hash=publication_hash,
            actor_id=actor_id,
        )
        if str(publication["config_hash"]) != publication_hash:
            raise NonRetryableExecutionError(
                "Existing Business Application publication binding differs",
                safe_message="该修订版本已使用不同的 MCP Tool 绑定发布",
                error_code="publication_binding_conflict",
            )
        self.mcp_tool_composition_service.persist_publication(
            application_publication_id=str(publication["id"]),
            agent_publication_id=str(revision["agent_publication_id"]),
            tools=prepared_mcp_tools,
        )
        publication = self.repository.get_publication(str(publication["id"]))
        publication = self._publication_document_processing(publication)
        self._audit("published", actor_id, application, publication=publication)
        return publication

    def activate(
        self,
        *,
        actor_id: str,
        code: str,
        environment: str,
        publication_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        """Probe the selected Runtime before entering the local database UoW."""

        normalized_code = validate_code(code)
        self._require(actor_id, normalized_code, "activate")
        application = self.repository.get_by_code(normalized_code)
        publication = self._verified_publication(publication_id)
        if str(publication["application_id"]) != str(application["id"]):
            raise NotFound(
                "Business Application publication not found",
                safe_message="未找到业务应用发布版本",
            )
        self._require_python_application_publication(publication)
        profile, _ = publication_document_processing_profile(publication["snapshot"])
        if (
            profile["code"] == DocumentProcessingProfileCode.DOCLING_LAYOUT_OCR_V1.value
            and not self.document_layout_ocr_publication_ready
        ):
            raise NonRetryableExecutionError(
                "Document layout OCR deployment contract is not ready",
                safe_message="Office 内嵌图片布局 OCR 部署合同尚未就绪",
                error_code="runtime_not_ready",
            )
        if (
            validate_file_format_policy_version(
                publication["snapshot"].get("file_format_policy_version")
            )
            == "text-v2"
        ):
            cutover_errors = self.mcp_tool_composition_service.text_v2_cutover_errors()
            if cutover_errors:
                raise NonRetryableExecutionError(
                    "text-v2 cutover preflight found active legacy File MCP Jobs",
                    safe_message="text-v2 切换预检未通过",
                    error_code="validation_failed",
                    field_errors=cutover_errors,
                )
        if self.runtime_readiness_guard is not None:
            agent = dict(publication["snapshot"].get("agent") or {})
            runtime_kind = str(agent.get("runtime_kind") or "")
            if not runtime_kind and agent.get("id"):
                runtime_kind = str(self.agent_reader.resolve(str(agent["id"])).runtime_kind or "")
            self.runtime_readiness_guard.require_ready(runtime_kind)
        return self._activate_in_unit_of_work(
            actor_id=actor_id,
            code=code,
            environment=environment,
            publication_id=publication_id,
            expected_revision=expected_revision,
        )

    def migrate_retired_typescript_publication(
        self,
        *,
        actor_id: str,
        source_application_publication_id: str,
        source_agent_publication_id: str,
        target_python_agent_publication_id: str,
        environment: str,
        expected_application_revision: int,
        expected_deployment_revision: int,
        correlation_id: str,
        apply: bool = False,
    ) -> dict[str, Any]:
        """Create and activate a new Python-backed Application publication.

        The source publications and both optimistic-lock revisions are exact
        operator inputs. Dry-run executes the same transactional path and then
        rolls it back, so compatibility checks cannot drift from apply mode.
        """

        context = self._retirement_migration_context(
            source_application_publication_id=source_application_publication_id,
            source_agent_publication_id=source_agent_publication_id,
            target_python_agent_publication_id=target_python_agent_publication_id,
            environment=environment,
            expected_application_revision=expected_application_revision,
            expected_deployment_revision=expected_deployment_revision,
        )
        target_runtime_kind = str(context["target_agent"].runtime_kind or "")
        if self.runtime_readiness_guard is not None:
            self.runtime_readiness_guard.require_ready(target_runtime_kind)
        if (
            validate_file_format_policy_version(
                context["source_publication"]["snapshot"].get("file_format_policy_version")
            )
            == "text-v2"
        ):
            cutover_errors = self.mcp_tool_composition_service.text_v2_cutover_errors()
            if cutover_errors:
                raise NonRetryableExecutionError(
                    "text-v2 cutover preflight found active legacy File MCP Jobs",
                    safe_message="text-v2 切换预检未通过",
                    error_code="validation_failed",
                    field_errors=cutover_errors,
                )
        try:
            return self._migrate_retired_typescript_publication(
                actor_id=actor_id,
                source_application_publication_id=source_application_publication_id,
                source_agent_publication_id=source_agent_publication_id,
                target_python_agent_publication_id=target_python_agent_publication_id,
                environment=environment,
                expected_application_revision=expected_application_revision,
                expected_deployment_revision=expected_deployment_revision,
                correlation_id=correlation_id,
                apply=apply,
            )
        except _RetirementMigrationDryRunRollback as rollback:
            return rollback.report

    @operation_unit_of_work(lambda service: service.repository.database)
    def _migrate_retired_typescript_publication(
        self,
        *,
        actor_id: str,
        source_application_publication_id: str,
        source_agent_publication_id: str,
        target_python_agent_publication_id: str,
        environment: str,
        expected_application_revision: int,
        expected_deployment_revision: int,
        correlation_id: str,
        apply: bool,
    ) -> dict[str, Any]:
        context = self._retirement_migration_context(
            source_application_publication_id=source_application_publication_id,
            source_agent_publication_id=source_agent_publication_id,
            target_python_agent_publication_id=target_python_agent_publication_id,
            environment=environment,
            expected_application_revision=expected_application_revision,
            expected_deployment_revision=expected_deployment_revision,
        )
        application = context["application"]
        source_publication = context["source_publication"]
        source_snapshot = dict(source_publication["snapshot"])
        target_agent = context["target_agent"]
        payload = self._retirement_migration_payload(
            source_snapshot=source_snapshot,
            target_agent_publication_id=target_agent.id,
        )
        revision = self.save_draft(
            actor_id=actor_id,
            code=str(application["code"]),
            expected_revision=expected_application_revision,
            payload=payload,
        )
        publication = self._publish(
            actor_id=actor_id,
            code=str(application["code"]),
            revision_id=str(revision["id"]),
        )
        deployment = self._activate_in_unit_of_work(
            actor_id=actor_id,
            code=str(application["code"]),
            environment=environment,
            publication_id=str(publication["id"]),
            expected_revision=expected_deployment_revision,
        )
        report = {
            "status": "migrated" if apply else "ready",
            "write_performed": apply,
            "application": {
                "id": application["id"],
                "code": application["code"],
                "environment": validate_environment(environment),
            },
            "source": {
                "application_publication_id": source_application_publication_id,
                "application_revision": source_publication["revision"],
                "application_config_hash": source_publication["config_hash"],
                "agent_publication_id": source_agent_publication_id,
                "runtime_kind": "typescript-v1",
            },
            "target": {
                "agent_publication_id": target_python_agent_publication_id,
                "agent_revision": target_agent.revision,
                "agent_config_hash": target_agent.config_hash,
                "runtime_kind": "python-v1",
                "application_revision": revision["revision"],
                "application_config_hash": revision["config_hash"],
                "application_publication_id": str(publication["id"]) if apply else "",
                "application_publication_hash": publication["config_hash"],
                "deployment_revision": deployment["revision"],
            },
            "correlation_id": correlation_id,
            "sensitive_values_exposed": False,
        }
        if not apply:
            raise _RetirementMigrationDryRunRollback(report)
        self.audit_service.record(
            "typescript_runtime.application_migrated",
            status="SUCCEEDED",
            summary="Business Application migrated from retired TypeScript Runtime",
            actor_id=actor_id,
            payload={
                "application_id": application["id"],
                "application_code": application["code"],
                "environment": validate_environment(environment),
                "source_application_publication_id": source_application_publication_id,
                "source_agent_publication_id": source_agent_publication_id,
                "target_agent_publication_id": target_python_agent_publication_id,
                "target_application_publication_id": publication["id"],
                "target_application_config_hash": publication["config_hash"],
                "expected_application_revision": expected_application_revision,
                "expected_deployment_revision": expected_deployment_revision,
                "correlation_id": correlation_id,
                "result": "migrated",
            },
        )
        return report

    def _retirement_migration_context(
        self,
        *,
        source_application_publication_id: str,
        source_agent_publication_id: str,
        target_python_agent_publication_id: str,
        environment: str,
        expected_application_revision: int,
        expected_deployment_revision: int,
    ) -> dict[str, Any]:
        normalized_environment = validate_environment(environment)
        source_publication = self._verified_publication(source_application_publication_id)
        application = self.repository.get_by_id(str(source_publication["application_id"]))
        if int(application["revision"]) != expected_application_revision:
            raise self.repository.revision_conflict(int(application["revision"]))
        source_revision = self.repository.get_revision(str(source_publication["revision_id"]))
        source_snapshot = dict(source_publication["snapshot"])
        source_snapshot_agent = dict(source_snapshot.get("agent") or {})
        source_snapshot_application = dict(source_snapshot.get("application") or {})
        if (
            str(source_revision.get("agent_publication_id") or "") != source_agent_publication_id
            or str(source_snapshot_agent.get("id") or "") != source_agent_publication_id
        ):
            raise NonRetryableExecutionError(
                "Source Application publication does not reference the exact Agent publication",
                safe_message="源应用发布版本与源 Agent 发布版本不匹配",
                error_code="retirement_migration_source_reference_mismatch",
            )
        if str(source_snapshot_application.get("id") or "") != str(application["id"]):
            raise NonRetryableExecutionError(
                "Source Application publication ownership is inconsistent",
                safe_message="源应用发布版本归属不一致",
                error_code="retirement_migration_source_integrity_error",
            )
        source_agent = self.agent_reader.resolve(source_agent_publication_id)
        if str(source_agent.runtime_kind or "") != "typescript-v1":
            raise NonRetryableExecutionError(
                "Source Agent publication is not a retired TypeScript publication",
                safe_message="源 Agent 发布版本不是已退役的 TypeScript 版本",
                error_code="retirement_migration_source_runtime_mismatch",
            )
        target_agent = self.agent_reader.resolve(target_python_agent_publication_id)
        _require_python_agent_publication(target_agent)
        if source_agent.id == target_agent.id:
            raise NonRetryableExecutionError(
                "Source and target Agent publications must differ",
                safe_message="源和目标 Agent 发布版本不能相同",
                error_code="retirement_migration_target_invalid",
            )
        deployment = self.repository.get_deployment(str(application["id"]), normalized_environment)
        if (
            deployment is None
            or not bool(deployment["active"])
            or str(deployment["publication_id"]) != source_application_publication_id
        ):
            raise NonRetryableExecutionError(
                "Active deployment does not reference the exact source publication",
                safe_message="活动部署与指定的源应用发布版本不匹配",
                error_code="retirement_migration_deployment_mismatch",
            )
        if int(deployment["revision"]) != expected_deployment_revision:
            raise self.repository.revision_conflict(int(deployment["revision"]))
        return {
            "application": application,
            "source_publication": source_publication,
            "source_agent": source_agent,
            "target_agent": target_agent,
            "deployment": deployment,
        }

    @staticmethod
    def _retirement_migration_payload(
        *,
        source_snapshot: dict[str, Any],
        target_agent_publication_id: str,
    ) -> dict[str, Any]:
        workflow = dict(source_snapshot.get("workflow") or {})
        return {
            "agent_publication_id": target_agent_publication_id,
            "workflow_publication_id": str(workflow.get("id") or ""),
            "task_workspace_retention_period": source_snapshot.get(
                "task_workspace_retention_period"
            ),
            "file_format_policy_version": source_snapshot.get("file_format_policy_version"),
            "task_file_features": dict(source_snapshot.get("task_file_features") or {}),
            "session_policy": dict(source_snapshot.get("session_policy") or {}),
            "execution_policy": dict(source_snapshot.get("execution_policy") or {}),
            "triggers": [
                {
                    key: value
                    for key, value in dict(trigger).items()
                    if key
                    in {
                        "trigger_type",
                        "connector_id",
                        "routing_key",
                        "actor_policy",
                        "service_account_user_id",
                        "enabled",
                        "config",
                    }
                }
                for trigger in source_snapshot.get("triggers") or []
            ],
            "deliveries": [
                {
                    key: value
                    for key, value in dict(delivery).items()
                    if key
                    in {
                        "delivery_type",
                        "connector_id",
                        "enabled",
                        "config",
                    }
                }
                for delivery in source_snapshot.get("deliveries") or []
            ],
            "mcp_tools": list(source_snapshot.get("mcp_tools") or []),
        }

    @operation_unit_of_work(lambda service: service.repository.database)
    def _activate_in_unit_of_work(
        self,
        *,
        actor_id: str,
        code: str,
        environment: str,
        publication_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        normalized_code = validate_code(code)
        normalized_environment = validate_environment(environment)
        self._require(actor_id, normalized_code, "activate")
        application = self.repository.get_by_code(normalized_code)
        if str(application["status"]) != "enabled":
            raise NonRetryableExecutionError(
                "Business Application is not enabled",
                safe_message="只有已启用的业务应用才能激活",
                error_code="invalid_lifecycle",
            )
        publication = self._verified_publication(publication_id)
        if str(publication["application_id"]) != str(application["id"]):
            raise NotFound(
                "Business Application publication not found",
                safe_message="未找到业务应用发布版本",
            )
        self._require_python_application_publication(publication)
        activation_errors = self.runtime_evaluator.activation_errors(dict(publication["snapshot"]))
        if (
            self.runtime_evaluator.data_plane_enabled
            and normalize_deployment_environment(normalized_environment)
            == self.runtime_evaluator.runtime_environment
            and activation_errors
        ):
            raise NonRetryableExecutionError(
                "Business Application runtime preflight failed",
                safe_message="业务应用运行配置无法执行",
                error_code="validation_failed",
                field_errors=activation_errors,
            )
        routes = [
            {
                "trigger_type": str(trigger["trigger_type"]),
                "connector_id": str(trigger["connector_id"]),
                "normalized_routing_key": str(trigger["normalized_routing_key"]),
            }
            for trigger in publication["snapshot"].get("triggers", [])
            if bool(trigger.get("enabled", True))
        ]
        old = self.repository.get_deployment(str(application["id"]), normalized_environment)
        deployment = self.repository.activate(
            application_id=str(application["id"]),
            environment=normalized_environment,
            publication_id=publication_id,
            expected_revision=expected_revision,
            actor_id=actor_id,
            routes=routes,
        )
        readiness = self.runtime_evaluator.evaluate(
            snapshot=dict(publication["snapshot"]),
            deployment=deployment,
        )
        event = "activated"
        if old and old.get("publication_id") and old.get("publication_id") != publication_id:
            try:
                old_publication = self.repository.get_publication(str(old["publication_id"]))
                if int(publication["revision"]) < int(old_publication["revision"]):
                    event = "rolled_back"
            except Exception:
                event = "activated"
        self._audit(
            event,
            actor_id,
            application,
            publication=publication,
            environment=normalized_environment,
            previous_publication_id=str((old or {}).get("publication_id") or ""),
            readiness=readiness,
        )
        return {**deployment, **readiness.to_dict()}

    @operation_unit_of_work(lambda service: service.repository.database)
    def deactivate(
        self,
        *,
        actor_id: str,
        code: str,
        environment: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        normalized_code = validate_code(code)
        normalized_environment = validate_environment(environment)
        self._require(actor_id, normalized_code, "activate")
        application = self.repository.get_by_code(normalized_code)
        old = self.repository.get_deployment(str(application["id"]), normalized_environment)
        deployment = self.repository.deactivate(
            application_id=str(application["id"]),
            environment=normalized_environment,
            expected_revision=expected_revision,
            actor_id=actor_id,
        )
        readiness = self.runtime_evaluator.evaluate(snapshot=None, deployment=deployment)
        self._audit(
            "deactivated",
            actor_id,
            application,
            environment=normalized_environment,
            previous_publication_id=str((old or {}).get("publication_id") or ""),
            readiness=readiness,
        )
        return {**deployment, **readiness.to_dict()}

    def publications(self, *, actor_id: str, code: str) -> list[dict[str, Any]]:
        application = self.repository.get_by_code(validate_code(code))
        self._require(actor_id, code, "read")
        deployments = self.repository.list_deployments(str(application["id"]))
        return [
            self._publication_with_readiness(publication, deployments)
            for publication in self.repository.list_publications(str(application["id"]))
        ]

    def catalog(self, *, actor_id: str, code: str) -> dict[str, Any]:
        application = self.repository.get_by_code(validate_code(code))
        self._require(actor_id, code, "read")
        project_code = str(application["project_code"])

        def reference(item: ComponentReference) -> dict[str, Any]:
            return {
                key: value for key, value in vars(item).items() if value is not None and value != ()
            }

        agents = [
            reference(item)
            for item in self.agent_reader.catalog(project_code)
            if item.runtime_kind == WRITABLE_AGENT_RUNTIME_KIND
        ]
        mcp_tool_catalog = self.mcp_tool_composition_service.management_catalog(
            agent_publication_ids=[str(item["id"]) for item in agents],
        )
        return {
            "agents": agents,
            "workflows": [reference(item) for item in self.workflow_reader.catalog(project_code)],
            "connectors": [reference(item) for item in self.connector_reader.catalog()],
            "document_processing_profiles": self._document_processing_profile_catalog(),
            **mcp_tool_catalog,
        }

    def _validate_revision(
        self, application: dict[str, Any], revision: dict[str, Any]
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        errors: list[dict[str, str]] = []
        components: dict[str, Any] = {}
        if str(application["status"]) != "enabled":
            errors.append({"field": "status", "message": "业务应用必须处于启用状态"})
        agent = self._resolve_component(
            errors,
            "agent_publication_id",
            lambda: self.agent_reader.resolve(str(revision["agent_publication_id"])),
        )
        if agent:
            components["agent"] = agent
            self._validate_component_scope(errors, application, agent, "agent_publication_id")
            if agent.runtime_kind != WRITABLE_AGENT_RUNTIME_KIND:
                errors.append(
                    {
                        "field": "agent_publication_id",
                        "message": "TypeScript Agent Runtime 已退役，请选择 Python Publication",
                    }
                )
        workflow_id = str(revision.get("workflow_publication_id") or "")
        if workflow_id:
            workflow = self._resolve_component(
                errors,
                "workflow_publication_id",
                lambda: self.workflow_reader.resolve(workflow_id),
            )
            if workflow:
                components["workflow"] = workflow
                self._validate_component_scope(
                    errors, application, workflow, "workflow_publication_id"
                )
        components["triggers"] = []
        for index, trigger in enumerate(revision["triggers"]):
            if not trigger["enabled"]:
                continue
            reference = self._resolve_component(
                errors,
                f"triggers.{index}.connector_id",
                lambda trigger=trigger: self.connector_reader.resolve(
                    str(trigger["connector_id"]),
                    "ingress",
                    str(trigger["trigger_type"]),
                ),
            )
            if reference:
                components["triggers"].append(reference)
            if str(trigger["actor_policy"]) == "SERVICE_ACCOUNT":
                account = self._resolve_component(
                    errors,
                    f"triggers.{index}.service_account_user_id",
                    lambda trigger=trigger: self.identity_reader.resolve_service_account(
                        str(trigger["service_account_user_id"])
                    ),
                )
                if account:
                    components.setdefault("actors", []).append(account)
        components["deliveries"] = []
        for index, delivery in enumerate(revision["deliveries"]):
            if not delivery["enabled"]:
                continue
            direction = (
                "ingress" if str(delivery["delivery_type"]) == "reply_original" else "delivery"
            )
            reference = self._resolve_component(
                errors,
                f"deliveries.{index}.connector_id",
                lambda delivery=delivery, direction=direction: self.connector_reader.resolve(
                    str(delivery["connector_id"]), direction
                ),
            )
            if reference:
                components["deliveries"].append(reference)
        if agent is None and not str(revision.get("agent_publication_id") or ""):
            errors.append({"field": "agent_publication_id", "message": "必须选择 Agent 发布版本"})
        errors.extend(
            self.mcp_tool_composition_service.file_feature_errors(
                agent_publication_id=str(revision.get("agent_publication_id") or ""),
                task_file_features=validate_task_file_features(revision.get("task_file_features")),
                selected_tools=list(revision.get("mcp_tools") or []),
            )
        )
        errors.extend(
            self._file_policy_compatibility_errors(
                file_format_policy_version=validate_file_format_policy_version(
                    revision.get("file_format_policy_version")
                ),
                task_file_features=validate_task_file_features(revision.get("task_file_features")),
                agent=agent,
            )
        )
        try:
            document_processing_profile_code = validate_document_processing_profile_code(
                revision.get("document_processing_profile_code")
            )
        except NonRetryableExecutionError as exc:
            errors.extend(exc.field_errors)
            document_processing_profile_code = DocumentProcessingProfileCode.NONE.value
        errors.extend(
            self._document_processing_compatibility_errors(
                document_processing_profile_code=document_processing_profile_code,
                task_file_features=validate_task_file_features(
                    revision.get("task_file_features")
                ),
                session_policy=validate_session_policy(
                    dict(revision.get("session_policy") or {})
                ),
                agent=agent,
            )
        )
        if (
            validate_file_format_policy_version(revision.get("file_format_policy_version"))
            == "text-v2"
        ):
            errors.extend(self.mcp_tool_composition_service.text_v2_cutover_errors())
        return errors, components

    @staticmethod
    def _document_processing_compatibility_errors(
        *,
        document_processing_profile_code: str,
        task_file_features: dict[str, bool],
        session_policy: dict[str, Any],
        agent: ComponentReference | None,
    ) -> list[dict[str, str]]:
        if document_processing_profile_code == DocumentProcessingProfileCode.NONE.value:
            return []
        errors: list[dict[str, str]] = []
        if not task_file_features.get("workspace_enabled"):
            errors.append(
                {
                    "field": "task_file_features.workspace_enabled",
                    "message": "Docling 文档处理必须启用任务工作区",
                }
            )
        if not task_file_features.get("file_mcp_enabled"):
            errors.append(
                {
                    "field": "task_file_features.file_mcp_enabled",
                    "message": "Docling 文档处理必须启用 File MCP",
                }
            )
        if not session_policy.get("attachments_enabled"):
            errors.append(
                {
                    "field": "session_policy.attachments_enabled",
                    "message": "Docling 文档处理必须允许消息附件",
                }
            )
        if not session_policy.get("continuous_conversation_enabled"):
            errors.append(
                {
                    "field": "session_policy.continuous_conversation_enabled",
                    "message": "Docling 文档处理必须启用连续会话",
                }
            )
        if agent is None or "1.3" not in agent.runtime_protocol_versions:
            errors.append(
                {
                    "field": "agent_publication_id",
                    "message": "所选 Agent 发布版本不支持 Docling 文件上下文 Runtime 能力",
                }
            )
        return errors

    @staticmethod
    def _file_policy_compatibility_errors(
        *,
        file_format_policy_version: str,
        task_file_features: dict[str, bool],
        agent: ComponentReference | None,
    ) -> list[dict[str, str]]:
        if file_format_policy_version != "text-v2":
            return []
        errors: list[dict[str, str]] = []
        if not task_file_features.get("workspace_enabled"):
            errors.append(
                {
                    "field": "file_format_policy_version",
                    "message": "text-v2 只能用于已启用的任务工作区",
                }
            )
        if not task_file_features.get("file_mcp_enabled"):
            errors.append(
                {
                    "field": "task_file_features.file_mcp_enabled",
                    "message": "text-v2 必须启用 File MCP 并冻结精确 Tool schema",
                }
            )
        if agent is None or "1.3" not in agent.runtime_protocol_versions:
            errors.append(
                {
                    "field": "agent_publication_id",
                    "message": "所选 Agent 发布版本未声明支持 Runtime protocol v1.3",
                }
            )
        return errors

    @staticmethod
    def _resolve_component(
        errors: list[dict[str, str]], field: str, resolve: Any
    ) -> ComponentReference | None:
        try:
            reference = resolve()
        except Exception as exc:
            field_errors = getattr(exc, "field_errors", [])
            errors.extend(field_errors or [{"field": field, "message": "组件不可用"}])
            return None
        if reference.status != "enabled":
            errors.append({"field": field, "message": "组件已停用"})
            return None
        return reference if isinstance(reference, ComponentReference) else None

    @staticmethod
    def _validate_component_scope(
        errors: list[dict[str, str]],
        application: dict[str, Any],
        component: ComponentReference,
        field: str,
    ) -> None:
        if component.project_code and component.project_code != str(application["project_code"]):
            errors.append({"field": field, "message": "组件项目范围冲突"})

    def _snapshot(
        self,
        application: dict[str, Any],
        revision: dict[str, Any],
        components: dict[str, Any],
    ) -> dict[str, Any]:
        def component(value: ComponentReference | None) -> dict[str, Any] | None:
            if value is None:
                return None
            return {
                "id": value.id,
                "code": value.code,
                "revision": value.revision,
                "project_code": value.project_code,
                "config_hash": value.config_hash,
                **({"runtime_kind": value.runtime_kind} if value.runtime_kind else {}),
                **(
                    {"runtime_protocol_versions": list(value.runtime_protocol_versions)}
                    if value.runtime_protocol_versions
                    else {}
                ),
            }

        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "application": {
                "id": application["id"],
                "code": application["code"],
                "name": application["name"],
                "description": application["description"],
                "project_code": application["project_code"],
                "owner_user_id": application["owner_user_id"],
            },
            "revision": int(revision["revision"]),
            "agent": component(components.get("agent")),
            "workflow": component(components.get("workflow")),
            "task_workspace_retention_period": str(
                revision.get("task_workspace_retention_period") or "WEEK"
            ),
            "file_format_policy_version": validate_file_format_policy_version(
                revision.get("file_format_policy_version")
            ),
            "document_processing_profile": document_processing_profile_snapshot(
                revision.get("document_processing_profile_code")
            ),
            "task_file_features": validate_task_file_features(revision.get("task_file_features")),
            "session_policy": revision["session_policy"],
            "execution_policy": revision["execution_policy"],
            "triggers": [
                {
                    "trigger_type": item["trigger_type"],
                    "connector_id": item["connector_id"],
                    "routing_key": item["routing_key"],
                    "normalized_routing_key": item["normalized_routing_key"],
                    "actor_policy": item["actor_policy"],
                    "service_account_user_id": item["service_account_user_id"],
                    "enabled": item["enabled"],
                    "config": item["config"],
                }
                for item in revision["triggers"]
            ],
            "deliveries": [
                {
                    "delivery_type": item["delivery_type"],
                    "connector_id": item["connector_id"],
                    "enabled": item["enabled"],
                    "config": item["config"],
                }
                for item in revision["deliveries"]
            ],
            "mcp_tools": list(revision.get("mcp_tools") or []),
        }
        reject_dangerous_content(snapshot)
        canonical_json(snapshot)
        return snapshot

    def _verified_publication(self, publication_id: str) -> dict[str, Any]:
        publication = self.repository.get_publication(publication_id)
        if not verify_publication_snapshot(
            dict(publication["snapshot"]),
            schema_version=int(publication["schema_version"]),
            expected_hash=str(publication["config_hash"]),
        ):
            raise NonRetryableExecutionError(
                "Business Application publication integrity check failed",
                safe_message="业务应用发布版本完整性校验失败",
                error_code="integrity_error",
            )
        return publication

    def _require_python_application_publication(
        self,
        publication: dict[str, Any],
    ) -> None:
        agent = dict(publication["snapshot"].get("agent") or {})
        runtime_kind = str(agent.get("runtime_kind") or "")
        if not runtime_kind and agent.get("id"):
            runtime_kind = str(self.agent_reader.resolve(str(agent["id"])).runtime_kind or "")
        _require_python_runtime_kind(runtime_kind)

    @staticmethod
    def _validate_metadata(name: str, description: str, owner_user_id: str) -> None:
        if not name.strip() or len(name.strip()) > 200:
            raise NonRetryableExecutionError(
                "Business Application name is invalid",
                safe_message="业务应用元数据无效",
                error_code="validation_failed",
                field_errors=[{"field": "name", "message": "必须填写名称且长度不能超出限制"}],
            )
        if len(description) > 4000 or len(owner_user_id) > 200:
            raise NonRetryableExecutionError(
                "Business Application metadata is too long",
                safe_message="业务应用元数据无效",
                error_code="validation_failed",
                field_errors=[{"field": "description", "message": "元数据过长"}],
            )

    def _require(self, actor_id: str, code: str, action: str) -> None:
        self.authorization.require(
            user_id=actor_id,
            resource_type="business_application",
            resource_code=code,
            action=action,
        )

    def _audit(
        self,
        event: str,
        actor_id: str,
        application: dict[str, Any],
        *,
        revision: dict[str, Any] | None = None,
        publication: dict[str, Any] | None = None,
        environment: str = "",
        previous_publication_id: str = "",
        readiness: RuntimeReadiness | None = None,
    ) -> None:
        readiness = readiness or self._runtime_for_application(application)
        self.audit_service.record(
            f"business_application.{event}",
            status="SUCCEEDED",
            summary=f"Business Application {event}",
            actor_id=actor_id,
            payload={
                "application_code": application["code"],
                "application_revision": application["revision"],
                "revision_id": (revision or {}).get("id", ""),
                "publication_id": (publication or {}).get("id", ""),
                "config_hash": (publication or revision or {}).get("config_hash", ""),
                "task_workspace_retention_period": (publication or revision or {}).get(
                    "task_workspace_retention_period", "WEEK"
                ),
                "file_format_policy_version": (publication or revision or {}).get(
                    "file_format_policy_version", "text-v1"
                ),
                "document_processing_profile_code": (
                    publication or revision or {}
                ).get("document_processing_profile_code", "NONE"),
                "task_file_features": (publication or revision or {}).get(
                    "task_file_features", validate_task_file_features(None)
                ),
                "environment": environment,
                "previous_publication_id": previous_publication_id,
                **readiness.to_dict(),
            },
        )
        if event in {"activated", "rolled_back", "deactivated"}:
            self.audit_service.record(
                f"business_application.runtime.{event}",
                status="SUCCEEDED",
                summary=f"Business Application runtime {event}",
                actor_id=actor_id,
                payload={
                    "application_code": application["code"],
                    "publication_id": (publication or {}).get("id", ""),
                    "previous_publication_id": previous_publication_id,
                    "environment": environment,
                    **readiness.to_dict(),
                },
            )

    def _summary(self, application: dict[str, Any]) -> dict[str, Any]:
        active_environments = sorted(
            str(deployment["environment"])
            for deployment in self.repository.list_deployments(str(application["id"]))
            if deployment["active"]
        )
        readiness = self._runtime_for_application(application)
        return {
            "id": application["id"],
            "code": application["code"],
            "name": application["name"],
            "description": application["description"],
            "project_code": application["project_code"],
            "owner_user_id": application["owner_user_id"],
            "status": application["status"],
            "revision": application["revision"],
            "latest_publication_revision": application.get("latest_publication_revision"),
            "active_environments": active_environments,
            "task_workspace_retention_period": str(
                application.get("task_workspace_retention_period")
                or (application.get("draft") or {}).get("task_workspace_retention_period", "WEEK")
            ),
            "file_format_policy_version": validate_file_format_policy_version(
                application.get("file_format_policy_version")
                or (application.get("draft") or {}).get("file_format_policy_version")
            ),
            "document_processing_profile_code": validate_document_processing_profile_code(
                application.get("document_processing_profile_code")
                or (application.get("draft") or {}).get(
                    "document_processing_profile_code"
                )
            ),
            **document_processing_state(
                application.get("document_processing_profile_code")
                or (application.get("draft") or {}).get(
                    "document_processing_profile_code"
                )
            ),
            **readiness.to_dict(),
        }

    def _detail(self, application: dict[str, Any]) -> dict[str, Any]:
        readiness = self._runtime_for_application(application)
        deployments = [
            self._deployment_with_readiness(value)
            for value in application.get("deployments")
            or self.repository.list_deployments(str(application["id"]))
        ]
        publications = [
            self._publication_with_readiness(value, deployments)
            for value in application.get("publications")
            or self.repository.list_publications(str(application["id"]))
        ]
        return {
            **application,
            "draft": (
                self._revision_with_document_processing(application["draft"])
                if isinstance(application.get("draft"), dict)
                else None
            ),
            "publications": publications,
            "deployments": deployments,
            **readiness.to_dict(),
        }

    def _snapshot_summary(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        file_format_policy_version = validate_file_format_policy_version(
            snapshot.get("file_format_policy_version")
        )
        document_profile, document_profile_source = (
            publication_document_processing_profile(snapshot)
        )
        return {
            "schema_version": snapshot.get("schema_version"),
            "application": snapshot.get("application"),
            "revision": snapshot.get("revision"),
            "agent": snapshot.get("agent"),
            "workflow": snapshot.get("workflow"),
            "trigger_count": len(snapshot.get("triggers") or []),
            "delivery_count": len(snapshot.get("deliveries") or []),
            "mcp_tool_count": len(snapshot.get("mcp_tools") or []),
            "task_workspace_retention_period": str(
                snapshot.get("task_workspace_retention_period") or "WEEK"
            ),
            "file_format_policy_version": file_format_policy_version,
            "file_format_policy_source": (
                "publication_snapshot"
                if "file_format_policy_version" in snapshot
                else "legacy_default"
            ),
            "document_processing_profile": document_profile,
            "document_processing_profile_code": document_profile["code"],
            "document_processing_profile_version": document_profile["version"],
            "document_processing_profile_hash": document_profile["hash"],
            "document_processing_profile_source": document_profile_source,
            **document_processing_state(document_profile["code"]),
            "task_file_features": validate_task_file_features(snapshot.get("task_file_features")),
            "file_format_compatibility": self._file_format_compatibility(
                snapshot,
                policy_version=file_format_policy_version,
            ),
            "task_workspace_retention_source": (
                "publication_snapshot"
                if "task_workspace_retention_period" in snapshot
                else "legacy_default"
            ),
            "runtime_readiness": self.runtime_evaluator.evaluate(
                snapshot=snapshot,
                deployment=None,
            ).to_dict(),
            "retirement_status": (
                "retired"
                if str((snapshot.get("agent") or {}).get("runtime_kind") or "") == "typescript-v1"
                else "supported"
            ),
        }

    @staticmethod
    def _file_format_compatibility(
        snapshot: dict[str, Any], *, policy_version: str
    ) -> dict[str, Any]:
        if policy_version == "text-v1":
            return {
                "status": "READY",
                "required_runtime_protocol": "1.2-or-earlier",
                "runtime_protocol_compatible": True,
                "file_mcp_schema_compatible": True,
            }
        agent_value = snapshot.get("agent")
        agent = agent_value if isinstance(agent_value, dict) else {}
        protocols = {str(value) for value in agent.get("runtime_protocol_versions") or []}
        features = validate_task_file_features(snapshot.get("task_file_features"))
        required_tools = required_file_mcp_tools(features)
        selected_tools = {
            str(item.get("tool_identifier") or ""): str(item.get("schema_hash") or "")
            for item in snapshot.get("mcp_tools") or []
            if isinstance(item, dict) and str(item.get("server_code") or "") == "file-service"
        }
        schema_compatible = bool(required_tools) and all(
            identifier in MCP_TOOL_MANIFEST
            and selected_tools.get(identifier) == MCP_TOOL_MANIFEST[identifier].schema_hash
            for identifier in required_tools
        )
        runtime_compatible = "1.3" in protocols
        return {
            "status": ("READY" if runtime_compatible and schema_compatible else "INCOMPATIBLE"),
            "required_runtime_protocol": "1.3",
            "runtime_protocol_compatible": runtime_compatible,
            "file_mcp_schema_compatible": schema_compatible,
        }

    def _deployment_with_readiness(self, deployment: dict[str, Any]) -> dict[str, Any]:
        snapshot: dict[str, Any] | None = None
        if deployment.get("publication_id"):
            try:
                snapshot = dict(
                    self._verified_publication(str(deployment["publication_id"]))["snapshot"]
                )
            except Exception:
                readiness = self.runtime_evaluator.blocked_integrity(
                    deployment_environment=str(deployment.get("environment") or "")
                )
                return {**deployment, **readiness.to_dict()}
        readiness = self.runtime_evaluator.evaluate(
            snapshot=snapshot,
            deployment=deployment,
        )
        return {**deployment, **readiness.to_dict()}

    def _publication_with_readiness(
        self,
        publication: dict[str, Any],
        deployments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        deployment = next(
            (
                value
                for value in deployments
                if bool(value.get("active"))
                and str(value.get("publication_id") or "") == str(publication["id"])
                and normalize_deployment_environment(str(value.get("environment") or ""))
                == self.runtime_evaluator.runtime_environment
            ),
            None,
        )
        snapshot = dict(publication["snapshot"])
        if not verify_publication_snapshot(
            snapshot,
            schema_version=int(publication.get("schema_version") or 0),
            expected_hash=str(publication.get("config_hash") or ""),
        ):
            readiness = self.runtime_evaluator.blocked_integrity(
                deployment_environment=str((deployment or {}).get("environment") or "")
            )
        else:
            readiness = self.runtime_evaluator.evaluate(
                snapshot=snapshot,
                deployment=deployment,
            )
        snapshot_summary = self._snapshot_summary(snapshot)
        return {
            **publication,
            "snapshot": snapshot_summary,
            "retirement_status": snapshot_summary["retirement_status"],
            "file_format_compatibility": snapshot_summary["file_format_compatibility"],
            "document_processing_profile_code": snapshot_summary[
                "document_processing_profile_code"
            ],
            "document_processing_profile_version": snapshot_summary[
                "document_processing_profile_version"
            ],
            "document_processing_profile_hash": snapshot_summary[
                "document_processing_profile_hash"
            ],
            "document_processing_profile_source": snapshot_summary[
                "document_processing_profile_source"
            ],
            "document_processing_status": snapshot_summary[
                "document_processing_status"
            ],
            "document_processing_reason_code": snapshot_summary[
                "document_processing_reason_code"
            ],
            **readiness.to_dict(),
        }

    @staticmethod
    def _revision_with_document_processing(revision: dict[str, Any]) -> dict[str, Any]:
        code = validate_document_processing_profile_code(
            revision.get("document_processing_profile_code")
        )
        return {
            **revision,
            "document_processing_profile_code": code,
            **document_processing_state(code),
        }

    @staticmethod
    def _publication_document_processing(
        publication: dict[str, Any],
    ) -> dict[str, Any]:
        profile, source = publication_document_processing_profile(
            dict(publication.get("snapshot") or {})
        )
        return {
            **publication,
            "document_processing_profile_code": profile["code"],
            "document_processing_profile_version": profile["version"],
            "document_processing_profile_hash": profile["hash"],
            "document_processing_profile_source": source,
            **document_processing_state(profile["code"]),
        }

    @staticmethod
    def _document_processing_profile_catalog() -> list[dict[str, Any]]:
        return [
            {
                "code": DocumentProcessingProfileCode.NONE.value,
                "version": "",
                "hash": "",
                "label": "关闭文档处理",
                "source_format_codes": [],
                "output_kinds": [],
                **document_processing_state(DocumentProcessingProfileCode.NONE.value),
            },
            {
                "code": DOCLING_TEXT_V1.code.value,
                "version": DOCLING_TEXT_V1.version,
                "hash": DOCLING_TEXT_V1.profile_hash,
                "label": "Docling 文字提取 v1",
                "source_format_codes": [
                    item.code.value for item in DOCLING_TEXT_V1.source_formats
                ],
                "output_kinds": list(DOCLING_TEXT_V1.output_kinds),
                "limits": {
                    "max_source_bytes": DOCLING_TEXT_V1.max_source_bytes,
                    "max_pdf_pages": DOCLING_TEXT_V1.max_pdf_pages,
                    "processing_timeout_seconds": (
                        DOCLING_TEXT_V1.processing_timeout_seconds
                    ),
                },
                **document_processing_state(DOCLING_TEXT_V1.code.value),
            },
            {
                "code": DOCLING_LAYOUT_OCR_V1.code.value,
                "version": DOCLING_LAYOUT_OCR_V1.version,
                "hash": DOCLING_LAYOUT_OCR_V1.profile_hash,
                "label": "Docling Office 内嵌图片布局 OCR v1",
                "source_format_codes": [
                    item.code.value for item in DOCLING_LAYOUT_OCR_V1.source_formats
                ],
                "output_kinds": list(DOCLING_LAYOUT_OCR_V1.output_kinds),
                "limits": {
                    "max_source_bytes": DOCLING_LAYOUT_OCR_V1.max_source_bytes,
                    "max_pdf_pages": DOCLING_LAYOUT_OCR_V1.max_pdf_pages,
                    "processing_timeout_seconds": (
                        DOCLING_LAYOUT_OCR_V1.processing_timeout_seconds
                    ),
                },
                "capabilities": {
                    "office_embedded_image_ocr": True,
                    "coordinates": "TOPLEFT_0_10000",
                    "reading_order": True,
                    "confidence": True,
                    "bounded_geometric_relations": True,
                    "vlm": False,
                    "visual_semantics": False,
                },
                **document_processing_state(DOCLING_LAYOUT_OCR_V1.code.value),
            },
        ]

    def _runtime_for_application(self, application: dict[str, Any]) -> RuntimeReadiness:
        deployment = next(
            (
                value
                for value in application.get("deployments")
                or self.repository.list_deployments(str(application["id"]))
                if bool(value.get("active"))
                and normalize_deployment_environment(str(value.get("environment") or ""))
                == self.runtime_evaluator.runtime_environment
            ),
            None,
        )
        if deployment is None:
            return self.runtime_evaluator.empty()
        try:
            publication = self._verified_publication(str(deployment.get("publication_id") or ""))
        except Exception:
            return self.runtime_evaluator.blocked_integrity(
                deployment_environment=str(deployment.get("environment") or "")
            )
        return self.runtime_evaluator.evaluate(
            snapshot=dict(publication["snapshot"]),
            deployment=deployment,
        )


class BusinessApplicationResolver:
    def __init__(
        self,
        repository: BusinessApplicationRepository,
        runtime_evaluator: RuntimeReadinessEvaluator | None = None,
    ) -> None:
        self.repository = repository
        self.runtime_evaluator = runtime_evaluator or RuntimeReadinessEvaluator(
            data_plane_enabled=False,
            runtime_environment="local",
        )

    def resolve_active(self, application_code: str, environment: str) -> dict[str, Any]:
        application = self.repository.get_by_code(validate_code(application_code))
        if str(application["status"]) != "enabled":
            raise self.configuration_error("Business Application is not enabled")
        deployment = self.repository.get_deployment(
            str(application["id"]), validate_environment(environment)
        )
        if deployment is None or not deployment["active"] or not deployment["publication_id"]:
            raise self.configuration_error("Business Application is not active")
        publication = self._verified(str(deployment["publication_id"]))
        readiness = self.runtime_evaluator.evaluate(
            snapshot=dict(publication["snapshot"]),
            deployment=deployment,
        )
        return {
            "application": {
                "id": application["id"],
                "code": application["code"],
                "project_code": application["project_code"],
            },
            "deployment": {**deployment, **readiness.to_dict()},
            "publication": {**publication, **readiness.to_dict()},
            **readiness.to_dict(),
        }

    def resolve_trigger(
        self,
        environment: str,
        trigger_type: str,
        connector_id: str,
        routing_key: str,
    ) -> dict[str, Any]:
        resolution = self.resolve_route(
            environment,
            trigger_type,
            connector_id,
            routing_key,
        )
        if resolution.outcome == RouteResolutionOutcome.NOT_MATCHED:
            raise self.configuration_error(
                "No active Business Application route",
                error_code=RuntimeReason.ROUTE_NOT_MATCHED.value,
            )
        if resolution.outcome == RouteResolutionOutcome.BLOCKED:
            raise self.configuration_error(
                resolution.message,
                error_code=resolution.reason_code,
            )
        return resolution.to_dict()

    def resolve_trigger_optional(
        self,
        environment: str,
        trigger_type: str,
        connector_id: str,
        routing_key: str,
    ) -> dict[str, Any] | None:
        resolution = self.resolve_route(
            environment,
            trigger_type,
            connector_id,
            routing_key,
        )
        if resolution.outcome == RouteResolutionOutcome.NOT_MATCHED:
            return None
        if resolution.outcome == RouteResolutionOutcome.BLOCKED:
            raise self.configuration_error(
                resolution.message,
                error_code=resolution.reason_code,
            )
        return resolution.to_dict()

    def resolve_route(
        self,
        environment: str,
        trigger_type: str,
        connector_id: str,
        routing_key: str,
    ) -> RuntimeRouteResolution:
        normalized_environment = validate_environment(environment)
        route = self.repository.find_route(
            environment=normalized_environment,
            trigger_type=trigger_type,
            connector_id=connector_id,
            normalized_routing_key=normalize_routing_key(routing_key),
        )
        if route is None:
            readiness = self.runtime_evaluator.empty(reason=RuntimeReason.ROUTE_NOT_MATCHED)
            return RuntimeRouteResolution(
                outcome=RouteResolutionOutcome.NOT_MATCHED,
                reason_code=RuntimeReason.ROUTE_NOT_MATCHED.value,
                message="No active Business Application route matched",
                readiness=readiness,
            )
        application = self.repository.get_by_id(str(route["application_id"]))
        deployment = self.repository.get_deployment(str(application["id"]), normalized_environment)
        if (
            str(application.get("status") or "") != "enabled"
            or deployment is None
            or not bool(deployment.get("active"))
        ):
            readiness = self.runtime_evaluator.blocked_integrity(
                deployment_environment=normalized_environment
            )
            return RuntimeRouteResolution(
                outcome=RouteResolutionOutcome.BLOCKED,
                reason_code=RuntimeReason.PUBLICATION_INTEGRITY_ERROR.value,
                message="Business Application is not active",
                readiness=readiness,
                application=self._application_summary(application),
                deployment=deployment,
                route=self._safe_route(route),
            )
        try:
            publication = self._verified(str(deployment["publication_id"]))
        except Exception:
            readiness = self.runtime_evaluator.blocked_integrity(
                deployment_environment=normalized_environment
            )
            return RuntimeRouteResolution(
                outcome=RouteResolutionOutcome.BLOCKED,
                reason_code=RuntimeReason.PUBLICATION_INTEGRITY_ERROR.value,
                message="Business Application publication integrity check failed",
                readiness=readiness,
                application=self._application_summary(application),
                deployment=deployment,
                route=self._safe_route(route),
            )
        readiness = self.runtime_evaluator.evaluate(
            snapshot=dict(publication["snapshot"]),
            deployment=deployment,
        )
        if readiness.runtime_status.value == "blocked":
            outcome = RouteResolutionOutcome.BLOCKED
        else:
            outcome = RouteResolutionOutcome.MATCHED
        return RuntimeRouteResolution(
            outcome=outcome,
            reason_code=readiness.reason_code,
            message=readiness.message,
            readiness=readiness,
            application=self._application_summary(application),
            deployment=deployment,
            publication=publication,
            route=self._safe_route(route),
        )

    def _verified(self, publication_id: str) -> dict[str, Any]:
        publication = self.repository.get_publication(publication_id)
        if not verify_publication_snapshot(
            dict(publication["snapshot"]),
            schema_version=int(publication["schema_version"]),
            expected_hash=str(publication["config_hash"]),
        ):
            raise self.configuration_error(
                "Business Application publication integrity check failed"
            )
        return publication

    @staticmethod
    def configuration_error(
        message: str,
        *,
        error_code: str = "business_application_configuration_error",
    ) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            message,
            safe_message="业务应用运行配置不可用",
            error_code=error_code,
        )

    @staticmethod
    def _application_summary(application: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": application["id"],
            "code": application["code"],
            "project_code": application["project_code"],
        }

    @staticmethod
    def _safe_route(route: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": route["id"],
            "deployment_id": route["deployment_id"],
            "application_id": route["application_id"],
            "publication_id": route["publication_id"],
            "environment": route["environment"],
            "trigger_type": route["trigger_type"],
            "connector_id": route["connector_id"],
        }
