from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilityDefinition:
    code: str
    module: str
    resource_type: str
    resource_code: str
    action: str


ADMIN_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    CapabilityDefinition("dashboard.read", "dashboard", "admin_dashboard", "*", "read"),
    CapabilityDefinition("users.manage", "users", "user", "*", "manage"),
    CapabilityDefinition("authorization.manage", "authorization", "role", "*", "manage"),
    CapabilityDefinition("agents.read", "agents", "agent", "*", "edit"),
    CapabilityDefinition("agents.edit", "agents", "agent", "default-diagnostic-agent", "edit"),
    CapabilityDefinition(
        "agents.publish", "agents", "agent", "default-diagnostic-agent", "publish"
    ),
    CapabilityDefinition("skills.read", "skills", "skill_catalog", "*", "read"),
    CapabilityDefinition("tools.read", "tools", "tool_resource", "*", "read"),
    CapabilityDefinition("tools.manage", "tools", "tool_resource", "*", "manage"),
    CapabilityDefinition("tools.test", "tools", "tool_resource", "*", "test"),
    CapabilityDefinition("channels.read", "channels", "channel_connector", "*", "read"),
    CapabilityDefinition("channels.manage", "channels", "channel_connector", "*", "manage"),
    CapabilityDefinition("webhooks.read", "webhooks", "webhook_trigger", "*", "read"),
    CapabilityDefinition("webhooks.edit", "webhooks", "webhook_trigger", "*", "edit"),
    CapabilityDefinition("queues.read", "queues", "queue_status", "*", "read"),
    CapabilityDefinition("jobs.read", "jobs", "agent_job", "*", "read"),
    CapabilityDefinition("conversations.read", "conversations", "conversation", "*", "read"),
    CapabilityDefinition("attachments.read", "attachments", "attachment", "*", "read"),
    CapabilityDefinition("audit.read", "audit", "audit", "*", "read"),
)
