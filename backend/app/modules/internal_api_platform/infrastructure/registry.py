from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..domain.addressing import ResourceBinding, RevisionResource, TargetRef
from ..domain.errors import PolicyViolation, ResolutionError
from ..domain.topology import ResourceKind, Topology


@dataclass(frozen=True)
class RegistryGeneration:
    topology: Topology
    revision_resources: Mapping[str, RevisionResource]


class TopologyRegistry:
    """In-memory projection of the topology. A DB-backed implementation can replace this."""

    def __init__(
        self,
        topology: Topology,
        *,
        revision_resources: Mapping[str, RevisionResource] | None = None,
    ) -> None:
        self._generation = RegistryGeneration(
            topology=topology,
            revision_resources=dict(revision_resources or {}),
        )

    @property
    def topology(self) -> Topology:
        return self._generation.topology

    def capture(self) -> RegistryGeneration:
        return self._generation

    def replace(
        self,
        topology: Topology,
        *,
        revision_resources: Mapping[str, RevisionResource] | None = None,
    ) -> RegistryGeneration:
        """Atomically replace the immutable topology snapshot."""
        generation = RegistryGeneration(
            topology=topology,
            revision_resources=dict(revision_resources or {}),
        )
        self._generation = generation
        return generation

    def resolve(
        self,
        target: TargetRef,
        *,
        generation: RegistryGeneration | None = None,
    ) -> ResourceBinding:
        captured = generation or self._generation
        environment = captured.topology.environment(target.environment)
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

    def resolve_revision(
        self,
        target: TargetRef,
        *,
        resource_revision_id: str,
        generation: RegistryGeneration | None = None,
    ) -> ResourceBinding:
        captured = generation or self._generation
        revision = captured.revision_resources.get(resource_revision_id)
        if revision is None:
            raise ResolutionError(
                f"Resource Revision is not effective: {resource_revision_id}"
            )
        if (
            revision.kind is not target.kind
            or revision.environment_code != target.environment
            or revision.base_code
            and revision.base_code != target.base
            or revision.workshop_code
            and revision.workshop_code != (target.workshop or "")
        ):
            raise ResolutionError(
                f"Resource Revision does not match requested target: "
                f"{resource_revision_id}"
            )
        environment = captured.topology.environment(target.environment)
        if environment is None:
            raise ResolutionError(f"Unknown environment: {target.environment}")
        base = environment.base(target.base)
        if base is None:
            raise ResolutionError(
                f"Unknown base: {target.environment}/{target.base}"
            )
        workshop = None
        if target.workshop is not None:
            workshop = base.workshop(target.workshop)
            if workshop is None:
                raise ResolutionError(
                    f"Unknown workshop: "
                    f"{target.environment}/{target.base}/{target.workshop}"
                )
        return ResourceBinding(
            environment=environment,
            base=base,
            kind=target.kind,
            workshop=workshop,
            engine=revision.engine,
            database=revision.database,
            redis=revision.redis,
            loki=revision.loki,
        )
