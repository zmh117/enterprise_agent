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
    resource_scope_kind: str = "global",
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
        resource_scope_kind=resource_scope_kind,
        assignable=assignable,
    )


# 管理能力目录是后台页面和 API 授权的唯一来源。业务应用调用、工具和数据范围不属于本目录。
ADMIN_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    _capability("dashboard.read", "dashboard", "admin_dashboard", "read", "查看工作台"),
    _capability("applications.read", "applications", "business_application", "read", "查看业务应用"),
    _capability(
        "applications.create",
        "applications",
        "business_application",
        "create",
        "新建业务应用",
        risk_level="medium",
        dependencies=("applications.read",),
    ),
    _capability(
        "applications.edit",
        "applications",
        "business_application",
        "edit",
        "编辑业务应用",
        risk_level="medium",
        dependencies=("applications.read",),
        resource_scope_kind="business_application",
    ),
    _capability(
        "applications.publish",
        "applications",
        "business_application",
        "publish",
        "发布业务应用",
        risk_level="high",
        dependencies=("applications.read",),
        resource_scope_kind="business_application",
    ),
    _capability(
        "applications.activate",
        "applications",
        "business_application",
        "activate",
        "激活或停用业务应用",
        risk_level="high",
        dependencies=("applications.read",),
        resource_scope_kind="business_application",
    ),
    _capability("channels.read", "channels", "channel_connector", "read", "查看渠道与触发器"),
    _capability(
        "channels.manage",
        "channels",
        "channel_connector",
        "manage",
        "管理渠道与触发器",
        risk_level="high",
        dependencies=("channels.read",),
    ),
    _capability(
        "channels.restart",
        "channels",
        "channel_connector",
        "restart",
        "重连渠道",
        risk_level="high",
        dependencies=("channels.read",),
    ),
    _capability(
        "channels.delete",
        "channels",
        "channel_connector",
        "delete",
        "删除渠道配置",
        risk_level="high",
        dependencies=("channels.read",),
    ),
    _capability("webhooks.read", "channels", "webhook_trigger", "read", "查看 Webhook 触发器"),
    _capability(
        "webhooks.edit",
        "channels",
        "webhook_trigger",
        "edit",
        "编辑 Webhook 触发器",
        risk_level="medium",
        dependencies=("webhooks.read",),
    ),
    _capability(
        "webhooks.publish",
        "channels",
        "webhook_trigger",
        "publish",
        "发布 Webhook 触发器",
        risk_level="high",
        dependencies=("webhooks.read",),
    ),
    _capability(
        "webhooks.rotate",
        "channels",
        "webhook_trigger",
        "rotate",
        "轮换 Webhook 凭据",
        risk_level="high",
        dependencies=("webhooks.read",),
    ),
    _capability(
        "webhooks.service_accounts",
        "channels",
        "webhook_trigger",
        "manage_service_account",
        "管理 Webhook 服务账号",
        risk_level="high",
        dependencies=("webhooks.read", "users.read"),
    ),
    _capability("agents.read", "agents", "agent", "read", "查看 Agent 配置"),
    _capability(
        "agents.edit",
        "agents",
        "agent",
        "edit",
        "编辑 Agent 配置",
        risk_level="medium",
        dependencies=("agents.read",),
        resource_scope_kind="agent",
    ),
    _capability(
        "agents.publish",
        "agents",
        "agent",
        "publish",
        "发布 Agent",
        risk_level="high",
        dependencies=("agents.read",),
        resource_scope_kind="agent",
    ),
    _capability("skills.read", "agents", "skill_catalog", "read", "查看技能目录"),
    _capability("tools.read", "agents", "tool_resource", "read", "查看只读工具资源"),
    _capability(
        "tools.manage",
        "agents",
        "tool_resource",
        "manage",
        "管理只读工具资源",
        risk_level="high",
        dependencies=("tools.read",),
    ),
    _capability(
        "tools.test",
        "agents",
        "tool_resource",
        "test",
        "测试只读工具连接",
        risk_level="medium",
        dependencies=("tools.read",),
    ),
    _capability(
        "builtin_tools.read",
        "platform",
        "builtin_tool",
        "read",
        "查看内置只读工具治理状态",
    ),
    _capability(
        "builtin_tools.reconcile",
        "platform",
        "builtin_tool",
        "reconcile",
        "对账内置只读工具安装",
        risk_level="medium",
        dependencies=("builtin_tools.read",),
    ),
    _capability(
        "builtin_tools.verify",
        "platform",
        "builtin_tool",
        "verify",
        "验证内置只读工具实现",
        risk_level="high",
        dependencies=("builtin_tools.read",),
    ),
    _capability(
        "builtin_tools.publish",
        "platform",
        "builtin_tool",
        "publish",
        "发布内置只读工具 Release",
        risk_level="high",
        dependencies=("builtin_tools.read",),
    ),
    _capability(
        "builtin_tools.lifecycle",
        "platform",
        "builtin_tool",
        "lifecycle",
        "管理内置只读工具 Release 生命周期",
        risk_level="high",
        dependencies=("builtin_tools.read",),
    ),
    _capability("users.read", "users", "user", "read", "查看人员与外部身份"),
    _capability(
        "users.manage",
        "users",
        "user",
        "manage",
        "管理人员与外部身份",
        risk_level="high",
        dependencies=("users.read",),
    ),
    _capability(
        "users.service_accounts",
        "users",
        "user",
        "manage_service_account",
        "管理服务账号",
        risk_level="high",
        dependencies=("users.read",),
    ),
    _capability("identity.discovery.read", "users", "identity", "read", "查看未绑定钉钉用户"),
    _capability(
        "identity.discovery.bind",
        "users",
        "identity",
        "manage",
        "绑定钉钉身份",
        risk_level="high",
        dependencies=("identity.discovery.read", "users.read"),
    ),
    _capability("authorization.read", "authorization", "role", "read", "查看角色与授权"),
    _capability(
        "authorization.manage",
        "authorization",
        "role",
        "manage",
        "管理角色授权",
        risk_level="high",
        dependencies=("authorization.read",),
    ),
    _capability(
        "authorization.assign",
        "authorization",
        "role",
        "assign",
        "分配角色成员",
        risk_level="high",
        dependencies=("authorization.read", "users.read"),
        resource_scope_kind="role",
    ),
    _capability("jobs.read", "operations", "agent_job", "read", "查看 Agent 运行记录"),
    _capability(
        "agent.debug.execute",
        "operations",
        "agent_job",
        "debug_execute",
        "执行 Agent 调试",
        risk_level="medium",
        dependencies=("jobs.read",),
    ),
    _capability(
        "jobs.manage",
        "operations",
        "agent_job",
        "manage",
        "重试或取消 Agent 运行",
        risk_level="high",
        dependencies=("jobs.read",),
    ),
    _capability("queues.read", "operations", "queue_status", "read", "查看队列状态"),
    _capability("conversations.read", "operations", "conversation", "read", "查看会话"),
    _capability("attachments.read", "operations", "attachment", "read", "查看附件"),
    _capability("audit.read", "audit", "audit", "read", "查看审计记录"),
    _capability("platform.read", "platform", "platform_config", "read", "查看平台配置"),
    _capability(
        "platform.manage",
        "platform",
        "platform_config",
        "manage",
        "管理平台配置",
        risk_level="high",
        dependencies=("platform.read",),
    ),
    _capability(
        "platform.restart",
        "platform",
        "platform_config",
        "restart",
        "重启运行服务",
        risk_level="high",
        dependencies=("platform.read",),
    ),
    _capability("secrets.read", "platform", "secret", "read", "查看密钥引用"),
    _capability(
        "secrets.manage",
        "platform",
        "secret",
        "manage",
        "管理密钥",
        risk_level="high",
        dependencies=("secrets.read",),
    ),
    _capability(
        "secrets.rotate",
        "platform",
        "secret",
        "rotate",
        "轮换密钥",
        risk_level="high",
        dependencies=("secrets.read",),
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
