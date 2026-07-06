from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.shared.exceptions import NonRetryableExecutionError

from ..domain import (
    AccessEffect,
    ConfigStatus,
    ResourceKind,
    ResourceScopeType,
    SecretProvider,
    SubjectType,
)

_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SECRET_KEY_FRAGMENTS = ("password", "passwd", "token", "secret", "api_key", "apikey", "credential")
_MUTATION_TERMS = (
    "delete",
    "update",
    "insert",
    "drop",
    "truncate",
    "restart",
    "deploy",
    "write",
    "patch",
    "merge_request",
    "pull_request",
)


class PlatformConfigValidationError(NonRetryableExecutionError):
    pass


def validate_code(value: str, *, field: str = "code") -> str:
    value = str(value or "").strip()
    if not _CODE_RE.match(value):
        raise PlatformConfigValidationError(
            f"Invalid {field}: {value}", safe_message=f"Invalid {field}"
        )
    return value


def validate_status(value: str) -> ConfigStatus:
    try:
        return ConfigStatus(str(value or ConfigStatus.ENABLED.value))
    except ValueError as exc:
        raise PlatformConfigValidationError(
            f"Invalid status: {value}", safe_message="Invalid status"
        ) from exc


def validate_engine(value: str) -> str:
    value = str(value or "").strip().lower()
    if value not in {"mysql", "sqlserver", "oracle"}:
        raise PlatformConfigValidationError(
            f"Invalid database engine: {value}",
            safe_message="Invalid database engine",
        )
    return value


def validate_resource_kind(value: str) -> ResourceKind:
    try:
        return ResourceKind(str(value))
    except ValueError as exc:
        raise PlatformConfigValidationError(
            f"Invalid resource kind: {value}", safe_message="Invalid resource kind"
        ) from exc


def validate_scope_type(value: str) -> ResourceScopeType:
    try:
        return ResourceScopeType(str(value))
    except ValueError as exc:
        raise PlatformConfigValidationError(
            f"Invalid scope type: {value}", safe_message="Invalid scope type"
        ) from exc


def validate_secret_provider(value: str) -> SecretProvider:
    try:
        return SecretProvider(str(value))
    except ValueError as exc:
        raise PlatformConfigValidationError(
            f"Invalid secret provider: {value}", safe_message="Invalid secret provider"
        ) from exc


def validate_subject_type(value: str) -> SubjectType:
    try:
        return SubjectType(str(value))
    except ValueError as exc:
        raise PlatformConfigValidationError(
            f"Invalid subject type: {value}", safe_message="Invalid subject type"
        ) from exc


def validate_access_effect(value: str) -> AccessEffect:
    try:
        return AccessEffect(str(value))
    except ValueError as exc:
        raise PlatformConfigValidationError(
            f"Invalid access effect: {value}", safe_message="Invalid access effect"
        ) from exc


def validate_secret_ref(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise PlatformConfigValidationError(
            "Secret ref is required", safe_message="Secret ref is required"
        )
    if ":" not in value:
        raise PlatformConfigValidationError(
            "Secret ref must include provider prefix",
            safe_message="Secret ref must include provider prefix",
        )
    provider = value.split(":", 1)[0]
    validate_secret_provider(provider)
    return value


def assert_no_secret_payload(value: Any, *, path: str = "config") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).lower()
            child_path = f"{path}.{key}"
            if any(fragment in key_text for fragment in _SECRET_KEY_FRAGMENTS):
                if not _looks_like_secret_ref(child):
                    raise PlatformConfigValidationError(
                        f"Secret payload is not allowed at {child_path}",
                        safe_message="Secret payload is not allowed in platform configuration",
                    )
            assert_no_secret_payload(child, path=child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_secret_payload(child, path=f"{path}[{index}]")


def normalize_aliases(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PlatformConfigValidationError(
            "aliases must be a list", safe_message="aliases must be a list"
        )
    return [str(item).strip() for item in value if str(item).strip()]


def normalize_json_object(value: Any, *, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PlatformConfigValidationError(
            f"{field} must be an object", safe_message=f"{field} must be an object"
        )
    return dict(value)


def normalize_json_list(value: Any, *, field: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PlatformConfigValidationError(
            f"{field} must be a list", safe_message=f"{field} must be a list"
        )
    return list(value)


def assert_readonly_tool_scope(tool_scope: list[Any]) -> None:
    for item in tool_scope:
        text = str(item).lower()
        if any(term in text for term in _MUTATION_TERMS):
            raise PlatformConfigValidationError(
                f"Mutation tool scope is not allowed: {item}",
                safe_message="Mutation tool scope is not allowed in MVP",
            )


def assert_readonly_workflow_node(node_type: str, config: dict[str, Any]) -> None:
    text = " ".join([node_type, *(str(v) for v in config.values())]).lower()
    if any(term in text for term in _MUTATION_TERMS):
        raise PlatformConfigValidationError(
            f"Mutation workflow node is not allowed: {node_type}",
            safe_message="Mutation workflow node is not allowed in MVP",
        )


def _looks_like_secret_ref(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        validate_secret_ref(value)
    except PlatformConfigValidationError:
        return False
    return True
