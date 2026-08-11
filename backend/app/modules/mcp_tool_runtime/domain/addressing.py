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
class ResourceBinding:
    """One published Resource resolved for the current MCP Tool call."""

    environment: Environment
    base: Base
    kind: ResourceKind
    workshop: Workshop | None
    engine: DatabaseEngine
    database: DatabaseConnection | None = None
    redis: RedisConnection | None = None
    loki: LokiConnection | None = None
