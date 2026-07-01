from __future__ import annotations

from dataclasses import dataclass

from .topology import (
    Base,
    DatabaseConnection,
    DatabaseEngine,
    Environment,
    LokiConnection,
    RedisConnection,
    ResourceKind,
    Workshop,
)


@dataclass(frozen=True)
class TargetRef:
    """A structured address the Agent uses instead of raw IPs or connection strings."""

    environment: str
    base: str
    kind: ResourceKind
    workshop: str | None = None


@dataclass(frozen=True)
class ResourceBinding:
    """A resolved, concrete resource plus the workshop partition constraints."""

    environment: Environment
    base: Base
    kind: ResourceKind
    workshop: Workshop | None
    engine: DatabaseEngine
    database: DatabaseConnection | None = None
    redis: RedisConnection | None = None
    loki: LokiConnection | None = None
