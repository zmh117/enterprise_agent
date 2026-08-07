from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.modules.permission.application.permission_service import PermissionService
from app.modules.platform_config.infrastructure.governed_resource_repository import (
    GovernedResourceRepository,
)
from app.modules.platform_config.infrastructure.loki_scope_policy_repository import (
    LokiScopePolicyRepository,
)
from app.modules.platform_config.infrastructure.repository import PlatformConfigRepository
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import NonRetryableExecutionError, NotFound
from app.shared.secret_redaction import redact_sensitive_text, sanitize_for_persistence

from .loki_scope_policy_verifier import (
    LokiScopePolicyTechnicalVerifier,
)
from .validation import validate_code


_LABEL_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_FORBIDDEN_VALUE_FRAGMENTS = ("*", "?", "!=", "=~", "!~", "|", "{", "}")
_DRAFT_KEYS = frozenset({"resource_revision_id", "conditions"})
_MAX_CONDITIONS = 16


def normalize_loki_scope_policy_draft(payload: dict[str, object]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _invalid("Loki Scope Policy Draft must be an object")
    unknown = sorted(set(payload).difference(_DRAFT_KEYS))
    if unknown:
        raise _invalid(f"Unknown Loki Scope Policy fields: {unknown}")
    resource_revision_id = str(payload.get("resource_revision_id") or "").strip()
    if not resource_revision_id:
        raise _invalid("Loki Scope Policy requires a Resource Revision")
    raw_conditions = payload.get("conditions")
    if (
        not isinstance(raw_conditions, list)
        or not raw_conditions
        or len(raw_conditions) > _MAX_CONDITIONS
    ):
        raise _invalid("Loki Scope Policy requires bounded exact conditions")
    conditions: list[dict[str, str]] = []
    for index, raw in enumerate(raw_conditions):
        if not isinstance(raw, dict) or set(raw) != {"key", "value"}:
            raise _invalid(
                "Loki Scope Policy condition must contain exact key/value",
                field=f"conditions.{index}",
            )
        key = str(raw.get("key") or "").strip()
        value = str(raw.get("value") or "")
        if _LABEL_KEY.fullmatch(key) is None:
            raise _invalid(
                "Loki Scope Policy label key is invalid", field=f"conditions.{index}.key"
            )
        if (
            not value
            or value != value.strip()
            or len(value) > 256
            or any(ord(character) < 32 for character in value)
            or any(fragment in value for fragment in _FORBIDDEN_VALUE_FRAGMENTS)
        ):
            raise _invalid(
                "Loki Scope Policy label value must be exact",
                field=f"conditions.{index}.value",
            )
        conditions.append({"key": key, "value": value})
    keys = [condition["key"] for condition in conditions]
    if len(keys) != len(set(keys)):
        raise _invalid("Loki Scope Policy label keys must be unique")
    conditions.sort(key=lambda condition: condition["key"])
    return {
        "resource_revision_id": resource_revision_id,
        "conditions": conditions,
    }


class LokiScopePolicyService:
    def __init__(
        self,
        repository: LokiScopePolicyRepository,
        topology: PlatformConfigRepository,
        permission_service: PermissionService,
        *,
        verifier: LokiScopePolicyTechnicalVerifier,
        resource_repository: GovernedResourceRepository | None = None,
    ) -> None:
        self.repository = repository
        self.topology = topology
        self.permission_service = permission_service
        self.verifier = verifier
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
        allowed = _DRAFT_KEYS.union({"code", "environment_code", "base_code"})
        unknown = sorted(set(payload).difference(allowed))
        if unknown:
            raise _invalid(f"Unknown Loki Scope Policy fields: {unknown}")
        code = validate_code(str(payload.get("code") or ""))
        environment_code = validate_code(
            str(payload.get("environment_code") or ""),
            field="environment_code",
        )
        environment = self.topology.get_environment_by_code(environment_code)
        if environment is None or str(environment["status"]) != "enabled":
            raise NotFound(
                "Loki Scope Policy Environment is unavailable",
                safe_message="Loki 范围策略目标环境不存在或未启用",
            )
        base_code = str(payload.get("base_code") or "").strip()
        base = None
        if base_code:
            base = self.topology.get_base_by_code(
                environment_code=environment_code,
                code=validate_code(base_code, field="base_code"),
            )
            if base is None or str(base["status"]) != "enabled":
                raise NotFound(
                    "Loki Scope Policy Base is unavailable",
                    safe_message="Loki 范围策略目标基地不存在或未启用",
                )
        draft = normalize_loki_scope_policy_draft({key: payload.get(key) for key in _DRAFT_KEYS})
        self._resource_revision(
            policy_target={
                "environment_id": environment["id"],
                "base_id": base["id"] if base else None,
            },
            revision_id=str(draft["resource_revision_id"]),
        )
        policy = self.repository.create(
            code=code,
            environment_id=str(environment["id"]),
            base_id=str(base["id"]) if base else None,
            draft=draft,
            content_hash=_content_hash(draft),
            actor_id=actor_id,
        )
        result = self.detail(str(policy["code"]))
        self._audit("create", actor_id, correlation_id, result)
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
        if self.repository.get_draft(str(policy["id"])) is None:
            raise NonRetryableExecutionError(
                "Published Loki Scope Policy requires copying a new Draft",
                safe_message="已发布 Loki 范围策略必须先复制为新草稿",
                error_code="loki_scope_policy_draft_missing",
            )
        draft = normalize_loki_scope_policy_draft(payload)
        self._resource_revision(policy_target=policy, revision_id=draft["resource_revision_id"])
        result = self.repository.replace_draft(
            policy_id=str(policy["id"]),
            expected_draft_revision=expected_draft_revision,
            draft=draft,
            content_hash=_content_hash(draft),
            actor_id=actor_id,
        )
        self._audit("save_draft", actor_id, correlation_id, policy, fact=result)
        return result

    def verify(
        self,
        code: str,
        *,
        expected_draft_revision: int,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._require_admin(actor_id)
        policy = self.repository.get_by_code(validate_code(code))
        draft = self.repository.get_draft(str(policy["id"]))
        if draft is None:
            raise NonRetryableExecutionError(
                "Loki Scope Policy has no Draft",
                safe_message="该 Loki 范围策略没有可验证草稿",
                error_code="loki_scope_policy_draft_missing",
            )
        if int(draft["draft_revision"]) != expected_draft_revision:
            raise NonRetryableExecutionError(
                "Loki Scope Policy Draft revision conflict",
                safe_message="Loki 范围策略草稿已变化，请刷新后重试",
                error_code="loki_scope_policy_revision_conflict",
            )
        normalized = normalize_loki_scope_policy_draft(
            {
                "resource_revision_id": draft["resource_revision_id"],
                "conditions": draft["conditions"],
            }
        )
        content_hash = _content_hash(normalized)
        if content_hash != str(draft["content_hash"]):
            raise NonRetryableExecutionError(
                "Loki Scope Policy Draft hash mismatch",
                safe_message="Loki 范围策略草稿完整性校验失败",
                error_code="builtin_tool_policy_hash_mismatch",
            )
        resource_revision = self._resource_revision(
            policy_target=policy,
            revision_id=str(draft["resource_revision_id"]),
        )
        outcome = self.verifier.verify(
            resource_revision=resource_revision,
            conditions=tuple(
                (condition["key"], condition["value"]) for condition in normalized["conditions"]
            ),
        )
        status = str(outcome.status).upper()
        if status not in {"PASSED", "FAILED", "BLOCKED"}:
            raise NonRetryableExecutionError(
                "Loki Scope Policy verifier returned invalid status",
                safe_message="Loki 范围策略验证结果无效",
                error_code="loki_scope_policy_verifier_invalid",
            )
        safe_summary = sanitize_for_persistence(outcome.result_summary)
        with self.repository.database.unit_of_work():
            current = self.repository.get_draft(str(policy["id"]))
            if (
                current is None
                or int(current["draft_revision"]) != int(draft["draft_revision"])
                or str(current["content_hash"]) != content_hash
            ):
                raise NonRetryableExecutionError(
                    "Loki Scope Policy Draft changed during verification",
                    safe_message="Loki 范围策略草稿已变化，请重新验证",
                    error_code="loki_scope_policy_verification_stale",
                )
            evidence = self.repository.insert_verification(
                policy_id=str(policy["id"]),
                draft_revision=int(draft["draft_revision"]),
                resource_revision_id=str(draft["resource_revision_id"]),
                content_hash=content_hash,
                verifier_version=validate_code(
                    outcome.verifier_version,
                    field="verifier_version",
                ),
                status=status,
                match_count=max(0, int(outcome.match_count)),
                truncated=bool(outcome.truncated),
                zero_match_warning=bool(outcome.zero_match_warning),
                result_summary=(safe_summary if isinstance(safe_summary, dict) else {}),
                safe_error_summary=redact_sensitive_text(outcome.safe_error_summary),
                actor_id=actor_id,
            )
            self._audit("verify", actor_id, correlation_id, policy, fact=evidence)
        return evidence

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
                raise self._stale_verification()
            return existing
        draft = self.repository.get_draft(str(policy["id"]))
        if draft is None:
            raise NonRetryableExecutionError(
                "Loki Scope Policy has no Draft",
                safe_message="该 Loki 范围策略没有可发布草稿",
                error_code="loki_scope_policy_draft_missing",
            )
        evidence = self.repository.get_verification(verification_id)
        if (
            str(evidence["policy_id"]) != str(policy["id"])
            or int(evidence["draft_revision"]) != int(draft["draft_revision"])
            or str(evidence["resource_revision_id"]) != str(draft["resource_revision_id"])
            or str(evidence["content_hash"]) != str(draft["content_hash"])
            or str(evidence["status"]) != "PASSED"
            or str(draft["status"]) != "VERIFIED"
        ):
            raise self._stale_verification()
        self._resource_revision(
            policy_target=policy,
            revision_id=str(draft["resource_revision_id"]),
        )
        revision = self.repository.publish(
            policy=policy,
            draft=draft,
            verification=evidence,
            expected_policy_revision=expected_policy_revision,
            actor_id=actor_id,
        )
        self._audit("publish", actor_id, correlation_id, policy, fact=revision)
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
                "Loki Scope Policy Revision belongs to another Policy",
                safe_message="未找到当前策略的指定发布版本",
            )
        draft = self.repository.copy_revision_to_draft(
            policy=policy,
            revision=revision,
            expected_policy_revision=expected_policy_revision,
            actor_id=actor_id,
        )
        self._audit("copy_revision_to_draft", actor_id, correlation_id, policy, fact=draft)
        return draft

    def refresh_health(
        self,
        code: str,
        *,
        policy_revision_id: str,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self._require_admin(actor_id)
        policy = self.repository.get_by_code(validate_code(code))
        revision = self.repository.get_revision(policy_revision_id)
        if (
            str(revision["policy_id"]) != str(policy["id"])
            or str(revision["status"]) != "PUBLISHED"
        ):
            raise NonRetryableExecutionError(
                "Loki Scope Policy Revision is not available for health probing",
                safe_message="Loki 范围策略发布版本不可执行健康探测",
                error_code="loki_scope_policy_health_unavailable",
            )
        resource_revision = self._resource_revision(
            policy_target=policy,
            revision_id=str(revision["resource_revision_id"]),
        )
        outcome = self.verifier.verify(
            resource_revision=resource_revision,
            conditions=tuple(
                (condition["key"], condition["value"]) for condition in revision["conditions"]
            ),
        )
        status = str(outcome.status).upper()
        health_status = (
            "HEALTHY"
            if status == "PASSED" and int(outcome.match_count) > 0
            else "EMPTY"
            if status == "PASSED"
            else "DEGRADED"
        )
        safe_summary = sanitize_for_persistence(outcome.result_summary)
        with self.repository.database.unit_of_work():
            current = self.repository.get_revision(policy_revision_id)
            if (
                str(current["status"]) != "PUBLISHED"
                or str(current["content_hash"]) != str(revision["content_hash"])
                or str(current["resource_revision_id"]) != str(revision["resource_revision_id"])
            ):
                raise NonRetryableExecutionError(
                    "Loki Scope Policy Revision changed during health probing",
                    safe_message="Loki 范围策略发布版本在健康探测期间已变化",
                    error_code="loki_scope_policy_health_unavailable",
                )
            observation = self.repository.record_health_observation(
                policy_revision_id=policy_revision_id,
                health_status=health_status,
                match_count=max(0, int(outcome.match_count)),
                truncated=bool(outcome.truncated),
                result_summary=(safe_summary if isinstance(safe_summary, dict) else {}),
                safe_error_summary=redact_sensitive_text(outcome.safe_error_summary),
                actor_id=actor_id,
            )
            self._audit(
                "refresh_health",
                actor_id,
                correlation_id,
                policy,
                fact=current,
            )
        return observation

    def _resource_revision(
        self,
        *,
        policy_target: dict[str, Any],
        revision_id: str,
    ) -> dict[str, Any]:
        revision = self.resource_repository.get_revision(str(revision_id))
        resource = self.resource_repository.get_resource(str(revision["resource_id"]))
        scope = str(resource["scope_type"])
        covers = scope == "global" or (
            scope == "environment"
            and str(resource.get("environment_id") or "")
            == str(policy_target.get("environment_id") or "")
        )
        if (
            str(resource["resource_kind"]) != "loki"
            or str(resource["status"]) != "enabled"
            or str(revision["provider_type"]) != "loki"
            or str(revision["status"]) != "PUBLISHED"
            or not covers
        ):
            raise NonRetryableExecutionError(
                "Loki Resource Revision cannot serve this Scope Policy",
                safe_message="所选 Loki 资源版本未发布或不能覆盖目标环境",
                error_code="loki_scope_policy_resource_invalid",
            )
        return revision

    def _require_admin(self, actor_id: str) -> None:
        self.permission_service.require_action(
            user_id=actor_id,
            resource_type="platform_config",
            resource_code="*",
            action="manage",
        )

    def _audit(
        self,
        action: str,
        actor_id: str,
        correlation_id: str,
        policy: dict[str, Any],
        *,
        fact: dict[str, Any] | None = None,
    ) -> None:
        current = fact or policy
        self.topology.record_config_audit(
            entity_type="loki_scope_policy",
            entity_id=str(policy["id"]),
            action=action,
            actor_id=actor_id,
            before={},
            after={
                "policy_id": str(policy["id"]),
                "policy_code": str(policy["code"]),
                "environment_id": str(policy["environment_id"]),
                "base_id": str(policy.get("base_id") or ""),
                "resource_revision_id": str(current.get("resource_revision_id") or ""),
                "content_hash": str(current.get("content_hash") or ""),
                "verification_id": str(current.get("verification_id") or ""),
                "revision": int(current.get("revision") or 0),
                "draft_revision": int(current.get("draft_revision") or 0),
            },
            correlation_id=correlation_id,
        )

    @staticmethod
    def _stale_verification() -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "Loki Scope Policy verification is stale",
            safe_message="验证证据与当前 Loki 范围策略草稿不一致",
            error_code="loki_scope_policy_verification_stale",
        )


def _content_hash(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _invalid(
    message: str,
    *,
    field: str = "loki_scope_policy",
) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        message,
        safe_message="Loki 范围策略只允许唯一、精确的 AND label 条件",
        error_code="loki_scope_policy_invalid",
        field_errors=[{"field": field, "message": "必须使用精确 key=value 条件"}],
    )
