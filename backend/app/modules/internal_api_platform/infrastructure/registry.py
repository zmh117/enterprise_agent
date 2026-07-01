from __future__ import annotations

from ..domain.addressing import ResourceBinding, TargetRef
from ..domain.errors import PolicyViolation, ResolutionError
from ..domain.topology import ResourceKind, Topology


class TopologyRegistry:
    """In-memory projection of the topology. A DB-backed implementation can replace this."""

    def __init__(self, topology: Topology) -> None:
        self._topology = topology

    @property
    def topology(self) -> Topology:
        return self._topology

    def resolve(self, target: TargetRef) -> ResourceBinding:
        environment = self._topology.environment(target.environment)
        if environment is None:
            raise ResolutionError(f"Unknown environment: {target.environment}")
        base = environment.base(target.base)
        if base is None:
            raise ResolutionError(f"Unknown base: {target.environment}/{target.base}")

        workshop = None
        if target.workshop is not None:
            workshop = base.workshop(target.workshop)
            if workshop is None:
                raise ResolutionError(
                    f"Unknown workshop: {target.environment}/{target.base}/{target.workshop}"
                )
        elif base.is_partitioned and target.kind is ResourceKind.DATABASE:
            raise PolicyViolation(
                f"Base {target.base} is workshop-partitioned; a workshop is required"
            )

        return ResourceBinding(
            environment=environment,
            base=base,
            kind=target.kind,
            workshop=workshop,
            engine=base.engine,
            database=base.database,
            redis=base.redis,
            loki=base.loki,
        )
