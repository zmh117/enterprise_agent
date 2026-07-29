from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any


_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")
_VERSION_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)[.](0|[1-9][0-9]*)[.](0|[1-9][0-9]*)$"
)
_RESOURCE_KINDS = frozenset({"database", "redis", "loki"})
_SCOPE_TYPES = frozenset({"environment", "base", "workshop"})
_RISK_LEVELS = frozenset({"LOW", "MEDIUM", "HIGH"})
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

    def manifest(self) -> dict[str, Any]:
        return {
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
        }

    @property
    def implementation_digest(self) -> str:
        canonical = json.dumps(
            {
                **self.manifest(),
                "implementation_key": self.implementation_key,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
            visibility=(
                "internal_diagnostic"
                if handler_id == "query_database"
                else "application"
            ),
            implementation_key=(
                f"ReadOnlyToolService.call_tool:{handler_id}"
            ),
        )
        for handler_id, manifest in sorted(TOOL_DEFINITIONS.items())
    )
    return HandlerRegistry(definitions)
