"""Deployment-only admission of the current local MES source; no model/network work."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from app.modules.knowledge.domain.code_contracts import COMPONENTS, CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_repository import CodeRepository
from app.modules.knowledge.infrastructure.code_source import FrozenSource, LocalCodeCollector
from app.modules.knowledge.infrastructure.code_snapshot_directory import CodeSnapshotDirectory
from app.modules.knowledge.infrastructure.storage import insert
from app.shared.database import Database

FIRST_COVERAGE = {
    "factory_frontend": ["work_order.publish", "work_order.start", "work_order.report"],
    "group_frontend": ["application.enable", "application.disable", "application.authorization"],
    "backend": [
        "referenced_handlers",
        "formula",
        "master_recipe",
        "material",
        "configuration",
        "permission",
    ],
}


def admission_statistics(source: FrozenSource) -> dict[str, Any]:
    return {
        "source_kind": "local_bundle",
        "svn_revision": None,
        "manifest_hash": source.source_ref["manifest_hash"],
        "file_count": len(source.manifest["files"]),
        "raw_bytes": sum(row["size_bytes"] for row in source.manifest["files"]),
        "roles": dict(Counter(row["role"] for row in source.manifest["files"])),
        "excluded": dict(Counter(row["reason"] for row in source.manifest["excluded"])),
        "business_analysis": "not_started",
    }


class CodeBaselineAdmission:
    def __init__(self, database: Database, snapshot_root: Path) -> None:
        self.database = database
        self.repository = CodeRepository(database)
        self.directory = CodeSnapshotDirectory(snapshot_root)

    def admit(
        self,
        collector: LocalCodeCollector,
        frozen: FrozenSource,
        *,
        source_code: str,
        base_code: str,
        local_root_key: str,
    ) -> dict[str, Any]:
        if not local_root_key or len(local_root_key) > 128:
            raise CodeKnowledgeError("code_root_registration_invalid")
        binding = self.repository.register(
            code=source_code,
            base_code=base_code,
            config={
                "local_root_key": local_root_key,
                "components": COMPONENTS,
                "first_coverage": FIRST_COVERAGE,
                "approved_dependency_roots": list(COMPONENTS.values()),
            },
        )
        identifier = self.publish(binding["source_id"], collector, frozen)
        return {**binding, "source_snapshot_id": identifier, **admission_statistics(frozen)}

    def publish(self, source_id: str, collector: LocalCodeCollector, frozen: FrozenSource) -> str:
        identifier = self.repository.freeze_source(source_id, frozen.source_ref, frozen.manifest)
        self.directory.publish(identifier, frozen, collector)
        # No source body in SQL. Same bytes and configuration reuse the same immutable identity.
        with self.database.unit_of_work():
            for entry in frozen.manifest["files"]:
                insert(
                    self.database,
                    "code_source_file",
                    dict(
                        source_snapshot_id=identifier,
                        file_id=entry["file_id"],
                        relative_path=entry["path"],
                        role=entry["role"],
                        metadata_json=entry,
                        artifact_json={
                            "storage": "runtime_source_volume",
                            "source_snapshot_id": identifier,
                            "raw_path": "raw/" + entry["path"],
                            "text_path": "text/" + entry["path"],
                            "available": True,
                        },
                    ),
                    conflict="on conflict(source_snapshot_id,file_id) do nothing",
                )
        return identifier
