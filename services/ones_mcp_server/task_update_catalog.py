from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from app.shared.ones_tool_contracts import (
    ONES_UPDATE_TASK_TOOL_IDENTIFIER,
    require_ones_tool_contract,
)
from services.ones_mcp_server.errors import OnesMcpError


DEFAULT_TASK_UPDATE_CATALOG_PATH: Final = (
    Path(__file__).resolve().parent / "resources" / "task_update_field_catalog.json"
)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_RESOURCE_BYTES = 512_000
_VALUE_KINDS = {
    "text",
    "number",
    "user",
    "users",
    "sprint",
    "entities",
    "option",
    "options",
}
_PROVIDER_TYPES_BY_VALUE_KIND = {
    "text": {0, 2, 15},
    "number": {4},
    "user": {0, 8},
    "users": {13},
    "sprint": {7},
    "entities": {44, 46},
    "option": {1},
    "options": {16},
}


def _invalid_catalog() -> OnesMcpError:
    return OnesMcpError(
        "ONES task-update field catalog is invalid",
        safe_message="ONES 缺陷更新字段目录不可用",
        error_code="ones_task_update_catalog_invalid",
    )


def _scope_mismatch() -> OnesMcpError:
    return OnesMcpError(
        "ONES task-update field catalog is outside the current Team",
        safe_message="当前 ONES Team 没有可用的缺陷更新字段目录",
        error_code="ones_task_update_catalog_scope_mismatch",
    )


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _invalid_catalog()
    return {str(key): item for key, item in value.items()}


def _text(value: object, *, maximum: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise _invalid_catalog()
    return value


def _identifier(value: object) -> str:
    text = _text(value, maximum=128)
    if _IDENTIFIER.fullmatch(text) is None:
        raise _invalid_catalog()
    return text


@dataclass(frozen=True, slots=True)
class TaskUpdateField:
    semantic_name: str
    label: str
    provider_field_uuid: str
    provider_type: int
    value_kind: str
    allow_clear: bool
    source_key: str
    options: tuple[dict[str, str], ...]

    @property
    def is_static_option(self) -> bool:
        return self.value_kind in {"option", "options"}


@dataclass(frozen=True, slots=True)
class TaskUpdateFieldCatalog:
    source_team_uuid: str
    captured_at: str
    catalog_version: str
    content_sha256: str
    fields: tuple[TaskUpdateField, ...]

    @classmethod
    def load(
        cls,
        path: Path = DEFAULT_TASK_UPDATE_CATALOG_PATH,
    ) -> TaskUpdateFieldCatalog:
        try:
            raw_bytes = path.read_bytes()
            if not raw_bytes or len(raw_bytes) > _MAX_RESOURCE_BYTES:
                raise _invalid_catalog()
            raw = _mapping(json.loads(raw_bytes))
            if raw.get("schema_version") != 1:
                raise _invalid_catalog()
            content_sha256 = _text(raw.pop("content_sha256"), maximum=64)
            catalog_version = _text(raw.pop("catalog_version"), maximum=80)
            canonical = json.dumps(
                raw,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            if (
                _SHA256.fullmatch(content_sha256) is None
                or hashlib.sha256(canonical).hexdigest() != content_sha256
            ):
                raise _invalid_catalog()
            captured_at = _text(raw.get("captured_at"), maximum=10)
            if catalog_version != f"{captured_at}-{content_sha256[:16]}":
                raise _invalid_catalog()
            source_sha256 = _text(raw.get("source_sha256"), maximum=64)
            if _SHA256.fullmatch(source_sha256) is None:
                raise _invalid_catalog()
            fields_raw = raw.get("fields")
            if not isinstance(fields_raw, list) or not fields_raw or len(fields_raw) > 64:
                raise _invalid_catalog()
            fields = cls._load_fields(fields_raw)
            expected_semantics = set(
                require_ones_tool_contract(
                    ONES_UPDATE_TASK_TOOL_IDENTIFIER
                ).input_schema["properties"]
            ) - {"uuid"}
            if {field.semantic_name for field in fields} != expected_semantics:
                raise _invalid_catalog()
            return cls(
                source_team_uuid=_identifier(raw.get("source_team_uuid")),
                captured_at=captured_at,
                catalog_version=catalog_version,
                content_sha256=content_sha256,
                fields=fields,
            )
        except OnesMcpError:
            raise
        except Exception:
            raise _invalid_catalog() from None

    @staticmethod
    def _load_fields(values: list[object]) -> tuple[TaskUpdateField, ...]:
        fields: list[TaskUpdateField] = []
        seen_semantics: set[str] = set()
        seen_provider_fields: set[str] = set()
        seen_labels: set[str] = set()
        seen_source_keys: set[str] = set()
        for raw in values:
            item = _mapping(raw)
            if set(item) != {
                "semantic_name",
                "label",
                "provider_field_uuid",
                "provider_type",
                "value_kind",
                "allow_clear",
                "source_key",
                "options",
            }:
                raise _invalid_catalog()
            semantic_name = _identifier(item["semantic_name"])
            provider_field_uuid = str(item["provider_field_uuid"])
            if provider_field_uuid and _IDENTIFIER.fullmatch(provider_field_uuid) is None:
                raise _invalid_catalog()
            provider_type = item["provider_type"]
            value_kind = _text(item["value_kind"], maximum=20)
            allow_clear = item["allow_clear"]
            options_raw = item["options"]
            label = _text(item["label"], maximum=100)
            source_key = _identifier(item["source_key"])
            if (
                semantic_name in seen_semantics
                or (provider_field_uuid and provider_field_uuid in seen_provider_fields)
                or label in seen_labels
                or source_key in seen_source_keys
                or type(provider_type) is not int
                or provider_type not in {0, 1, 2, 4, 7, 8, 13, 15, 16, 44, 46}
                or value_kind not in _VALUE_KINDS
                or provider_type not in _PROVIDER_TYPES_BY_VALUE_KIND.get(value_kind, set())
                or type(allow_clear) is not bool
                or not isinstance(options_raw, list)
                or (not provider_field_uuid and semantic_name not in {"title", "description", "assignee_uuid"})
                or (provider_field_uuid and semantic_name in {"title", "description", "assignee_uuid"})
            ):
                raise _invalid_catalog()
            options: list[dict[str, str]] = []
            seen_options: set[str] = set()
            for raw_option in options_raw:
                option = _mapping(raw_option)
                if set(option) != {"uuid", "name"}:
                    raise _invalid_catalog()
                option_uuid = _identifier(option["uuid"])
                if option_uuid in seen_options:
                    raise _invalid_catalog()
                seen_options.add(option_uuid)
                options.append({"uuid": option_uuid, "name": _text(option["name"], maximum=300)})
            if (value_kind in {"option", "options"}) != bool(options):
                raise _invalid_catalog()
            seen_semantics.add(semantic_name)
            seen_labels.add(label)
            seen_source_keys.add(source_key)
            if provider_field_uuid:
                seen_provider_fields.add(provider_field_uuid)
            fields.append(
                TaskUpdateField(
                    semantic_name=semantic_name,
                    label=label,
                    provider_field_uuid=provider_field_uuid,
                    provider_type=provider_type,
                    value_kind=value_kind,
                    allow_clear=allow_clear,
                    source_key=source_key,
                    options=tuple(options),
                )
            )
        return tuple(fields)

    def require_team(self, team_uuid: str) -> None:
        if team_uuid != self.source_team_uuid:
            raise _scope_mismatch()

    def require_field(self, semantic_name: str) -> TaskUpdateField:
        matches = [field for field in self.fields if field.semantic_name == semantic_name]
        if len(matches) != 1:
            raise _invalid_catalog()
        return matches[0]

    def display_option(self, semantic_name: str, option_uuid: str) -> str:
        field = self.require_field(semantic_name)
        matches = [option["name"] for option in field.options if option["uuid"] == option_uuid]
        if len(matches) != 1:
            raise OnesMcpError(
                "ONES task-update option is not in the managed catalog",
                safe_message=f"{field.label}的选项不存在或字段目录已过期",
                error_code="ones_task_update_option_invalid",
            )
        return matches[0]
