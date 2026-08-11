from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.shared.exceptions import NonRetryableExecutionError

from ..domain import (
    AccessEffect,
    ConfigValueType,
    ConfigStatus,
    ResourceKind,
    ResourcePlacement,
    ResourceScopeType,
    RuntimeConfigScope,
    SecretProvider,
    SubjectType,
)

_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_TOPOLOGY_PLACEHOLDER_CODES = {
    "cloud",
    "default",
    "edge",
    "n_a",
    "na",
    "none",
    "not_applicable",
    "not_configured",
    "null",
    "standalone",
    "undefined",
    "unknown",
    "unset",
}
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
            f"Invalid {field}: {value}", safe_message=f"{field} 无效"
        )
    return value


def validate_topology_code(
    value: str,
    *,
    field: str = "code",
    level: str = "topology",
) -> str:
    code = validate_code(value, field=field)
    normalized = re.sub(r"[.:-]+", "_", code.lower())
    if normalized in _TOPOLOGY_PLACEHOLDER_CODES:
        raise PlatformConfigValidationError(
            f"Placeholder {level} code is forbidden: {code}",
            safe_message=(
                f"{level} 必须使用真实业务编码，不能使用占位值"
            ),
            error_code="builtin_tool_topology_placeholder_forbidden",
        )
    return code


def validate_resource_placement(
    value: object | None,
) -> ResourcePlacement | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    try:
        return ResourcePlacement(text)
    except ValueError as exc:
        raise PlatformConfigValidationError(
            f"Invalid Resource placement: {text}",
            safe_message="资源位置只能为 cloud、edge 或缺省",
            error_code="resource_placement_invalid",
        ) from exc


def assert_no_resource_placement(
    value: Any,
    *,
    context: str,
) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in {"placement", "placementkey", "resourceplacement"}:
                raise PlatformConfigValidationError(
                    f"Resource placement is forbidden in {context}",
                    safe_message=(
                        "placement 只能在应用资源映射中配置，"
                        f"不能写入{context}"
                    ),
                    error_code="resource_placement_invalid",
                )
            assert_no_resource_placement(item, context=context)
    elif isinstance(value, (list, tuple)):
        for item in value:
            assert_no_resource_placement(item, context=context)


def validate_status(value: str) -> ConfigStatus:
    try:
        return ConfigStatus(str(value or ConfigStatus.ENABLED.value))
    except ValueError as exc:
        raise PlatformConfigValidationError(
            f"Invalid status: {value}", safe_message="状态无效"
        ) from exc


def validate_engine(value: str) -> str:
    value = str(value or "").strip().lower()
    if value not in {"postgresql", "mysql", "sqlserver", "oracle"}:
        raise PlatformConfigValidationError(
            f"Invalid database engine: {value}",
            safe_message="数据库引擎无效",
        )
    return value


def validate_redis_mode(value: str) -> str:
    value = str(value or "standalone").strip().lower()
    if value not in {"standalone", "cluster"}:
        raise PlatformConfigValidationError(
            f"Invalid redis mode: {value}",
            safe_message="Redis 模式无效",
        )
    return value


def validate_oracle_client_mode(value: str) -> str:
    value = str(value or "auto").strip().lower()
    if value not in {"thin", "thick", "auto"}:
        raise PlatformConfigValidationError(
            f"Invalid oracle_client_mode: {value}",
            safe_message="oracle_client_mode 配置无效",
        )
    return value


def validate_oracle_compat(value: str) -> str:
    value = str(value or "modern").strip().lower()
    if value not in {"modern", "legacy"}:
        raise PlatformConfigValidationError(
            f"Invalid oracle_compat: {value}",
            safe_message="oracle_compat 配置无效",
        )
    return value


def normalize_redis_resource_config(config: dict[str, Any]) -> dict[str, Any]:
    """Normalize and validate redis binding config_json fields."""

    normalized = dict(config)
    mode = validate_redis_mode(str(normalized.get("mode") or "standalone"))
    normalized["mode"] = mode
    if "db" in normalized and normalized["db"] is not None:
        try:
            db = int(normalized["db"])
        except (TypeError, ValueError) as exc:
            raise PlatformConfigValidationError(
                "redis db must be an integer", safe_message="Redis 数据库编号必须是整数"
            ) from exc
        if mode == "cluster" and db != 0:
            raise PlatformConfigValidationError(
                "Redis cluster mode does not support non-zero db",
                safe_message="Redis 集群模式不支持非零数据库编号",
            )
        normalized["db"] = db
    nodes = normalized.get("nodes")
    if nodes is not None:
        if not isinstance(nodes, list):
            raise PlatformConfigValidationError(
                "redis nodes must be a list", safe_message="Redis 节点必须是列表"
            )
        cleaned: list[dict[str, Any]] = []
        for index, item in enumerate(nodes):
            if not isinstance(item, dict):
                raise PlatformConfigValidationError(
                    f"redis nodes[{index}] must be an object",
                    safe_message="Redis 节点条目必须是对象",
                )
            host = str(item.get("host") or "").strip()
            if not host:
                raise PlatformConfigValidationError(
                    f"redis nodes[{index}].host is required",
                    safe_message="必须填写 Redis 节点主机",
                )
            cleaned.append({"host": host, "port": int(item.get("port") or 6379)})
        normalized["nodes"] = cleaned
        if mode == "cluster" and not cleaned and not normalized.get("host"):
            raise PlatformConfigValidationError(
                "Redis cluster mode requires nodes or host",
                safe_message="Redis 集群模式需要配置节点或主机",
            )
    elif mode == "cluster" and not normalized.get("host"):
        raise PlatformConfigValidationError(
            "Redis cluster mode requires nodes or host",
            safe_message="Redis 集群模式需要配置节点或主机",
        )
    return normalized


def normalize_oracle_database_config(config: dict[str, Any]) -> dict[str, Any]:
    """Normalize Oracle-specific fields on a database resource config_json."""

    normalized = dict(config)
    normalized["oracle_client_mode"] = validate_oracle_client_mode(
        str(normalized.get("oracle_client_mode") or "auto")
    )
    normalized["oracle_compat"] = validate_oracle_compat(
        str(normalized.get("oracle_compat") or "modern")
    )
    if "use_sid" in normalized:
        value = normalized["use_sid"]
        if isinstance(value, bool):
            normalized["use_sid"] = value
        else:
            text = str(value).strip().lower()
            if text in {"1", "true", "yes", "on"}:
                normalized["use_sid"] = True
            elif text in {"0", "false", "no", "off", ""}:
                normalized["use_sid"] = False
            else:
                raise PlatformConfigValidationError(
                    "use_sid must be a boolean", safe_message="use_sid 必须是布尔值"
                )
    else:
        normalized["use_sid"] = False
    if "connect_descriptor" in normalized and normalized["connect_descriptor"] is not None:
        normalized["connect_descriptor"] = str(normalized["connect_descriptor"])
    else:
        normalized.setdefault("connect_descriptor", "")
    return normalized


def validate_resource_kind(value: str) -> ResourceKind:
    try:
        return ResourceKind(str(value))
    except ValueError as exc:
        raise PlatformConfigValidationError(
            f"Invalid resource kind: {value}", safe_message="资源类型无效"
        ) from exc


def validate_scope_type(value: str) -> ResourceScopeType:
    try:
        return ResourceScopeType(str(value))
    except ValueError as exc:
        raise PlatformConfigValidationError(
            f"Invalid scope type: {value}", safe_message="作用域类型无效"
        ) from exc


def validate_secret_provider(value: str) -> SecretProvider:
    try:
        return SecretProvider(str(value))
    except ValueError as exc:
        raise PlatformConfigValidationError(
            f"Invalid secret provider: {value}", safe_message="凭据提供方无效"
        ) from exc


def validate_config_value_type(value: str) -> ConfigValueType:
    try:
        return ConfigValueType(str(value))
    except ValueError as exc:
        raise PlatformConfigValidationError(
            f"Invalid runtime config value type: {value}",
            safe_message="运行配置值类型无效",
        ) from exc


def validate_runtime_scope_type(value: str) -> RuntimeConfigScope:
    try:
        return RuntimeConfigScope(str(value or RuntimeConfigScope.GLOBAL.value))
    except ValueError as exc:
        raise PlatformConfigValidationError(
            f"Invalid runtime config scope type: {value}",
            safe_message="运行配置作用域类型无效",
        ) from exc


def validate_subject_type(value: str) -> SubjectType:
    try:
        return SubjectType(str(value))
    except ValueError as exc:
        raise PlatformConfigValidationError(
            f"Invalid subject type: {value}", safe_message="主体类型无效"
        ) from exc


def validate_access_effect(value: str) -> AccessEffect:
    try:
        return AccessEffect(str(value))
    except ValueError as exc:
        raise PlatformConfigValidationError(
            f"Invalid access effect: {value}", safe_message="访问效果值无效"
        ) from exc


def validate_secret_ref(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise PlatformConfigValidationError(
            "Secret ref is required", safe_message="必须填写凭据引用"
        )
    if ":" not in value:
        raise PlatformConfigValidationError(
            "Secret ref must include provider prefix",
            safe_message="凭据引用必须包含提供方前缀",
        )
    provider = value.split(":", 1)[0]
    if provider in {"vault", "kms"}:
        raise PlatformConfigValidationError(
            f"Reserved secret provider is not implemented: {provider}",
            safe_message="Provider 尚未实现",
        )
    if provider == "env":
        raise PlatformConfigValidationError(
            "env secret references require explicit import",
            safe_message="env 凭据引用必须先导入凭据中心",
        )
    if provider != "secret" or not value.startswith("secret://platform/"):
        raise PlatformConfigValidationError(
            "New bindings require secret://platform/<code>",
            safe_message="新配置只能选择凭据中心的 secret://platform/<code>",
        )
    code = value.removeprefix("secret://platform/")
    if not code or "/" in code or value != f"secret://platform/{validate_code(code)}":
        raise PlatformConfigValidationError(
            "Platform secret ref must use secret://platform/<code>",
            safe_message="平台凭据引用格式无效",
        )
    return value


def coerce_runtime_value(value: Any, value_type: ConfigValueType, *, field: str = "value") -> Any:
    if value_type == ConfigValueType.SECRET_REF:
        return validate_secret_ref(str(value or ""))
    if value_type == ConfigValueType.BOOL:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in {"1", "true", "yes", "on"}:
            return True
        if isinstance(value, str) and value.lower() in {"0", "false", "no", "off"}:
            return False
        raise PlatformConfigValidationError(
            f"{field} must be a boolean", safe_message=f"{field} 必须是布尔值"
        )
    if value_type == ConfigValueType.INT:
        if isinstance(value, bool):
            raise PlatformConfigValidationError(
                f"{field} must be an integer", safe_message=f"{field} 必须是整数"
            )
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise PlatformConfigValidationError(
                f"{field} must be an integer", safe_message=f"{field} 必须是整数"
            ) from exc
    if value_type == ConfigValueType.STRING:
        text = str(value or "")
        _reject_obvious_secret_text(text, field=field)
        return text
    if value_type == ConfigValueType.URL:
        text = str(value or "").strip()
        if not text.startswith(("http://", "https://", "amqp://", "amqps://")):
            raise PlatformConfigValidationError(
                f"{field} must be a supported URL", safe_message=f"{field} 必须是受支持的 URL"
            )
        _reject_obvious_secret_text(text, field=field)
        return text
    if value_type == ConfigValueType.JSON:
        assert_no_secret_payload(value, path=field)
        return value
    raise PlatformConfigValidationError(
        f"Unsupported runtime config value type: {value_type}",
        safe_message="不支持此运行配置值类型",
    )


def assert_no_secret_payload(value: Any, *, path: str = "config") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).lower()
            child_path = f"{path}.{key}"
            if any(fragment in key_text for fragment in _SECRET_KEY_FRAGMENTS):
                if not _looks_like_secret_ref(child):
                    raise PlatformConfigValidationError(
                        f"Secret payload is not allowed at {child_path}",
                        safe_message="平台配置中不允许包含凭据内容",
                    )
            assert_no_secret_payload(child, path=child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_secret_payload(child, path=f"{path}[{index}]")
    elif isinstance(value, str):
        _reject_obvious_secret_text(value, field=path)


def normalize_aliases(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PlatformConfigValidationError(
            "aliases must be a list", safe_message="aliases 必须是列表"
        )
    return [str(item).strip() for item in value if str(item).strip()]


def normalize_json_object(value: Any, *, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PlatformConfigValidationError(
            f"{field} must be an object", safe_message=f"{field} 必须是对象"
        )
    return dict(value)


def normalize_json_list(value: Any, *, field: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PlatformConfigValidationError(
            f"{field} must be a list", safe_message=f"{field} 必须是列表"
        )
    return list(value)


def assert_readonly_tool_scope(tool_scope: list[Any]) -> None:
    for item in tool_scope:
        text = str(item).lower()
        if any(term in text for term in _MUTATION_TERMS):
            raise PlatformConfigValidationError(
                f"Mutation tool scope is not allowed: {item}",
                safe_message="当前版本不允许写操作工具作用域",
            )


def assert_readonly_workflow_node(node_type: str, config: dict[str, Any]) -> None:
    text = " ".join([node_type, *(str(v) for v in config.values())]).lower()
    if any(term in text for term in _MUTATION_TERMS):
        raise PlatformConfigValidationError(
            f"Mutation workflow node is not allowed: {node_type}",
            safe_message="当前版本不允许写操作工作流节点",
        )


def _looks_like_secret_ref(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        validate_secret_ref(value)
    except PlatformConfigValidationError:
        return False
    return True


def _reject_obvious_secret_text(value: str, *, field: str) -> None:
    text = str(value or "")
    lower = text.lower()
    if _looks_like_secret_ref(text):
        return
    if any(marker in lower for marker in ("sk-", "api_key=", "token=", "password=")):
        raise PlatformConfigValidationError(
            f"Secret payload is not allowed at {field}",
            safe_message="平台配置中不允许包含凭据内容",
        )
