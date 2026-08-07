from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any


_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")
_VERSION_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)[.](0|[1-9][0-9]*)[.](0|[1-9][0-9]*)$"
)
_RESOURCE_KINDS = frozenset({"database", "redis", "loki"})
_SCOPE_TYPES = frozenset({"environment", "base", "workshop"})
_RISK_LEVELS = frozenset({"LOW", "MEDIUM", "HIGH"})
_RISK_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
_VISIBILITIES = frozenset({"application", "internal_diagnostic"})
_DYNAMIC_IMPLEMENTATION_KEYS = frozenset(
    {
        "code",
        "command",
        "endpoint",
        "handler_url",
        "implementation",
        "javascript",
        "python",
        "script",
        "source",
        "sql",
        "sql_template",
        "url",
    }
)


class HandlerRegistryError(ValueError):
    pass


def _canonical_hash(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ResourceSlotDefinition:
    code: str
    resource_kind: str
    required: bool = True
    allowed_scope_types: tuple[str, ...] = (
        "environment",
        "base",
        "workshop",
    )

    def public(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "resource_kind": self.resource_kind,
            "required": self.required,
            "allowed_scope_types": list(self.allowed_scope_types),
        }


@dataclass(frozen=True)
class VerifierPlanDefinition:
    verifier_id: str = ""
    verifier_version: str = "0.0.0"
    checks: tuple[str, ...] = ()
    max_duration_ms: int = 0
    max_result_bytes: int = 0

    def public(self) -> dict[str, Any]:
        return {
            "verifier_id": self.verifier_id,
            "verifier_version": self.verifier_version,
            "checks": list(self.checks),
            "max_duration_ms": self.max_duration_ms,
            "max_result_bytes": self.max_result_bytes,
        }


@dataclass(frozen=True)
class SafetyBoundaryDefinition:
    read_only: bool = True
    allowed_effects: tuple[str, ...] = ()
    required_guards: tuple[str, ...] = ()

    def public(self) -> dict[str, Any]:
        return {
            "read_only": self.read_only,
            "allowed_effects": list(self.allowed_effects),
            "required_guards": list(self.required_guards),
        }


@dataclass(frozen=True)
class HandlerDefinition:
    handler_id: str
    handler_version: str
    display_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk_level: str
    required_permissions: tuple[str, ...]
    resource_slots: tuple[ResourceSlotDefinition, ...] = ()
    visibility: str = "application"
    implementation_key: str = ""
    tool_semantic_version: str = "1.0.0"
    verifier_plan: VerifierPlanDefinition = field(
        default_factory=VerifierPlanDefinition
    )
    safety_boundary: SafetyBoundaryDefinition = field(
        default_factory=SafetyBoundaryDefinition
    )

    @property
    def tool_identifier(self) -> str:
        return self.handler_id

    @property
    def public_schema_hash(self) -> str:
        return _canonical_hash(
            {
                "input_schema": self.input_schema,
                "output_schema": self.output_schema,
            }
        )

    def manifest(self) -> dict[str, Any]:
        return {
            "tool_identifier": self.tool_identifier,
            "tool_semantic_version": self.tool_semantic_version,
            "handler_id": self.handler_id,
            "handler_version": self.handler_version,
            "display_name": self.display_name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "risk_level": self.risk_level,
            "required_permissions": list(self.required_permissions),
            "resource_slots": [
                slot.public() for slot in self.resource_slots
            ],
            "visibility": self.visibility,
            "public_schema_hash": self.public_schema_hash,
            "verifier_plan": self.verifier_plan.public(),
            "safety_boundary": self.safety_boundary.public(),
        }

    @property
    def manifest_hash(self) -> str:
        return _canonical_hash(self.manifest())

    @property
    def implementation_digest(self) -> str:
        return _canonical_hash(
            {
                "manifest_hash": self.manifest_hash,
                "implementation_key": self.implementation_key,
            }
        )


class HandlerRegistry:
    def __init__(self, definitions: tuple[HandlerDefinition, ...]) -> None:
        values: dict[tuple[str, str], HandlerDefinition] = {}
        for definition in definitions:
            self._validate_definition(definition)
            key = (
                definition.handler_id,
                definition.handler_version,
            )
            if key in values:
                raise HandlerRegistryError(
                    f"Duplicate Handler version: {key}"
                )
            values[key] = definition
        self._definitions = values

    def definitions(self) -> tuple[HandlerDefinition, ...]:
        return tuple(
            self._definitions[key]
            for key in sorted(self._definitions)
        )

    def require(
        self,
        handler_id: str,
        handler_version: str,
    ) -> HandlerDefinition:
        definition = self._definitions.get(
            (handler_id, handler_version)
        )
        if definition is None:
            raise HandlerRegistryError(
                f"Handler is not installed in code: "
                f"{handler_id}@{handler_version}"
            )
        return definition

    def application_catalog(self) -> tuple[HandlerDefinition, ...]:
        return tuple(
            definition
            for definition in self.definitions()
            if definition.visibility == "application"
        )

    @staticmethod
    def assert_no_safety_boundary_expansion(
        previous: HandlerDefinition,
        candidate: HandlerDefinition,
    ) -> None:
        if previous.tool_identifier != candidate.tool_identifier:
            return
        reasons: list[str] = []
        reasons.extend(
            f"input_schema:{reason}"
            for reason in _schema_expansion_reasons(
                previous.input_schema,
                candidate.input_schema,
            )
        )
        reasons.extend(
            f"output_schema:{reason}"
            for reason in _schema_expansion_reasons(
                previous.output_schema,
                candidate.output_schema,
            )
        )
        if _RISK_RANK[candidate.risk_level] > _RISK_RANK[previous.risk_level]:
            reasons.append("risk_level")
        if set(candidate.required_permissions) != set(
            previous.required_permissions
        ):
            reasons.append("required_permissions")

        previous_slots = {slot.code: slot for slot in previous.resource_slots}
        candidate_slots = {slot.code: slot for slot in candidate.resource_slots}
        for code, slot in candidate_slots.items():
            before = previous_slots.get(code)
            if before is None:
                reasons.append(f"resource_slot:{code}:added")
                continue
            if before.resource_kind != slot.resource_kind:
                reasons.append(f"resource_slot:{code}:kind")
            if set(slot.allowed_scope_types).difference(
                before.allowed_scope_types
            ):
                reasons.append(f"resource_slot:{code}:scope")
            if before.required and not slot.required:
                reasons.append(f"resource_slot:{code}:optional")

        before_boundary = previous.safety_boundary
        after_boundary = candidate.safety_boundary
        if before_boundary.read_only and not after_boundary.read_only:
            reasons.append("safety_boundary:mutation")
        if set(after_boundary.allowed_effects).difference(
            before_boundary.allowed_effects
        ):
            reasons.append("safety_boundary:effects")
        if set(before_boundary.required_guards).difference(
            after_boundary.required_guards
        ):
            reasons.append("safety_boundary:guards")

        if reasons:
            raise HandlerRegistryError(
                "Manifest expands the safety boundary for a stable "
                f"Identifier: {', '.join(sorted(set(reasons)))}"
            )

    @classmethod
    def reject_dynamic_governance_payload(
        cls,
        payload: dict[str, Any],
    ) -> None:
        cls._reject_dynamic_value(payload, path="")

    @classmethod
    def _reject_dynamic_value(
        cls,
        value: Any,
        *,
        path: str,
    ) -> None:
        if isinstance(value, dict):
            for raw_key, item in value.items():
                key = str(raw_key).strip().lower()
                child = f"{path}.{key}" if path else key
                if key in _DYNAMIC_IMPLEMENTATION_KEYS:
                    raise HandlerRegistryError(
                        f"Dynamic Handler implementation field is forbidden: "
                        f"{child}"
                    )
                cls._reject_dynamic_value(item, path=child)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                cls._reject_dynamic_value(
                    item,
                    path=f"{path}[{index}]",
                )
        elif isinstance(value, str) and value.strip().lower().startswith(
            ("http://", "https://")
        ):
            raise HandlerRegistryError(
                f"Dynamic Handler URL is forbidden: {path}"
            )

    @staticmethod
    def _validate_definition(definition: HandlerDefinition) -> None:
        if not _CODE_PATTERN.fullmatch(definition.handler_id):
            raise HandlerRegistryError("Handler ID is invalid")
        if definition.handler_id.startswith("cap__"):
            raise HandlerRegistryError(
                "The cap__ namespace is reserved for governed API capabilities"
            )
        if definition.handler_id == "legacy-v1":
            raise HandlerRegistryError(
                "The legacy-v1 Identifier is reserved for migration evidence"
            )
        if not _VERSION_PATTERN.fullmatch(
            definition.tool_semantic_version
        ):
            raise HandlerRegistryError(
                "Tool semantic version must be immutable SemVer"
            )
        if not _VERSION_PATTERN.fullmatch(
            definition.handler_version
        ):
            raise HandlerRegistryError(
                "Handler version must be immutable SemVer"
            )
        if definition.risk_level not in _RISK_LEVELS:
            raise HandlerRegistryError("Handler risk level is invalid")
        if definition.visibility not in _VISIBILITIES:
            raise HandlerRegistryError("Handler visibility is invalid")
        for schema_name, schema in (
            ("input", definition.input_schema),
            ("output", definition.output_schema),
        ):
            if (
                not isinstance(schema, dict)
                or schema.get("type") != "object"
            ):
                raise HandlerRegistryError(
                    f"Handler {schema_name} schema must be an object"
                )
            try:
                json.dumps(schema, sort_keys=True)
            except (TypeError, ValueError) as exc:
                raise HandlerRegistryError(
                    f"Handler {schema_name} schema is not JSON"
                ) from exc
        if not definition.required_permissions:
            raise HandlerRegistryError(
                "Handler must declare required permissions"
            )
        for permission in definition.required_permissions:
            if not _CODE_PATTERN.fullmatch(permission):
                raise HandlerRegistryError(
                    "Handler required permission is invalid"
                )
        slot_codes: set[str] = set()
        for slot in definition.resource_slots:
            if not _CODE_PATTERN.fullmatch(slot.code):
                raise HandlerRegistryError(
                    "Handler resource slot code is invalid"
                )
            if slot.code in slot_codes:
                raise HandlerRegistryError(
                    "Handler resource slot code is duplicated"
                )
            slot_codes.add(slot.code)
            if slot.resource_kind not in _RESOURCE_KINDS:
                raise HandlerRegistryError(
                    "Handler resource slot kind is invalid"
                )
            if (
                not slot.allowed_scope_types
                or not set(slot.allowed_scope_types).issubset(
                    _SCOPE_TYPES
                )
            ):
                raise HandlerRegistryError(
                    "Handler resource slot scopes are invalid"
                )
        if not definition.implementation_key:
            raise HandlerRegistryError(
                "Handler implementation key is required"
            )
        verifier = definition.verifier_plan
        if not _CODE_PATTERN.fullmatch(verifier.verifier_id):
            raise HandlerRegistryError("Verifier ID is invalid")
        if not _VERSION_PATTERN.fullmatch(verifier.verifier_version):
            raise HandlerRegistryError("Verifier version must be SemVer")
        if (
            not verifier.checks
            or len(set(verifier.checks)) != len(verifier.checks)
            or any(not _CODE_PATTERN.fullmatch(item) for item in verifier.checks)
        ):
            raise HandlerRegistryError("Verifier checks are invalid")
        if verifier.max_duration_ms <= 0 or verifier.max_result_bytes <= 0:
            raise HandlerRegistryError("Verifier bounds are invalid")
        boundary = definition.safety_boundary
        if not boundary.read_only:
            raise HandlerRegistryError("Built-in Tool must be read-only")
        for name, values in (
            ("effects", boundary.allowed_effects),
            ("guards", boundary.required_guards),
        ):
            if (
                not values
                or len(set(values)) != len(values)
                or any(not _CODE_PATTERN.fullmatch(item) for item in values)
            ):
                raise HandlerRegistryError(
                    f"Safety boundary {name} are invalid"
                )


def _schema_expansion_reasons(
    previous: Any,
    candidate: Any,
    *,
    path: str = "$",
) -> tuple[str, ...]:
    if not isinstance(previous, dict) or not isinstance(candidate, dict):
        return (f"{path}:shape",) if previous != candidate else ()
    reasons: list[str] = []
    before_type = previous.get("type")
    after_type = candidate.get("type")
    if before_type != after_type:
        reasons.append(f"{path}:type")
        return tuple(reasons)
    if before_type == "object":
        before_properties = previous.get("properties") or {}
        after_properties = candidate.get("properties") or {}
        if isinstance(before_properties, dict) and isinstance(
            after_properties, dict
        ):
            for name in set(after_properties).difference(before_properties):
                reasons.append(f"{path}.{name}:property")
            for name in set(before_properties).intersection(after_properties):
                reasons.extend(
                    _schema_expansion_reasons(
                        before_properties[name],
                        after_properties[name],
                        path=f"{path}.{name}",
                    )
                )
        if previous.get("additionalProperties", True) is False and candidate.get(
            "additionalProperties", True
        ) is not False:
            reasons.append(f"{path}:additional_properties")
        removed_required = set(previous.get("required") or ()).difference(
            candidate.get("required") or ()
        )
        if removed_required:
            reasons.append(f"{path}:required")
    before_enum = previous.get("enum")
    after_enum = candidate.get("enum")
    if isinstance(before_enum, list) and isinstance(after_enum, list):
        if set(after_enum).difference(before_enum):
            reasons.append(f"{path}:enum")
    for lower_bound in ("minimum", "minLength", "minItems"):
        before = previous.get(lower_bound)
        after = candidate.get(lower_bound)
        if before is not None and (after is None or after < before):
            reasons.append(f"{path}:{lower_bound}")
    for upper_bound in ("maximum", "maxLength", "maxItems"):
        before = previous.get(upper_bound)
        after = candidate.get(upper_bound)
        if before is not None and (after is None or after > before):
            reasons.append(f"{path}:{upper_bound}")
    if previous.get("pattern") and candidate.get("pattern") != previous.get(
        "pattern"
    ):
        reasons.append(f"{path}:pattern")
    if before_type == "array" and "items" in previous and "items" in candidate:
        reasons.extend(
            _schema_expansion_reasons(
                previous["items"],
                candidate["items"],
                path=f"{path}[]",
            )
        )
    return tuple(reasons)


_GENERIC_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "object"},
        "raw": {"type": "object"},
        "truncated": {"type": "boolean"},
        "metadata": {"type": "object"},
    },
    "required": ["summary"],
    "additionalProperties": False,
}


def build_builtin_handler_registry() -> HandlerRegistry:
    from app.modules.agent.infrastructure.claude_code_agent_client import (
        TOOL_DEFINITIONS,
    )

    slot_by_handler = {
        "get_schema_directory": ResourceSlotDefinition(
            code="database",
            resource_kind="database",
        ),
        "query_database": ResourceSlotDefinition(
            code="database",
            resource_kind="database",
        ),
        "query_redis_get": ResourceSlotDefinition(
            code="redis",
            resource_kind="redis",
        ),
        "query_redis_scan": ResourceSlotDefinition(
            code="redis",
            resource_kind="redis",
        ),
        "query_loki": ResourceSlotDefinition(
            code="loki",
            resource_kind="loki",
        ),
        "diagnose_loki_labels": ResourceSlotDefinition(
            code="loki",
            resource_kind="loki",
        ),
        "diagnose_loki_label_values": ResourceSlotDefinition(
            code="loki",
            resource_kind="loki",
        ),
        "diagnose_loki_probe": ResourceSlotDefinition(
            code="loki",
            resource_kind="loki",
        ),
    }
    effect_by_handler = {
        "diagnose_loki_label_values": "loki.label_values.read",
        "diagnose_loki_labels": "loki.labels.read",
        "diagnose_loki_probe": "loki.logs.probe",
        "get_business_flow_context": "context.business_flow.read",
        "get_er_context": "context.er.read",
        "get_schema_directory": "database.schema.read",
        "query_database": "database.rows.read",
        "query_loki": "loki.logs.read",
        "query_redis_get": "redis.value.read",
        "query_redis_scan": "redis.keys.read",
    }
    definitions = tuple(
        HandlerDefinition(
            handler_id=handler_id,
            handler_version="1.0.0",
            display_name=handler_id,
            description=str(manifest["description"]),
            input_schema=dict(manifest["schema"]),
            output_schema=dict(_GENERIC_OUTPUT_SCHEMA),
            risk_level=(
                "MEDIUM"
                if handler_id
                in {
                    "query_database",
                    "query_redis_get",
                    "query_redis_scan",
                }
                else "LOW"
            ),
            required_permissions=(handler_id,),
            resource_slots=(
                (slot_by_handler[handler_id],)
                if handler_id in slot_by_handler
                else ()
            ),
            visibility="application",
            implementation_key=(
                f"ReadOnlyToolService.call_tool:{handler_id}"
            ),
            tool_semantic_version="1.0.0",
            verifier_plan=VerifierPlanDefinition(
                verifier_id=f"{handler_id}.verifier",
                verifier_version="1.0.0",
                checks=(
                    "manifest.contract",
                    "implementation.binding",
                    "readonly.boundary",
                    *(
                        ("resource_slot.contract",)
                        if handler_id in slot_by_handler
                        else ()
                    ),
                ),
                max_duration_ms=30_000,
                max_result_bytes=16_384,
            ),
            safety_boundary=SafetyBoundaryDefinition(
                read_only=True,
                allowed_effects=(effect_by_handler[handler_id],),
                required_guards=(
                    "job_snapshot.exact",
                    "authorization.stable_identifier",
                    "response.bounded",
                    "audit.required",
                    *(
                        ("resource_revision.exact",)
                        if handler_id in slot_by_handler
                        else ()
                    ),
                ),
            ),
        )
        for handler_id, manifest in sorted(TOOL_DEFINITIONS.items())
    )
    return HandlerRegistry(definitions)
