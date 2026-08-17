from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from app.shared.exceptions import NonRetryableExecutionError

from .validation import validate_topology_code


_LABEL_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_FORBIDDEN_EXACT_VALUE_FRAGMENTS = ("*", "?", "!=", "=~", "!~", "|", "{", "}")
_FORBIDDEN_PREFIX_FRAGMENTS = ("*", "?", "[", "]", "\\", "^", "(", ")", "{", "}", "|")
_MAX_BINDINGS = 128
_MAX_SELECTOR_CONDITIONS = 8
_MAX_NAMESPACE_PREFIXES = 16


def normalize_resource_scope_bindings(
    raw: object,
    *,
    resource_kind: str,
    scope_type: str,
    environment_code: str,
    base_code: str,
    workshop_code: str,
) -> list[dict[str, Any]]:
    if raw is None:
        values: list[object] = []
    elif isinstance(raw, list):
        values = raw
    else:
        raise _invalid("工具资源数据范围必须是列表")
    if len(values) > _MAX_BINDINGS:
        raise _invalid("工具资源数据范围条目过多")

    normalized: list[dict[str, Any]] = []
    seen_targets: set[tuple[str, str, str]] = set()
    for value in values:
        if not isinstance(value, Mapping):
            raise _invalid("工具资源数据范围条目无效")
        item = dict(value)
        target = _target(
            item,
            resource_kind=resource_kind,
            scope_type=scope_type,
            resource_environment=environment_code,
            resource_base=base_code,
            resource_workshop=workshop_code,
        )
        target_key = (
            target["environment_code"],
            target.get("base_code", ""),
            target.get("workshop_code", ""),
        )
        if target_key in seen_targets:
            raise _invalid("同一平台目标只能配置一个数据范围")
        seen_targets.add(target_key)

        if resource_kind == "database":
            _reject_unknown(item, {"environment_code", "base_code", "workshop_code", "table_prefix"})
            prefix = _exact_prefix(item.get("table_prefix"), field="数据库表前缀")
            if target.get("workshop_code") and not prefix:
                raise _invalid("Workshop 数据库范围必须配置精确表前缀")
            normalized.append({**target, "table_prefix": prefix})
        elif resource_kind == "redis":
            _reject_unknown(
                item,
                {"environment_code", "base_code", "workshop_code", "namespace_prefixes"},
            )
            prefixes = _namespace_prefixes(item.get("namespace_prefixes"))
            if target.get("workshop_code") and not prefixes:
                raise _invalid("Workshop Redis 范围必须配置完整 namespace prefix")
            normalized.append({**target, "namespace_prefixes": prefixes})
        elif resource_kind == "loki":
            _reject_unknown(item, {"environment_code", "base_code", "selector_conditions"})
            conditions = _selector_conditions(item.get("selector_conditions"))
            normalized.append({**target, "selector_conditions": conditions})
        else:
            raise _invalid("工具资源类型不支持数据范围")

    return sorted(
        normalized,
        key=lambda item: (
            str(item.get("environment_code") or ""),
            str(item.get("base_code") or ""),
            str(item.get("workshop_code") or ""),
        ),
    )


def assert_resource_scope_bindings_publishable(
    bindings: object,
    *,
    resource_kind: str,
    scope_type: str,
) -> None:
    if not isinstance(bindings, list):
        raise _invalid("工具资源数据范围无效")
    if resource_kind == "loki" and not bindings:
        raise _invalid("Loki Resource 必须先发现并配置至少一个 Environment selector")
    if scope_type == "workshop" and resource_kind in {"database", "redis"} and not bindings:
        raise _invalid("Workshop Resource 必须先配置精确数据范围")


def select_resource_scope_binding(
    bindings: object,
    *,
    resource_kind: str,
    environment_code: str,
    base_code: str,
    workshop_code: str,
) -> dict[str, Any] | None:
    if not isinstance(bindings, list):
        raise _invalid("已发布工具资源数据范围无效")
    environment = str(environment_code or "").strip()
    base = str(base_code or "").strip()
    workshop = str(workshop_code or "").strip()
    if resource_kind == "loki":
        targets = [
            (environment, base, "") if base else None,
            (environment, "", ""),
        ]
    else:
        targets = [(environment, base, workshop)]
    for target in targets:
        if target is None:
            continue
        matches = [
            item
            for item in bindings
            if isinstance(item, Mapping)
            and (
                str(item.get("environment_code") or ""),
                str(item.get("base_code") or ""),
                str(item.get("workshop_code") or ""),
            )
            == target
        ]
        if len(matches) > 1:
            raise _invalid("已发布工具资源包含重复的数据范围目标")
        if matches:
            return dict(matches[0])
    return None


def _target(
    item: dict[str, Any],
    *,
    resource_kind: str,
    scope_type: str,
    resource_environment: str,
    resource_base: str,
    resource_workshop: str,
) -> dict[str, str]:
    environment = validate_topology_code(
        str(item.get("environment_code") or ""),
        field="environment_code",
        level="Environment",
    )
    base = str(item.get("base_code") or "").strip()
    workshop = str(item.get("workshop_code") or "").strip()
    if base:
        base = validate_topology_code(base, field="base_code", level="Base")
    if workshop:
        workshop = validate_topology_code(
            workshop,
            field="workshop_code",
            level="Workshop",
        )
    if workshop and not base:
        raise _invalid("Workshop 数据范围必须同时指定 Base")
    if resource_kind == "loki" and workshop:
        raise _invalid("Loki selector 只能绑定 Environment 或 Environment/Base")
    if scope_type != "global" and environment != resource_environment:
        raise _invalid("数据范围 Environment 超出 Resource Identity 范围")
    if scope_type in {"base", "workshop"} and base != resource_base:
        raise _invalid("数据范围 Base 超出 Resource Identity 范围")
    if scope_type == "workshop" and workshop != resource_workshop:
        raise _invalid("数据范围 Workshop 超出 Resource Identity 范围")
    if scope_type in {"base", "workshop"} and not base:
        raise _invalid("数据范围必须包含 Resource Identity 的 Base")
    if scope_type == "workshop" and not workshop:
        raise _invalid("数据范围必须包含 Resource Identity 的 Workshop")
    target = {"environment_code": environment}
    if base:
        target["base_code"] = base
    if workshop:
        target["workshop_code"] = workshop
    return target


def _selector_conditions(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value or len(value) > _MAX_SELECTOR_CONDITIONS:
        raise _invalid("Loki selector 必须包含有界的精确 label 条件")
    normalized: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "").strip()
        text = str(raw_value)
        if _LABEL_KEY.fullmatch(key) is None:
            raise _invalid("Loki selector label key 无效")
        if key in normalized:
            raise _invalid("Loki selector label key 不能重复")
        if (
            not text
            or text != text.strip()
            or len(text) > 256
            or any(ord(character) < 32 for character in text)
            or any(fragment in text for fragment in _FORBIDDEN_EXACT_VALUE_FRAGMENTS)
        ):
            raise _invalid("Loki selector 只允许精确、非空的 label value")
        normalized[key] = text
    return dict(sorted(normalized.items()))


def _namespace_prefixes(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > _MAX_NAMESPACE_PREFIXES:
        raise _invalid("Redis namespace prefixes 必须是有界列表")
    normalized = [_exact_prefix(item, field="Redis namespace prefix") for item in value]
    if any(not item for item in normalized):
        raise _invalid("Redis namespace prefix 不能为空")
    if len(set(normalized)) != len(normalized):
        raise _invalid("Redis namespace prefix 不能重复")
    return sorted(normalized)


def _exact_prefix(value: object, *, field: str) -> str:
    text = str(value or "")
    if len(text) > 256 or any(ord(character) < 32 for character in text):
        raise _invalid(f"{field}无效")
    if text and any(fragment in text for fragment in _FORBIDDEN_PREFIX_FRAGMENTS):
        raise _invalid(f"{field}不能包含通配或正则语法")
    return text


def _reject_unknown(value: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(value).difference(allowed))
    if unknown:
        raise _invalid(f"工具资源数据范围包含未知字段: {unknown}")


def _invalid(safe_message: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        safe_message,
        safe_message=safe_message,
        error_code="resource_scope_bindings_invalid",
    )
