from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.modules.permission.application.permission_service import PermissionService
from app.modules.platform_config.infrastructure.repository import (
    PlatformConfigRepository,
)
from app.modules.platform_config.infrastructure.governed_resource_repository import (
    GovernedResourceRepository,
)
from app.modules.platform_config.infrastructure.workshop_partition_policy_repository import (
    WorkshopPartitionPolicyRepository,
)
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import NonRetryableExecutionError, NotFound
from app.shared.secret_redaction import redact_sensitive_text, sanitize_for_persistence

from .validation import validate_code
from .workshop_partition_verifier import (
    WorkshopPartitionTechnicalVerifier,
    WorkshopPartitionVerificationOutcome,
)


_DRAFT_KEYS = frozenset(
    {
        "database_rule_enabled",
        "database_table_prefix",
        "redis_rule_enabled",
        "redis_prefixes",
    }
)
_DATABASE_PREFIX = re.compile(r"[A-Za-z_][A-Za-z0-9_$#]*")
_REDIS_NAMESPACE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,383}")
_MAX_REDIS_PREFIXES = 32
_MAX_REDIS_PREFIX_LENGTH = 512


def normalize_workshop_partition_draft(
    payload: dict[str, object],
    *,
    workshop_code: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _invalid("Workshop Partition Policy Draft must be an object")
    unknown = sorted(set(payload).difference(_DRAFT_KEYS))
    if unknown:
        raise _invalid(f"Unknown Workshop Partition Policy fields: {unknown}")
    database_enabled = _require_bool(
        payload.get("database_rule_enabled"),
        field="database_rule_enabled",
    )
    redis_enabled = _require_bool(
        payload.get("redis_rule_enabled"),
        field="redis_rule_enabled",
    )
    if not database_enabled and not redis_enabled:
        raise _invalid("At least one Workshop Partition Policy rule is required")

    raw_database_prefix = payload.get("database_table_prefix")
    if database_enabled:
        if not isinstance(raw_database_prefix, str):
            raise _invalid(
                "Database table prefix must be exactly one string",
                field="database_table_prefix",
            )
        database_prefix = raw_database_prefix.strip()
        if (
            database_prefix != raw_database_prefix
            or len(database_prefix) > 128
            or _DATABASE_PREFIX.fullmatch(database_prefix) is None
        ):
            raise _invalid(
                "Database table prefix must be a non-empty exact identifier prefix",
                field="database_table_prefix",
            )
    else:
        if raw_database_prefix is not None and raw_database_prefix != "":
            raise _invalid(
                "Disabled database rule cannot retain a table prefix",
                field="database_table_prefix",
            )
        database_prefix = None

    raw_redis_prefixes = payload.get("redis_prefixes")
    if redis_enabled:
        if not isinstance(raw_redis_prefixes, list) or not raw_redis_prefixes:
            raise _invalid(
                "Redis rule requires one or more exact namespace prefixes",
                field="redis_prefixes",
            )
        if len(raw_redis_prefixes) > _MAX_REDIS_PREFIXES:
            raise _invalid(
                "Redis namespace prefix limit exceeded",
                field="redis_prefixes",
            )
        redis_prefixes = [
            _normalize_redis_prefix(
                value,
                workshop_code=workshop_code,
                field=f"redis_prefixes.{index}",
            )
            for index, value in enumerate(raw_redis_prefixes)
        ]
        if len(redis_prefixes) != len(set(redis_prefixes)):
            raise _invalid(
                "Redis namespace prefixes must be unique",
                field="redis_prefixes",
            )
        redis_prefixes.sort()
    else:
        if raw_redis_prefixes is not None and raw_redis_prefixes != () and raw_redis_prefixes != []:
            raise _invalid(
                "Disabled Redis rule cannot retain namespace prefixes",
                field="redis_prefixes",
            )
        redis_prefixes = []
    return {
        "database_rule_enabled": database_enabled,
        "database_table_prefix": database_prefix,
        "redis_rule_enabled": redis_enabled,
        "redis_prefixes": redis_prefixes,
    }


class WorkshopPartitionPolicyService:
    def __init__(
        self,
        repository: WorkshopPartitionPolicyRepository,
        topology: PlatformConfigRepository,
        permission_service: PermissionService,
        *,
        redis_verifier: WorkshopPartitionTechnicalVerifier | None = None,
        resource_repository: GovernedResourceRepository | None = None,
    ) -> None:
        self.repository = repository
        self.topology = topology
        self.permission_service = permission_service
        self.redis_verifier = redis_verifier
        self.resource_repository = resource_repository or GovernedResourceRepository(
            repository.database
        )

    def list(self) -> list[dict[str, Any]]:
        return self.repository.list_policies()

    def detail(self, code: str) -> dict[str, Any]:
        policy = self.repository.get_by_code(validate_code(code))
        return {
            **policy,
            "draft": self.repository.get_draft(str(policy["id"])),
            "revisions": self.repository.list_revisions(str(policy["id"])),
        }

    @operation_unit_of_work(lambda service: service.repository.database)
    def create(
        self,
        payload: dict[str, Any],
        *,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._require_admin(actor_id)
        allowed = _DRAFT_KEYS.union({"code", "environment_code", "base_code", "workshop_code"})
        unknown = sorted(set(payload).difference(allowed))
        if unknown:
            raise _invalid(f"Unknown Workshop Partition Policy fields: {unknown}")
        code = validate_code(str(payload.get("code") or ""))
        environment_code = validate_code(
            str(payload.get("environment_code") or ""),
            field="environment_code",
        )
        base_code = validate_code(
            str(payload.get("base_code") or ""),
            field="base_code",
        )
        workshop_code = validate_code(
            str(payload.get("workshop_code") or ""),
            field="workshop_code",
        )
        workshop = self.topology.get_workshop_by_code(
            environment_code=environment_code,
            base_code=base_code,
            code=workshop_code,
        )
        if workshop is None or str(workshop["status"]) != "enabled":
            raise NotFound(
                "Workshop Partition Policy target Workshop is unavailable",
                safe_message="目标车间不存在或未启用",
            )
        draft_payload = {key: payload.get(key) for key in _DRAFT_KEYS}
        draft = normalize_workshop_partition_draft(
            draft_payload,
            workshop_code=workshop_code,
        )
        policy = self.repository.create(
            code=code,
            workshop_id=str(workshop["id"]),
            draft=draft,
            content_hash=_content_hash(draft),
            actor_id=actor_id,
        )
        result = self.detail(str(policy["code"]))
        self._audit(
            action="create",
            actor_id=actor_id,
            correlation_id=correlation_id,
            policy=result,
        )
        return result

    @operation_unit_of_work(lambda service: service.repository.database)
    def save_draft(
        self,
        code: str,
        *,
        expected_draft_revision: int,
        payload: dict[str, Any],
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._require_admin(actor_id)
        policy = self.repository.get_by_code(validate_code(code))
        current = self.repository.get_draft(str(policy["id"]))
        if current is None:
            raise NonRetryableExecutionError(
                "Published Workshop Partition Policy requires copying a new Draft",
                safe_message="已发布策略必须先复制为新草稿才能修改",
                error_code="workshop_partition_policy_draft_missing",
            )
        draft = normalize_workshop_partition_draft(
            payload,
            workshop_code=str(policy["workshop_code"]),
        )
        result = self.repository.replace_draft(
            policy_id=str(policy["id"]),
            expected_draft_revision=expected_draft_revision,
            draft=draft,
            content_hash=_content_hash(draft),
            actor_id=actor_id,
        )
        self._audit(
            action="save_draft",
            actor_id=actor_id,
            correlation_id=correlation_id,
            policy=policy,
            draft=result,
        )
        return result

    def verify(
        self,
        code: str,
        *,
        expected_draft_revision: int,
        redis_resource_revision_id: str | None = None,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._require_admin(actor_id)
        policy = self.repository.get_by_code(validate_code(code))
        draft = self.repository.get_draft(str(policy["id"]))
        if draft is None:
            raise NonRetryableExecutionError(
                "Workshop Partition Policy has no Draft to verify",
                safe_message="该策略没有可验证的草稿",
                error_code="workshop_partition_policy_draft_missing",
            )
        if int(draft["draft_revision"]) != expected_draft_revision:
            raise NonRetryableExecutionError(
                "Workshop Partition Policy Draft revision conflict",
                safe_message="车间分区策略草稿已变化，请刷新后重试",
                error_code="workshop_partition_policy_revision_conflict",
            )
        normalized = normalize_workshop_partition_draft(
            {
                "database_rule_enabled": draft["database_rule_enabled"],
                "database_table_prefix": draft["database_table_prefix"],
                "redis_rule_enabled": draft["redis_rule_enabled"],
                "redis_prefixes": draft["redis_prefixes"],
            },
            workshop_code=str(policy["workshop_code"]),
        )
        content_hash = _content_hash(normalized)
        if content_hash != str(draft["content_hash"]):
            raise NonRetryableExecutionError(
                "Workshop Partition Policy Draft hash mismatch",
                safe_message="车间分区策略草稿完整性校验失败",
                error_code="builtin_tool_policy_hash_mismatch",
            )
        resource_revision: dict[str, Any] | None = None
        if normalized["redis_rule_enabled"]:
            resource_revision = self._redis_resource_revision(
                policy=policy,
                revision_id=str(redis_resource_revision_id or ""),
            )
            if self.redis_verifier is None:
                outcome = WorkshopPartitionVerificationOutcome(
                    status="BLOCKED",
                    verifier_version="workshop-partition-redis-scan.v1",
                    redis_summary={"enabled": True, "prefix_count": 0, "probes": []},
                    safe_error_summary="Redis namespace 技术验证器尚未配置",
                )
            else:
                outcome = self.redis_verifier.verify_redis(
                    resource_revision=resource_revision,
                    prefixes=tuple(normalized["redis_prefixes"]),
                )
        else:
            outcome = WorkshopPartitionVerificationOutcome(
                status="PASSED",
                verifier_version="workshop-partition-structural.v1",
                redis_summary={"enabled": False, "prefix_count": 0, "probes": []},
            )
        status = str(outcome.status).upper()
        if status not in {"PASSED", "FAILED", "BLOCKED"}:
            raise NonRetryableExecutionError(
                "Workshop Partition Policy verifier returned invalid status",
                safe_message="车间分区策略验证结果无效",
                error_code="workshop_partition_policy_verifier_invalid",
            )
        safe_redis_summary = sanitize_for_persistence(outcome.redis_summary)
        with self.repository.database.unit_of_work():
            current = self.repository.get_draft(str(policy["id"]))
            if (
                current is None
                or int(current["draft_revision"]) != int(draft["draft_revision"])
                or str(current["content_hash"]) != content_hash
            ):
                raise NonRetryableExecutionError(
                    "Workshop Partition Policy Draft changed during verification",
                    safe_message="车间分区策略草稿已变化，请重新验证",
                    error_code="workshop_partition_policy_verification_stale",
                )
            evidence = self.repository.insert_verification(
                policy_id=str(policy["id"]),
                draft_revision=int(draft["draft_revision"]),
                content_hash=content_hash,
                verifier_version=validate_code(
                    outcome.verifier_version,
                    field="verifier_version",
                ),
                status=status,
                redis_resource_revision_id=(
                    str(resource_revision["id"]) if resource_revision else None
                ),
                database_summary={
                    "enabled": bool(normalized["database_rule_enabled"]),
                    "prefix_length": len(normalized["database_table_prefix"] or ""),
                    "prefix_hash": _value_hash(normalized["database_table_prefix"] or ""),
                },
                redis_summary=(safe_redis_summary if isinstance(safe_redis_summary, dict) else {}),
                zero_match_warning=bool(outcome.zero_match_warning),
                safe_error_summary=redact_sensitive_text(outcome.safe_error_summary),
                actor_id=actor_id,
            )
            self._audit(
                action="verify",
                actor_id=actor_id,
                correlation_id=correlation_id,
                policy=policy,
                evidence=evidence,
            )
        return evidence

    def _redis_resource_revision(
        self,
        *,
        policy: dict[str, Any],
        revision_id: str,
    ) -> dict[str, Any]:
        if not revision_id:
            raise NonRetryableExecutionError(
                "Redis Resource Revision is required for namespace verification",
                safe_message="验证 Redis namespace 前必须选择已发布的 Redis 资源版本",
                error_code="workshop_partition_policy_redis_resource_required",
            )
        revision = self.resource_repository.get_revision(revision_id)
        resource = self.resource_repository.get_resource(str(revision["resource_id"]))
        scope_type = str(resource["scope_type"])
        covers_workshop = str(resource.get("environment_code") or "") == str(
            policy["environment_code"]
        ) and (
            scope_type == "environment"
            or (
                scope_type == "base"
                and str(resource.get("base_code") or "") == str(policy["base_code"])
            )
            or (
                scope_type == "workshop"
                and str(resource.get("workshop_code") or "") == str(policy["workshop_code"])
            )
        )
        if (
            str(resource["resource_kind"]) != "redis"
            or str(resource["status"]) != "enabled"
            or str(revision["provider_type"]) != "redis"
            or str(revision["status"]) != "PUBLISHED"
            or not covers_workshop
        ):
            raise NonRetryableExecutionError(
                "Redis Resource Revision cannot verify this Workshop Policy",
                safe_message="所选 Redis 资源版本未发布或不能覆盖该车间",
                error_code="workshop_partition_policy_redis_resource_invalid",
            )
        return revision

    @operation_unit_of_work(lambda service: service.repository.database)
    def publish(
        self,
        code: str,
        *,
        verification_id: str,
        expected_policy_revision: int,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._require_admin(actor_id)
        policy = self.repository.get_by_code(validate_code(code))
        existing = self.repository.find_revision_by_verification(verification_id)
        if existing is not None:
            if str(existing["policy_id"]) != str(policy["id"]):
                raise NonRetryableExecutionError(
                    "Workshop Partition Policy verification belongs to another Policy",
                    safe_message="验证证据不属于当前车间分区策略",
                    error_code="workshop_partition_policy_verification_stale",
                )
            return existing
        draft = self.repository.get_draft(str(policy["id"]))
        if draft is None:
            raise NonRetryableExecutionError(
                "Workshop Partition Policy has no Draft to publish",
                safe_message="该策略没有可发布的草稿",
                error_code="workshop_partition_policy_draft_missing",
            )
        verification = self.repository.get_verification(verification_id)
        if (
            str(verification["policy_id"]) != str(policy["id"])
            or int(verification["draft_revision"]) != int(draft["draft_revision"])
            or str(verification["content_hash"]) != str(draft["content_hash"])
            or str(verification["status"]) != "PASSED"
            or str(draft["status"]) != "VERIFIED"
        ):
            raise NonRetryableExecutionError(
                "Workshop Partition Policy verification is stale",
                safe_message="验证证据与当前策略草稿不一致，请重新验证",
                error_code="workshop_partition_policy_verification_stale",
            )
        revision = self.repository.publish(
            policy=policy,
            draft=draft,
            verification=verification,
            expected_policy_revision=expected_policy_revision,
            actor_id=actor_id,
        )
        self._audit(
            action="publish",
            actor_id=actor_id,
            correlation_id=correlation_id,
            policy=policy,
            revision=revision,
        )
        return revision

    @operation_unit_of_work(lambda service: service.repository.database)
    def copy_revision_to_draft(
        self,
        code: str,
        *,
        source_revision_id: str,
        expected_policy_revision: int,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._require_admin(actor_id)
        policy = self.repository.get_by_code(validate_code(code))
        revision = self.repository.get_revision(source_revision_id)
        if str(revision["policy_id"]) != str(policy["id"]):
            raise NotFound(
                "Workshop Partition Policy revision belongs to another Policy",
                safe_message="未找到当前策略的指定发布版本",
            )
        draft = self.repository.copy_revision_to_draft(
            policy=policy,
            revision=revision,
            expected_policy_revision=expected_policy_revision,
            actor_id=actor_id,
        )
        self._audit(
            action="copy_revision_to_draft",
            actor_id=actor_id,
            correlation_id=correlation_id,
            policy=policy,
            draft=draft,
        )
        return draft

    def _require_admin(self, actor_id: str) -> None:
        self.permission_service.require_action(
            user_id=actor_id,
            resource_type="platform_config",
            resource_code="*",
            action="manage",
        )

    def _audit(
        self,
        *,
        action: str,
        actor_id: str,
        correlation_id: str,
        policy: dict[str, Any],
        draft: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
        revision: dict[str, Any] | None = None,
    ) -> None:
        fact = draft or evidence or revision or policy
        self.topology.record_config_audit(
            entity_type="workshop_partition_policy",
            entity_id=str(policy["id"]),
            action=action,
            actor_id=actor_id,
            before={},
            after={
                "policy_id": str(policy["id"]),
                "policy_code": str(policy["code"]),
                "workshop_id": str(policy["workshop_id"]),
                "policy_revision": int(policy["revision"]),
                "draft_revision": int(fact.get("draft_revision") or 0),
                "revision": int(fact.get("revision") or 0),
                "content_hash": str(fact.get("content_hash") or ""),
                "verification_id": str(fact.get("verification_id") or ""),
            },
            correlation_id=correlation_id,
        )


def _normalize_redis_prefix(
    value: object,
    *,
    workshop_code: str,
    field: str,
) -> str:
    if not isinstance(value, str):
        raise _invalid("Redis namespace prefix must be a string", field=field)
    if (
        not value
        or value != value.strip()
        or len(value) > _MAX_REDIS_PREFIX_LENGTH
        or any(ord(character) < 32 for character in value)
    ):
        raise _invalid("Redis namespace prefix is invalid", field=field)
    suffix = f"#{workshop_code}@$"
    if not value.endswith(suffix):
        raise _invalid(
            "Redis namespace prefix must end at the exact Workshop boundary",
            field=field,
        )
    namespace = value[: -len(suffix)]
    if _REDIS_NAMESPACE.fullmatch(namespace) is None:
        raise _invalid(
            "Redis namespace prefix must include an exact fixed namespace",
            field=field,
        )
    return value


def _require_bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid("Workshop Partition Policy flags must be boolean", field=field)
    return value


def _content_hash(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _value_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _invalid(
    message: str,
    *,
    field: str = "workshop_partition_policy",
) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        message,
        safe_message="车间分区策略包含无效或模糊的资源前缀",
        error_code="workshop_partition_policy_invalid",
        field_errors=[
            {
                "field": field,
                "message": "必须配置精确、非空且不含通配或正则的前缀",
            }
        ],
    )
