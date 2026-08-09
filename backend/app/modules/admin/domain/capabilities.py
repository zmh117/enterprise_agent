from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CapabilityDefinition:
    code: str
    module: str
    resource_type: str
    resource_code: str
    action: str
    display_name_zh: str
    risk_level: str = "low"
    dependencies: tuple[str, ...] = ()
    resource_scope_kind: str = "global"
    assignable: bool = True

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["dependencies"] = list(self.dependencies)
        return result


def _capability(
    code: str,
    module: str,
    resource_type: str,
    action: str,
    display_name_zh: str,
    *,
    resource_code: str = "*",
    risk_level: str = "low",
    dependencies: tuple[str, ...] = (),
    assignable: bool = True,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        code=code,
        module=module,
        resource_type=resource_type,
        resource_code=resource_code,
        action=action,
        display_name_zh=display_name_zh,
        risk_level=risk_level,
        dependencies=dependencies,
        assignable=assignable,
    )


# The heavy web administration catalog was retired.  The remaining assignable
# operations are the audited CLI control surfaces for MCP resources, encrypted
# secrets and the one-way cutover.
ADMIN_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    _capability(
        "mcp_resources.read",
        "mcp_operations",
        "mcp_resource",
        "read",
        "查看 MCP Resource 状态",
    ),
    _capability(
        "mcp_resources.manage",
        "mcp_operations",
        "mcp_resource",
        "manage",
        "管理 MCP Resource",
        risk_level="high",
        dependencies=("mcp_resources.read",),
    ),
    _capability("secrets.read", "mcp_operations", "secret", "read", "查看凭据状态"),
    _capability(
        "secrets.manage",
        "mcp_operations",
        "secret",
        "manage",
        "管理加密凭据",
        risk_level="high",
        dependencies=("secrets.read",),
    ),
    _capability(
        "cutover.read",
        "mcp_operations",
        "platform_cutover",
        "read",
        "检查破坏性切换状态",
        resource_code="legacy-platform",
    ),
    _capability(
        "cutover.manage",
        "mcp_operations",
        "platform_cutover",
        "manage",
        "执行破坏性切换",
        resource_code="legacy-platform",
        risk_level="high",
        dependencies=("cutover.read",),
    ),
    _capability(
        "external_credentials.self_manage",
        "identity",
        "external_credential",
        "self_manage",
        "管理本人外部身份",
        risk_level="high",
        assignable=False,
    ),
)


ADMIN_CAPABILITY_BY_CODE = {item.code: item for item in ADMIN_CAPABILITIES}


def validate_admin_capability_catalog() -> None:
    if len(ADMIN_CAPABILITY_BY_CODE) != len(ADMIN_CAPABILITIES):
        raise RuntimeError("管理能力目录存在重复 code")
    for item in ADMIN_CAPABILITIES:
        if item.risk_level not in {"low", "medium", "high"}:
            raise RuntimeError(f"管理能力风险等级无效: {item.code}")
        for dependency in item.dependencies:
            if dependency not in ADMIN_CAPABILITY_BY_CODE:
                raise RuntimeError(f"管理能力依赖不存在: {item.code} -> {dependency}")
            if dependency == item.code:
                raise RuntimeError(f"管理能力不能依赖自身: {item.code}")


validate_admin_capability_catalog()
