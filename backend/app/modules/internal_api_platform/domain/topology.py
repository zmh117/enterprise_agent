from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ResourceKind(str, Enum):
    DATABASE = "database"
    REDIS = "redis"
    LOKI = "loki"


class DatabaseEngine(str, Enum):
    MYSQL = "mysql"
    SQLSERVER = "sqlserver"
    ORACLE = "oracle"


@dataclass(frozen=True)
class DatabaseConnection:
    host: str
    port: int
    database: str
    user: str
    password: str


@dataclass(frozen=True)
class RedisConnection:
    host: str
    port: int
    db: int = 0
    password: str = ""


@dataclass(frozen=True)
class LokiConnection:
    base_url: str
    tenant: str = ""


@dataclass(frozen=True)
class Workshop:
    """A logical partition inside a base. Not an independently connected resource."""

    code: str
    table_prefix: str
    redis_key_prefix: str
    loki_label: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Base:
    """A base addressed by business code. Owns base-level DB/Redis/Loki resources."""

    code: str
    engine: DatabaseEngine
    database: DatabaseConnection | None = None
    redis: RedisConnection | None = None
    loki: LokiConnection | None = None
    workshops: dict[str, Workshop] = field(default_factory=dict)

    @property
    def is_partitioned(self) -> bool:
        return bool(self.workshops)

    def workshop(self, code: str) -> Workshop | None:
        return self.workshops.get(code)


@dataclass(frozen=True)
class Environment:
    code: str
    bases: dict[str, Base] = field(default_factory=dict)

    def base(self, code: str) -> Base | None:
        return self.bases.get(code)


@dataclass(frozen=True)
class Topology:
    environments: dict[str, Environment] = field(default_factory=dict)

    def environment(self, code: str) -> Environment | None:
        return self.environments.get(code)
