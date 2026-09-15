from __future__ import annotations

from app.shared.exceptions import ToolPolicyError
from app.shared.loki_contract import assert_loki_selector


def build_effective_selector(
    selector: dict[str, str],
    *,
    mandatory_conditions: tuple[tuple[str, str], ...] = (),
    require_mandatory: bool = False,
) -> dict[str, str]:
    """AND exact diagnostic filters with the published resource's fixed scope."""
    assert_loki_selector(selector, allow_empty=True)
    mandatory = dict(mandatory_conditions)
    if require_mandatory and not mandatory:
        raise ToolPolicyError(
            "Published Loki resource scope is required",
            safe_message="Loki 资源缺少已发布的固定标签范围，禁止无范围查询",
            error_code="loki_resource_scope_required",
        )
    assert_loki_selector(mandatory, allow_empty=not require_mandatory)
    effective = dict(mandatory)
    for label, value in selector.items():
        if label in mandatory:
            raise ToolPolicyError(
                "Loki diagnostic filter cannot override mandatory scope",
                safe_message=f"标签 {label} 已由 Loki 资源固定；请仅提交其他标签条件",
                error_code="loki_fixed_label_conflict",
            )
        effective[label] = str(value)
    if not effective:
        assert_loki_selector(effective)
    return effective
