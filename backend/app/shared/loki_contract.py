"""Shared Loki syntax and configuration limits; label names are not grants."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from app.shared.exceptions import ToolPolicyError

DEFAULT_LOKI_PLATFORM_MAX_LINES = 10000
LOKI_RESOURCE_MAX_LINES = 1000

# The end assertion also rejects a final newline (unlike JSON Schema's `$`).
LOKI_LABEL_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,127}(?![\s\S])"
LOKI_EXACT_VALUE_PATTERN = (
    r"^(?!\s)(?!.*(?:!=|=~|!~))[^\x00-\x1f*?{}|]{0,255}"
    r"[^\x00-\x1f\s*?{}|](?![\s\S])"
)
MAX_LOKI_SELECTOR_CONDITIONS = 8
_LABEL = re.compile(LOKI_LABEL_PATTERN)
_VALUE = re.compile(LOKI_EXACT_VALUE_PATTERN)


def is_loki_label(value: object) -> bool:
    return isinstance(value, str) and _LABEL.fullmatch(value) is not None


def assert_loki_label(value: object) -> None:
    if not is_loki_label(value):
        raise ToolPolicyError(
            "Invalid Loki label name",
            safe_message="Loki 标签名必须为 1–128 位字母、数字或下划线，且不能以数字开头",
            error_code="loki_label_invalid",
        )


def is_loki_exact_value(value: object) -> bool:
    return isinstance(value, str) and _VALUE.fullmatch(value) is not None


def assert_loki_selector(
    selector: object,
    *,
    allow_empty: bool = False,
    max_conditions: int = MAX_LOKI_SELECTOR_CONDITIONS,
) -> None:
    if not isinstance(selector, Mapping) or len(selector) > max_conditions:
        raise ToolPolicyError(
            "Invalid Loki selector object or size",
            safe_message=f"Loki 标签条件必须是对象，且不超过 {max_conditions} 项",
            error_code="loki_selector_invalid",
        )
    if not allow_empty and not selector:
        raise ToolPolicyError(
            "Loki selector is required",
            safe_message="Loki 查询缺少有效的标签范围",
            error_code="loki_selector_required",
        )
    for label, value in selector.items():
        assert_loki_label(label)
        if not is_loki_exact_value(value):
            raise ToolPolicyError(
                "Invalid Loki exact label value",
                safe_message="Loki 标签值必须是 1–256 位非空精确文本，不含首尾空白、控制字符或匹配表达式",
                error_code="loki_selector_value_invalid",
            )


def loki_label_schema() -> dict[str, Any]:
    return {"type": "string", "pattern": LOKI_LABEL_PATTERN, "minLength": 1, "maxLength": 128}


def loki_selector_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "description": "仅追加非固定标签的精确条件；固定标签由资源注入，不得重复提交。空对象表示只使用资源固定范围。",
        "propertyNames": loki_label_schema(),
        "additionalProperties": {
            "type": "string",
            "minLength": 1,
            "maxLength": 256,
            "pattern": LOKI_EXACT_VALUE_PATTERN,
        },
        "maxProperties": MAX_LOKI_SELECTOR_CONDITIONS,
    }
