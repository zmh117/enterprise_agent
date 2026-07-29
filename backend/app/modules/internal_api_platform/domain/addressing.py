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


@dataclass(frozen=True)
class RevisionResource:
    """A generation-local exact Resource Revision projection.

    The connection values exist only in the immutable in-memory generation.
    Persisted generation metadata stores IDs and active Secret versions, never
    these resolved values.
    """

    resource_revision_id: str
    resource_id: str
    environment_code: str
    base_code: str
    workshop_code: str
    kind: ResourceKind
    engine: DatabaseEngine
    database: DatabaseConnection | None = None
    redis: RedisConnection | None = None
    loki: LokiConnection | None = None
