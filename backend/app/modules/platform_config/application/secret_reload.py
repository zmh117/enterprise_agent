from __future__ import annotations

from typing import Protocol

from app.shared.database import Database

from ..infrastructure.repository import PlatformConfigRepository
from .snapshot import PlatformTopologySnapshotBuilder, RuntimeTopologySnapshot


class RuntimeSnapshotReloadTarget(Protocol):
    def apply_runtime_snapshot(
        self,
        snapshot: RuntimeTopologySnapshot,
    ) -> bool: ...


class SecretChangeReloader:
    """Consume persisted Secret changes and atomically preserve the LKG."""

    def __init__(
        self,
        *,
        database: Database,
        snapshot_builder: PlatformTopologySnapshotBuilder,
        target: RuntimeSnapshotReloadTarget,
    ) -> None:
        self.database = database
        self.repository = snapshot_builder.repository
        self.snapshot_builder = snapshot_builder
        self.target = target

    def poll_once(self, *, limit: int = 50) -> dict[str, int]:
        summary = {"claimed": 0, "succeeded": 0, "failed": 0}
        with self.database.unit_of_work():
            events = self.repository.claim_secret_change_events(limit=limit)
        summary["claimed"] = len(events)
        for event in events:
            try:
                snapshot = self.snapshot_builder.build_runtime_snapshot()
                succeeded = self.target.apply_runtime_snapshot(snapshot)
            except Exception:
                succeeded = False
            with self.database.unit_of_work():
                self.repository.complete_secret_change_event(
                    event_id=str(event["id"]),
                    succeeded=succeeded,
                    error_summary="related resource reload failed",
                )
            summary["succeeded" if succeeded else "failed"] += 1
        return summary

    def close(self) -> None:
        self.database.close()


def build_secret_change_reloader(
    *,
    database: Database,
    master_key: str,
    target: RuntimeSnapshotReloadTarget,
) -> SecretChangeReloader:
    from app.modules.internal_api_platform.infrastructure.secrets import (
        DbBackedSecretResolver,
    )

    repository = PlatformConfigRepository(database)
    builder = PlatformTopologySnapshotBuilder(
        repository,
        resolver=DbBackedSecretResolver(
            repository,
            master_key=master_key,
        ),
    )
    return SecretChangeReloader(
        database=database,
        snapshot_builder=builder,
        target=target,
    )
