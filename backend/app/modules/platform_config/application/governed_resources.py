from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.modules.permission.application.permission_service import (
    PermissionService,
)
from app.modules.platform_config.infrastructure.governed_resource_repository import (
    GovernedResourceRepository,
)
from app.modules.platform_config.infrastructure.repository import (
    PlatformConfigRepository,
)
from app.modules.platform_config.infrastructure.runtime_generation_repository import (
    RuntimeGenerationRepository,
)
from app.modules.platform_config.domain.provider_contracts import (
    ProviderContractRegistry,
)
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import (
    NonRetryableExecutionError,
    NotFound,
    PermissionDenied,
)
from app.shared.secret_redaction import (
    redact_sensitive_text,
    sanitize_for_persistence,
)

from .validation import (
    assert_no_resource_placement,
    assert_no_secret_payload,
    normalize_json_object,
    validate_code,
    validate_secret_ref,
)
from .resource_reset import resource_reset_in_progress


RESOURCE_PROVIDERS = {
    "database": frozenset({"mysql", "sqlserver", "oracle"}),
    "redis": frozenset({"redis"}),
    "loki": frozenset({"loki"}),
}
SCOPE_TYPES = frozenset({"global", "environment", "base", "workshop"})


@dataclass(frozen=True)
class ResourceVerificationOutcome:
    status: str
    provider_contract_version: str
    checks: dict[str, Any] = field(default_factory=dict)
    safe_error_summary: str = ""


class ResourceTechnicalVerifier(Protocol):
    def verify(
        self,
        *,
        resource: dict[str, Any],
        draft: dict[str, Any],
    ) -> ResourceVerificationOutcome: ...


class UnavailableResourceTechnicalVerifier:
    def verify(
        self,
        *,
        resource: dict[str, Any],
        draft: dict[str, Any],
    ) -> ResourceVerificationOutcome:
        del resource, draft
        return ResourceVerificationOutcome(
            status="BLOCKED",
            provider_contract_version="unavailable",
            checks={"available": False},
            safe_error_summary="资源 Provider 技术验证器尚未配置",
        )


class GovernedResourceService:
    def __init__(
        self,
        repository: GovernedResourceRepository,
        config_repository: PlatformConfigRepository,
        permission_service: PermissionService,
        verifier: ResourceTechnicalVerifier | None = None,
        provider_contracts: ProviderContractRegistry | None = None,
    ) -> None:
        self.repository = repository
        self.config_repository = config_repository
        self.permission_service = permission_service
        self.verifier = verifier or UnavailableResourceTechnicalVerifier()
        self.provider_contracts = provider_contracts or ProviderContractRegistry()

    def require_admin(self, actor_id: str) -> None:
        if not actor_id:
            raise PermissionDenied(
                "Resource administrator actor is required",
                safe_message="缺少工具资源操作人",
            )
        self.permission_service.require_action(
            user_id=actor_id,
            resource_type="platform_config",
            resource_code="*",
            action="manage",
        )
        if resource_reset_in_progress(self.repository.database):
            raise NonRetryableExecutionError(
                "Resource configuration is in maintenance mode",
                safe_message="工具资源处于重置维护模式，暂不允许修改",
                error_code="resource_reset_maintenance",
            )

    def list_resources(self) -> list[dict[str, Any]]:
        runtime_status = RuntimeGenerationRepository(self.repository.database).public_status()
        runtime_by_revision = {
            str(item["resource_revision_id"]): item for item in runtime_status["resources"]
        }
        result: list[dict[str, Any]] = []
        for resource in self.repository.list_resources():
            draft = self.repository.find_draft(str(resource["id"]))
            draft_verification = (
                self.repository.matching_verification(
                    resource_id=str(resource["id"]),
                    draft_revision=int(draft["draft_revision"]),
                    content_hash=str(draft["content_hash"]),
                )
                if draft
                else None
            )
            revisions = self.repository.list_revisions(str(resource["id"]))
            published = revisions[-1] if revisions else None
            activation = runtime_by_revision.get(str(published["id"])) if published else None
            result.append(
                {
                    **resource,
                    "draft": draft,
                    "draft_verification": draft_verification,
                    "published_revision": published,
                    "effective_revision_id": (
                        str(activation["effective_revision_id"]) if activation else ""
                    ),
                    "activation_status": (
                        str(activation["status"])
                        if activation
                        else ("PENDING" if published else "EMPTY")
                    ),
                    "last_known_good_generation_id": (
                        str(activation["last_known_good_generation_id"]) if activation else ""
                    ),
                    "safe_error_summary": (str(activation["error_summary"]) if activation else ""),
                    "affected_applications": self._affected_applications(
                        str(resource["id"]),
                        runtime_status=runtime_status,
                    ),
                }
            )
        return result

    def _affected_applications(
        self,
        resource_id: str,
        *,
        runtime_status: dict[str, Any],
    ) -> list[dict[str, Any]]:
        application_status = {
            str(item["application_publication_id"]): str(item["status"])
            for item in runtime_status["applications"]
        }
        rows = self.repository.database.execute(
            """
            select affected.publication_id, affected.application_id,
                   affected.application_code, affected.application_name
              from (
                    select distinct p.id as publication_id,
                           a.id as application_id,
                           a.code as application_code,
                           a.name as application_name,
                           p.revision as publication_revision
                      from business_application_publication_builtin_tool_resource binding
                      join business_application_publication_builtin_tool tool
                        on tool.id = binding.application_tool_id
                      join business_application_publication p
                        on p.id = tool.application_publication_id
                      join business_application a on a.id = p.application_id
                      join platform_resource_revision revision
                        on revision.id = binding.resource_revision_id
                     where revision.resource_id = ?
                   ) affected
             order by affected.application_code,
                      affected.publication_revision
            """,
            (resource_id,),
        )
        return [
            {
                **row,
                "runtime_status": application_status.get(
                    str(row["publication_id"]),
                    "NOT_ACTIVE",
                ),
            }
            for row in rows
        ]

    @operation_unit_of_work(lambda service: service.repository.database)
    def create_resource(
        self,
        payload: dict[str, Any],
        *,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        assert_no_resource_placement(
            payload,
            context="Resource Identity 或连接草稿",
        )
        code = validate_code(str(payload.get("code") or ""))
        if self.repository.get_resource_by_code(code):
            raise NonRetryableExecutionError(
                f"Platform resource already exists: {code}",
                safe_message="工具资源编码已存在",
                error_code="resource_code_conflict",
            )
        resource_kind = str(payload.get("resource_kind") or "").lower()
        provider_type, config, secret_refs, content_hash = self._draft_payload(
            resource_kind=resource_kind,
            payload=payload,
        )
        scope_type = str(payload.get("scope_type") or "").lower()
        if scope_type not in SCOPE_TYPES:
            raise NonRetryableExecutionError(
                f"Unsupported Resource scope: {scope_type}",
                safe_message="工具资源作用域无效",
                error_code="resource_scope_invalid",
            )
        if resource_kind == "loki":
            if scope_type not in {"global", "environment"}:
                raise NonRetryableExecutionError(
                    "Loki Resource scope must be global or environment",
                    safe_message="Loki 连接资源只能配置为全局或精确环境范围",
                    error_code="resource_scope_invalid",
                )
        elif scope_type == "global":
            raise NonRetryableExecutionError(
                "Only Loki Resource can use global scope",
                safe_message="只有 Loki 连接资源可以使用全局范围",
                error_code="resource_scope_invalid",
            )
        if scope_type == "global":
            if any(
                str(payload.get(field) or "")
                for field in ("environment_code", "base_code", "workshop_code")
            ):
                raise NonRetryableExecutionError(
                    "Global Resource cannot retain topology address fields",
                    safe_message="全局 Loki 不能配置环境、基地或车间地址",
                    error_code="resource_scope_invalid",
                )
            environment_id = base_id = workshop_id = None
        else:
            environment_id, base_id, workshop_id = self.config_repository.resolve_scope_ids(
                environment_code=str(payload.get("environment_code") or ""),
                base_code=str(payload.get("base_code") or ""),
                workshop_code=str(payload.get("workshop_code") or ""),
            )
        if (
            (scope_type != "global" and environment_id is None)
            or (scope_type == "base" and base_id is None)
            or (scope_type == "workshop" and workshop_id is None)
            or (scope_type == "environment" and (base_id or workshop_id))
            or (scope_type == "base" and workshop_id)
        ):
            raise NonRetryableExecutionError(
                "Resource scope does not match topology address",
                safe_message="工具资源作用域与环境、基地、车间不匹配",
                error_code="resource_scope_invalid",
            )
        resource = self.repository.create_resource(
            code=code,
            name=str(payload.get("name") or code),
            resource_kind=resource_kind,
            scope_type=scope_type,
            environment_id=str(environment_id) if environment_id else None,
            base_id=str(base_id) if base_id else None,
            workshop_id=str(workshop_id) if workshop_id else None,
            actor_id=actor_id,
        )
        draft = self.repository.insert_draft(
            resource_id=str(resource["id"]),
            draft_revision=1,
            provider_type=provider_type,
            config=config,
            secret_refs=secret_refs,
            content_hash=content_hash,
            actor_id=actor_id,
        )
        self._audit(
            resource_id=str(resource["id"]),
            action="create_draft",
            actor_id=actor_id,
            after={"resource": resource, "draft": draft},
            correlation_id=correlation_id,
        )
        return {"resource": resource, "draft": draft}

    @operation_unit_of_work(lambda service: service.repository.database)
    def save_draft(
        self,
        code: str,
        payload: dict[str, Any],
        *,
        expected_revision: int,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        assert_no_resource_placement(
            payload,
            context="Resource Identity 或连接草稿",
        )
        resource = self._resource(code)
        before = self.repository.get_draft(str(resource["id"]))
        provider_type, config, secret_refs, content_hash = self._draft_payload(
            resource_kind=str(resource["resource_kind"]),
            payload=payload,
        )
        draft = self.repository.update_draft(
            resource_id=str(resource["id"]),
            expected_revision=expected_revision,
            provider_type=provider_type,
            config=config,
            secret_refs=secret_refs,
            content_hash=content_hash,
            actor_id=actor_id,
        )
        self._audit(
            resource_id=str(resource["id"]),
            action="save_draft",
            actor_id=actor_id,
            before=before,
            after=draft,
            correlation_id=correlation_id,
        )
        return draft

    @operation_unit_of_work(lambda service: service.repository.database)
    def delete_draft(
        self,
        code: str,
        *,
        expected_revision: int,
        actor_id: str,
        correlation_id: str = "",
    ) -> None:
        self.require_admin(actor_id)
        resource = self._resource(code)
        before = self.repository.get_draft(str(resource["id"]))
        self.repository.delete_draft(
            resource_id=str(resource["id"]),
            expected_revision=expected_revision,
        )
        self._audit(
            resource_id=str(resource["id"]),
            action="delete_draft",
            actor_id=actor_id,
            before=before,
            correlation_id=correlation_id,
        )

    def verify_draft(
        self,
        code: str,
        *,
        actor_id: str,
        correlation_id: str = "",
        verifier: ResourceTechnicalVerifier | None = None,
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        resource = self._resource(code)
        draft = self.repository.get_draft(str(resource["id"]))
        outcome = (verifier or self.verifier).verify(
            resource=resource,
            draft=draft,
        )
        status = str(outcome.status).upper()
        if status not in {"PASSED", "FAILED", "BLOCKED"}:
            raise NonRetryableExecutionError(
                "Resource verifier returned invalid status",
                safe_message="资源技术验证结果无效",
                error_code="resource_verifier_invalid",
            )
        contract = self.provider_contracts.require(str(draft["provider_type"]))
        if status == "PASSED" and outcome.provider_contract_version != contract.contract_version:
            raise NonRetryableExecutionError(
                "Resource verification used a stale Provider contract",
                safe_message="Provider 契约已变化，请重新验证资源草稿",
                error_code="resource_verification_stale",
            )
        safe_checks = sanitize_for_persistence(outcome.checks)
        with self.repository.database.unit_of_work():
            current_draft = self.repository.get_draft(str(resource["id"]))
            if (
                current_draft["id"] != draft["id"]
                or int(current_draft["draft_revision"]) != int(draft["draft_revision"])
                or current_draft["content_hash"] != draft["content_hash"]
            ):
                raise NonRetryableExecutionError(
                    "Resource Draft changed during external verification",
                    safe_message="资源草稿已变化，请重新验证",
                    error_code="resource_verification_stale",
                )
            verification = self.repository.insert_verification(
                resource_id=str(resource["id"]),
                draft_id=str(draft["id"]),
                draft_revision=int(draft["draft_revision"]),
                content_hash=str(draft["content_hash"]),
                status=status,
                provider_contract_version=validate_code(
                    (
                        outcome.provider_contract_version
                        if status == "PASSED"
                        else contract.contract_version
                    ),
                    field="provider_contract_version",
                ),
                checks=safe_checks if isinstance(safe_checks, dict) else {},
                safe_error_summary=redact_sensitive_text(
                    outcome.safe_error_summary,
                ),
                actor_id=actor_id,
            )
            self._audit(
                resource_id=str(resource["id"]),
                action="verify_draft",
                actor_id=actor_id,
                after=verification,
                correlation_id=correlation_id,
            )
        return verification

    @operation_unit_of_work(lambda service: service.repository.database)
    def publish_draft(
        self,
        code: str,
        *,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        resource = self._resource(code)
        draft = self.repository.get_draft(str(resource["id"]))
        verification = self.repository.matching_verification(
            resource_id=str(resource["id"]),
            draft_revision=int(draft["draft_revision"]),
            content_hash=str(draft["content_hash"]),
        )
        if draft["status"] != "VERIFIED" or not verification:
            raise NonRetryableExecutionError(
                "Resource Draft is not verified",
                safe_message="资源草稿尚未通过当前内容的技术验证",
                error_code="resource_not_verified",
            )
        if verification["status"] != "PASSED":
            raise NonRetryableExecutionError(
                "Resource verification did not pass",
                safe_message="资源草稿技术验证未通过",
                error_code="resource_not_verified",
            )
        revision = self.repository.insert_revision(
            resource_id=str(resource["id"]),
            revision=self.repository.next_resource_revision(str(resource["id"])),
            provider_type=str(draft["provider_type"]),
            provider_contract_version=str(verification["provider_contract_version"]),
            config=dict(draft["config"]),
            secret_refs=dict(draft["secret_refs"]),
            content_hash=str(draft["content_hash"]),
            verification_id=str(verification["id"]),
            actor_id=actor_id,
        )
        self.repository.delete_draft(
            resource_id=str(resource["id"]),
            expected_revision=int(draft["draft_revision"]),
        )
        self._audit(
            resource_id=str(resource["id"]),
            action="publish",
            actor_id=actor_id,
            before=draft,
            after=revision,
            correlation_id=correlation_id,
        )
        return revision

    @operation_unit_of_work(lambda service: service.repository.database)
    def create_draft_from_revision(
        self,
        code: str,
        revision_id: str,
        *,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        resource = self._resource(code)
        if self.repository.find_draft(str(resource["id"])):
            raise NonRetryableExecutionError(
                "Resource Draft already exists",
                safe_message="该工具资源已有草稿，请先处理现有草稿",
                error_code="resource_draft_conflict",
            )
        revision = self.repository.get_revision(revision_id)
        if revision["resource_id"] != resource["id"]:
            raise NotFound(f"Resource Revision not found for Resource: {revision_id}")
        draft = self.repository.insert_draft(
            resource_id=str(resource["id"]),
            draft_revision=self.repository.next_draft_revision(str(resource["id"])),
            provider_type=str(revision["provider_type"]),
            config=dict(revision["config"]),
            secret_refs=dict(revision["secret_refs"]),
            content_hash=str(revision["content_hash"]),
            actor_id=actor_id,
        )
        self._audit(
            resource_id=str(resource["id"]),
            action="create_draft_from_revision",
            actor_id=actor_id,
            after={
                "source_revision_id": revision_id,
                "draft": draft,
            },
            correlation_id=correlation_id,
        )
        return draft

    @operation_unit_of_work(lambda service: service.repository.database)
    def set_revision_status(
        self,
        code: str,
        revision_id: str,
        status: str,
        *,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        normalized = status.upper()
        if normalized not in {"DISABLED", "ARCHIVED"}:
            raise NonRetryableExecutionError(
                "Published Resource Revision cannot be modified",
                safe_message="已发布资源只能禁用或归档，不能原地修改",
                error_code="resource_revision_immutable",
            )
        resource = self._resource(code)
        before = self.repository.get_revision(revision_id)
        if before["resource_id"] != resource["id"]:
            raise NotFound(f"Resource Revision not found for Resource: {revision_id}")
        if before["status"] == "ARCHIVED" or (
            before["status"] == "DISABLED" and normalized == "DISABLED"
        ):
            raise NonRetryableExecutionError(
                "Resource Revision status transition is invalid",
                safe_message="资源发布版本状态不能回退或重复变更",
                error_code="resource_revision_immutable",
            )
        revision = self.repository.set_revision_status(
            revision_id=revision_id,
            status=normalized,
            actor_id=actor_id,
        )
        self._audit(
            resource_id=str(resource["id"]),
            action=normalized.lower(),
            actor_id=actor_id,
            before=before,
            after=revision,
            correlation_id=correlation_id,
        )
        return revision

    def _resource(self, code: str) -> dict[str, Any]:
        resource = self.repository.get_resource_by_code(validate_code(code))
        if not resource:
            raise NotFound(f"Platform resource not found: {code}")
        return resource

    def _draft_payload(
        self,
        *,
        resource_kind: str,
        payload: dict[str, Any],
    ) -> tuple[str, dict[str, Any], dict[str, str], str]:
        providers = RESOURCE_PROVIDERS.get(resource_kind)
        provider_type = str(payload.get("provider_type") or "").lower()
        if not providers or provider_type not in providers:
            raise NonRetryableExecutionError(
                f"Resource Provider does not match kind: {provider_type}",
                safe_message="工具资源类型与 Provider 不匹配",
                error_code="resource_provider_invalid",
            )
        config = normalize_json_object(
            payload.get("config"),
            field="config",
        )
        assert_no_secret_payload(config)
        secret_refs = {
            str(key): validate_secret_ref(str(value))
            for key, value in normalize_json_object(
                payload.get("secret_refs"),
                field="secret_refs",
            ).items()
        }
        document = self.provider_contracts.normalize(
            provider_type=provider_type,
            config=config,
            secret_refs=secret_refs,
        )
        if document.resource_kind != resource_kind:
            raise NonRetryableExecutionError(
                "Resource Provider contract kind mismatch",
                safe_message="工具资源类型与 Provider 契约不匹配",
                error_code="resource_provider_invalid",
            )
        config = document.config
        secret_refs = document.secret_refs
        for ref in secret_refs.values():
            code = ref.removeprefix("secret://platform/")
            secret = self.config_repository.get_platform_secret_by_code(code)
            if not secret or not secret.get("configured"):
                raise NonRetryableExecutionError(
                    "Platform Secret is unavailable for Resource Draft",
                    safe_message="所选凭据不存在、已禁用或未配置",
                    error_code="resource_secret_unavailable",
                )
        canonical = json.dumps(
            {
                "provider_type": provider_type,
                "config": config,
                "secret_refs": secret_refs,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return (
            document.provider_type,
            config,
            secret_refs,
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )

    def _audit(
        self,
        *,
        resource_id: str,
        action: str,
        actor_id: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        correlation_id: str = "",
    ) -> None:
        self.config_repository.record_config_audit(
            entity_type="platform_resource",
            entity_id=resource_id,
            action=action,
            actor_id=actor_id,
            before=before or {},
            after=after or {},
            correlation_id=correlation_id,
        )
