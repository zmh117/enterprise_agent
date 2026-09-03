from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Final

from app.shared.ones_tool_contracts import ONES_CREATE_BUG_TOOL_IDENTIFIER, require_ones_tool_contract
from services.ones_mcp_server.errors import OnesMcpError


DEFAULT_BUG_CREATE_CATALOG_PATH: Final = (
    Path(__file__).resolve().parent / "resources" / "bug_create_field_catalog.json"
)
FIXED_DEFECT_ISSUE_TYPE_UUID: Final = "B4TV9bu5"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_RESOURCE_BYTES = 512_000
_VALUE_KINDS = {"text", "rich_text", "user", "entities", "option", "options"}


def _invalid_catalog() -> OnesMcpError:
    return OnesMcpError(
        "ONES bug-create field catalog is invalid",
        safe_message="ONES 缺陷创建字段目录不可用",
        error_code="ones_bug_create_catalog_invalid",
    )


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _invalid_catalog()
    return {str(key): item for key, item in value.items()}


def _text(value: object, maximum: int = 300) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise _invalid_catalog()
    if any(ord(char) < 32 for char in value):
        raise _invalid_catalog()
    return value


def _identifier(value: object) -> str:
    text = _text(value, 128)
    if _IDENTIFIER.fullmatch(text) is None:
        raise _invalid_catalog()
    return text


def normalize_reference_name(value: str) -> str:
    return "".join(value.casefold().split())


@dataclass(frozen=True, slots=True)
class BugCreateField:
    semantic_name: str
    label: str
    provider_field_uuid: str
    provider_type: int
    value_kind: str
    options: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class BugCreateFieldCatalog:
    source_team_uuid: str
    captured_at: str
    catalog_version: str
    content_sha256: str
    fixed_issue_type_uuid: str
    fields: tuple[BugCreateField, ...]
    reference_indexes: dict[str, tuple[dict[str, str], ...]]

    @classmethod
    def load(cls, path: Path = DEFAULT_BUG_CREATE_CATALOG_PATH) -> BugCreateFieldCatalog:
        try:
            raw_bytes = path.read_bytes()
            if not raw_bytes or len(raw_bytes) > _MAX_RESOURCE_BYTES:
                raise _invalid_catalog()
            raw = _mapping(json.loads(raw_bytes))
            if raw.get("schema_version") != 1:
                raise _invalid_catalog()
            content_sha256 = _text(raw.pop("content_sha256"), 64)
            catalog_version = _text(raw.pop("catalog_version"), 80)
            canonical = json.dumps(
                raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
            if (
                _SHA256.fullmatch(content_sha256) is None
                or hashlib.sha256(canonical).hexdigest() != content_sha256
            ):
                raise _invalid_catalog()
            captured_at = _text(raw.get("captured_at"), 10)
            if catalog_version != f"{captured_at}-{content_sha256[:16]}":
                raise _invalid_catalog()
            source_hash = _text(raw.get("source_sha256"), 64)
            if _SHA256.fullmatch(source_hash) is None:
                raise _invalid_catalog()
            if raw.get("interface_contract") != "ones-bug-add3-v1":
                raise _invalid_catalog()
            fixed = _mapping(raw.get("fixed_issue_type"))
            if set(fixed) != {"uuid", "name"} or fixed.get("name") != "缺陷":
                raise _invalid_catalog()
            fixed_uuid = _identifier(fixed.get("uuid"))
            if fixed_uuid != FIXED_DEFECT_ISSUE_TYPE_UUID:
                raise _invalid_catalog()
            fields = cls._load_fields(raw.get("fields"))
            reference_indexes = cls._load_indexes(raw.get("reference_indexes"))
            expected = set(
                require_ones_tool_contract(ONES_CREATE_BUG_TOOL_IDENTIFIER).input_schema[
                    "required"
                ]
            ) - {"project_uuid"}
            if {field.semantic_name for field in fields} != expected:
                raise _invalid_catalog()
            return cls(
                source_team_uuid=_identifier(raw.get("source_team_uuid")),
                captured_at=captured_at,
                catalog_version=catalog_version,
                content_sha256=content_sha256,
                fixed_issue_type_uuid=fixed_uuid,
                fields=fields,
                reference_indexes=reference_indexes,
            )
        except OnesMcpError:
            raise
        except Exception:
            raise _invalid_catalog() from None

    @staticmethod
    def _load_fields(raw_fields: object) -> tuple[BugCreateField, ...]:
        if not isinstance(raw_fields, list) or not raw_fields or len(raw_fields) > 32:
            raise _invalid_catalog()
        fields: list[BugCreateField] = []
        semantic_names: set[str] = set()
        provider_fields: set[str] = set()
        option_uuids: set[str] = set()
        for raw in raw_fields:
            item = _mapping(raw)
            if set(item) != {
                "semantic_name",
                "label",
                "provider_field_uuid",
                "provider_type",
                "value_kind",
                "options",
            }:
                raise _invalid_catalog()
            semantic_name = _identifier(item["semantic_name"])
            label = _text(item["label"], 100)
            provider_field_uuid = _identifier(item["provider_field_uuid"])
            provider_type = item["provider_type"]
            value_kind = _text(item["value_kind"], 20)
            options_raw = item["options"]
            if (
                semantic_name in semantic_names
                or provider_field_uuid in provider_fields
                or type(provider_type) is not int
                or provider_type not in {1, 2, 8, 15, 16, 20, 44, 46}
                or value_kind not in _VALUE_KINDS
                or not isinstance(options_raw, list)
                or (value_kind in {"option", "options"}) != bool(options_raw)
            ):
                raise _invalid_catalog()
            options: list[dict[str, str]] = []
            for raw_option in options_raw:
                option = _mapping(raw_option)
                if set(option) != {"uuid", "name"}:
                    raise _invalid_catalog()
                uuid = _identifier(option["uuid"])
                if uuid in option_uuids:
                    raise _invalid_catalog()
                option_uuids.add(uuid)
                options.append({"uuid": uuid, "name": _text(option["name"])})
            semantic_names.add(semantic_name)
            provider_fields.add(provider_field_uuid)
            fields.append(
                BugCreateField(
                    semantic_name=semantic_name,
                    label=label,
                    provider_field_uuid=provider_field_uuid,
                    provider_type=provider_type,
                    value_kind=value_kind,
                    options=tuple(options),
                )
            )
        return tuple(fields)

    @staticmethod
    def _load_indexes(raw_indexes: object) -> dict[str, tuple[dict[str, str], ...]]:
        indexes = _mapping(raw_indexes)
        if set(indexes) != {
            "projects",
            "users",
            "products",
            "product_modules",
            "affected_versions",
        }:
            raise _invalid_catalog()
        result: dict[str, tuple[dict[str, str], ...]] = {}
        all_uuids: set[str] = set()
        for kind, raw_values in indexes.items():
            if not isinstance(raw_values, list) or len(raw_values) > 2000:
                raise _invalid_catalog()
            values: list[dict[str, str]] = []
            names: set[str] = set()
            for raw in raw_values:
                value = _mapping(raw)
                if set(value) != {"uuid", "name"}:
                    raise _invalid_catalog()
                uuid = _identifier(value["uuid"])
                name = _text(value["name"])
                normalized = normalize_reference_name(name)
                if uuid in all_uuids or normalized in names:
                    raise _invalid_catalog()
                all_uuids.add(uuid)
                names.add(normalized)
                values.append({"uuid": uuid, "name": name})
            result[kind] = tuple(values)
        return result

    def require_team(self, team_uuid: str) -> None:
        if team_uuid != self.source_team_uuid:
            raise OnesMcpError(
                "ONES bug-create catalog Team mismatch",
                safe_message="当前 ONES Team 没有可用的缺陷创建字段目录",
                error_code="ones_bug_create_catalog_scope_mismatch",
            )

    def require_field(self, semantic_name: str) -> BugCreateField:
        matches = [field for field in self.fields if field.semantic_name == semantic_name]
        if len(matches) != 1:
            raise _invalid_catalog()
        return matches[0]

    def option_name(self, semantic_name: str, option_uuid: str) -> str:
        field = self.require_field(semantic_name)
        matches = [item["name"] for item in field.options if item["uuid"] == option_uuid]
        if len(matches) != 1:
            raise OnesMcpError(
                "ONES bug-create option is outside the catalog",
                safe_message=f"{field.label}的选项不存在或字段目录已过期",
                error_code="ones_bug_create_option_invalid",
            )
        return matches[0]

    def resolve_name(
        self,
        kind: str,
        name: str,
        *,
        live_lookup: Callable[[str], list[dict[str, str]]],
    ) -> dict[str, str]:
        if kind not in self.reference_indexes:
            raise _invalid_catalog()
        normalized = normalize_reference_name(name)
        matches = [
            item
            for item in self.reference_indexes[kind]
            if normalize_reference_name(item["name"]) == normalized
        ]
        if len(matches) == 1:
            return dict(matches[0])
        live = [
            item
            for item in live_lookup(name)
            if normalize_reference_name(str(item.get("name") or "")) == normalized
        ]
        if len(live) != 1 or _IDENTIFIER.fullmatch(str(live[0].get("uuid") or "")) is None:
            raise OnesMcpError(
                "ONES reference name is ambiguous",
                safe_message="名称无法在 ONES 中唯一解析，请明确选择",
                error_code="ones_bug_create_reference_ambiguous",
            )
        return {"uuid": str(live[0]["uuid"]), "name": str(live[0]["name"])}
