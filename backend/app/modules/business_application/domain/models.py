from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ApplicationStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class RevisionStatus(StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    PUBLISHED = "published"


class ActorPolicy(StrEnum):
    CURRENT_SENDER = "CURRENT_SENDER"
    SERVICE_ACCOUNT = "SERVICE_ACCOUNT"


class TriggerType(StrEnum):
    DINGTALK_PRIVATE = "dingtalk_private"
    DINGTALK_GROUP = "dingtalk_group"
    WEBHOOK = "webhook"


class DeliveryType(StrEnum):
    REPLY_ORIGINAL = "reply_original"
    DINGTALK_PRIVATE = "dingtalk_private"
    DINGTALK_GROUP = "dingtalk_group"
    WEBHOOK_CALLBACK = "webhook_callback"


@dataclass(frozen=True)
class TriggerBinding:
    trigger_type: str
    connector_id: str
    routing_key: str
    actor_policy: str
    service_account_user_id: str = ""
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeliveryBinding:
    delivery_type: str
    connector_id: str
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CapabilityReference:
    capability_code: str
    version_constraint: str = ""
    enabled: bool = True


@dataclass(frozen=True)
class BusinessApplicationRevision:
    id: str
    application_id: str
    revision: int
    status: str
    agent_publication_id: str
    workflow_publication_id: str = ""
    session_policy: dict[str, Any] = field(default_factory=dict)
    execution_policy: dict[str, Any] = field(default_factory=dict)
    triggers: tuple[TriggerBinding, ...] = ()
    deliveries: tuple[DeliveryBinding, ...] = ()
    capabilities: tuple[CapabilityReference, ...] = ()
    validation: dict[str, Any] = field(default_factory=dict)
    config_hash: str = ""
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class BusinessApplication:
    id: str
    code: str
    name: str
    description: str
    project_code: str
    owner_user_id: str
    status: str
    revision: int
    created_by: str
    created_at: str
    updated_at: str
    draft: BusinessApplicationRevision | None = None


@dataclass(frozen=True)
class Publication:
    id: str
    application_id: str
    revision_id: str
    revision: int
    schema_version: int
    snapshot: dict[str, Any]
    config_hash: str
    published_by: str
    published_at: str


@dataclass(frozen=True)
class Deployment:
    id: str
    application_id: str
    environment: str
    publication_id: str
    active: bool
    revision: int
    activated_by: str = ""
    activated_at: str = ""
    deactivated_by: str = ""
    deactivated_at: str = ""
    updated_at: str = ""

