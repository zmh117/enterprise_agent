from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ConfigStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class ResourceScopeType(str, Enum):
    ENVIRONMENT = "environment"
    BASE = "base"
    WORKSHOP = "workshop"


class ResourceKind(str, Enum):
    DATABASE = "database"
    REDIS = "redis"
    LOKI = "loki"
    ER_CONTEXT = "er_context"
    BUSINESS_FLOW_CONTEXT = "business_flow_context"


class SecretProvider(str, Enum):
    SECRET = "secret"
    ENV = "env"
    VAULT = "vault"
    KMS = "kms"
    ENCRYPTED_DB = "encrypted_db"


class SecretStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class SecretVersionStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DISABLED = "disabled"


class RuntimeConfigScope(str, Enum):
    GLOBAL = "global"
    SERVICE = "service"
    PROJECT = "project"
    ENVIRONMENT = "environment"
    BASE = "base"
    WORKSHOP = "workshop"
    CONNECTOR = "connector"


class ConfigValueType(str, Enum):
    BOOL = "bool"
    INT = "int"
    STRING = "string"
    URL = "url"
    JSON = "json"
    SECRET_REF = "secret_ref"


class AccessEffect(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


class SubjectType(str, Enum):
    USER = "user"
    GROUP = "group"
    ROLE = "role"
    SERVICE = "service"


@dataclass(frozen=True)
class PlatformEnvironment:
    id: str
    code: str
    display_name: str = ""
    status: ConfigStatus = ConfigStatus.ENABLED
    aliases: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    revision: int = 1


@dataclass(frozen=True)
class PlatformBase:
    id: str
    environment_id: str
    code: str
    engine: str
    display_name: str = ""
    status: ConfigStatus = ConfigStatus.ENABLED
    aliases: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    revision: int = 1


@dataclass(frozen=True)
class PlatformWorkshop:
    id: str
    base_id: str
    code: str
    display_name: str = ""
    table_prefix: str = ""
    redis_key_prefix: str = ""
    loki_labels: dict[str, str] = field(default_factory=dict)
    status: ConfigStatus = ConfigStatus.ENABLED
    aliases: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    revision: int = 1


@dataclass(frozen=True)
class PlatformSecretReference:
    id: str
    code: str
    provider: SecretProvider
    ref: str
    purpose: str = ""
    status: ConfigStatus = ConfigStatus.ENABLED
    metadata: dict[str, Any] = field(default_factory=dict)
    revision: int = 1


@dataclass(frozen=True)
class PlatformSecret:
    id: str
    code: str
    provider: SecretProvider = SecretProvider.ENCRYPTED_DB
    ref: str = ""
    purpose: str = ""
    status: SecretStatus = SecretStatus.ENABLED
    active_version: int = 0
    masked_summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    revision: int = 1


@dataclass(frozen=True)
class PlatformSecretVersion:
    id: str
    secret_id: str
    version: int
    ciphertext: str
    nonce: str
    key_id: str
    algorithm: str
    status: SecretVersionStatus = SecretVersionStatus.ACTIVE
    created_by: str = ""


@dataclass(frozen=True)
class RuntimeConfigDefinition:
    id: str
    key: str
    value_type: ConfigValueType
    default: Any = None
    sensitive: bool = False
    bootstrap_only: bool = False
    service_names: tuple[str, ...] = ()
    description: str = ""
    status: ConfigStatus = ConfigStatus.ENABLED
    revision: int = 1


@dataclass(frozen=True)
class RuntimeConfigValue:
    id: str
    definition_id: str
    key: str
    scope_type: RuntimeConfigScope = RuntimeConfigScope.GLOBAL
    scope_code: str = "*"
    service_name: str = ""
    value: Any = None
    secret_ref: str = ""
    status: ConfigStatus = ConfigStatus.ENABLED
    revision: int = 1


@dataclass(frozen=True)
class PlatformResourceBinding:
    id: str
    code: str
    scope_type: ResourceScopeType
    resource_kind: ResourceKind
    environment_id: str | None = None
    base_id: str | None = None
    workshop_id: str | None = None
    connector_id: str | None = None
    engine: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    secret_refs: dict[str, str] = field(default_factory=dict)
    status: ConfigStatus = ConfigStatus.ENABLED
    revision: int = 1


@dataclass(frozen=True)
class PlatformAccessGrant:
    id: str
    subject_type: SubjectType
    subject_code: str
    effect: AccessEffect
    environment_id: str | None = None
    base_id: str | None = None
    workshop_id: str | None = None
    tool_scope: list[str] = field(default_factory=list)
    resource_scope: dict[str, Any] = field(default_factory=dict)
    condition: dict[str, Any] = field(default_factory=dict)
    priority: int = 100
    status: ConfigStatus = ConfigStatus.ENABLED
    revision: int = 1


@dataclass(frozen=True)
class PlatformConfigAudit:
    id: str
    entity_type: str
    entity_id: str
    action: str
    actor_id: str = ""
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""
