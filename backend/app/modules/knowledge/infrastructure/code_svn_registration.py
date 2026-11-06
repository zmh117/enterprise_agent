"""Explicit deployment verification; does not enable collection or grant permissions."""

from pathlib import Path
from typing import Any

from app.modules.knowledge.infrastructure.code_baseline import CodeBaselineAdmission
from app.modules.knowledge.infrastructure.code_svn_admission import compare_baseline
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.domain.normalization import canonical_json, digest
from app.modules.knowledge.infrastructure.code_repository import CodeRepository, decoded
from app.modules.knowledge.infrastructure.code_source_registry import CodeSourceRegistry
from app.modules.knowledge.infrastructure.storage import source_lock, table
from app.shared.database import Database


class CodeSvnRegistration:
    def __init__(self, database: Database, registry: CodeSourceRegistry, source_root: Path) -> None:
        self.db, self.registry, self.source_root = database, registry, source_root
        self.repo = CodeRepository(database)

    def verify(
        self,
        source_id: str,
        registration_key: str,
        revision: int,
        *,
        local_snapshot_id: str | None = None,
        establish_origin: bool = False,
        commit: bool = False,
    ) -> dict[str, Any]:
        binding = self.repo.binding(source_id)
        registration, collector = self.registry.get(registration_key)
        local = (
            self.db.execute_one(
                f"select manifest_json from {table(self.db, 'code_source_snapshot')} where id=? and source_id=? and source_kind='local_bundle'",
                (local_snapshot_id, source_id),
            )
            if local_snapshot_id
            else None
        )
        if local_snapshot_id and not local:
            raise CodeKnowledgeError("code_source_unavailable")
        with collector.prepare(revision) as (admission, frozen):
            mapping = (
                compare_baseline(decoded(local["manifest_json"]), frozen.manifest)
                if local
                else {"state": "UNMAPPED"}
            )
            result = {
                "source_id": source_id,
                "revision": revision,
                "mapping": mapping,
                "manifest_hash": frozen.source_ref["manifest_hash"],
                "file_count": len(frozen.manifest["files"]),
                "externals_complete": frozen.manifest["externals"]["complete"],
            }
            if not commit:
                return result
            if mapping["state"] != "VERIFIED" and not establish_origin:
                raise CodeKnowledgeError("code_baseline_unmapped_origin_required")
            if not result["externals_complete"]:
                raise CodeKnowledgeError("code_svn_externals_unresolved")
            config = {
                **decoded(binding["config_json"]),
                "svn_verified": True,
                "svn_registration": {"key": registration["key"], "digest": registration["digest"]},
                "svn_identity": {
                    "repository_uuid": collector.source.expected_uuid,
                    "branch_path": collector.source.branch_path,
                },
                "svn_components": collector.components,
            }
            with (
                source_lock(self.db, "code-svn:" + source_id),
                source_lock(self.db, source_id),
                self.db.unit_of_work(),
            ):
                current = self.repo.binding(source_id)
                if current["config_hash"] != binding["config_hash"]:
                    raise CodeKnowledgeError("code_source_configuration_changed")
                if current["config_hash"] == digest(config):
                    snapshot_id = CodeBaselineAdmission(self.db, self.source_root).publish(
                        source_id, admission, frozen
                    )
                    return {
                        **result,
                        "source_snapshot_id": snapshot_id,
                        "enabled": bool(current["enabled"]),
                    }
                busy = self.db.execute_one(
                    f"select id from {table(self.db, 'code_build')} where source_id=? and stage not in ('READY','ACTIVATED','FAILED','CANCELLED','INTERRUPTED') limit 1",
                    (source_id,),
                )
                if busy:
                    raise CodeKnowledgeError("code_source_busy")
                self.db.execute(
                    f"update {table(self.db, 'code_binding')} set config_json=?,config_hash=?,config_revision=config_revision+1,"
                    "enabled=0,demand_enabled=0,collected_revision=?,collected_from_revision=?,next_run_at=null,updated_at=? where source_id=?",
                    (canonical_json(config), digest(config), revision, revision, now(), source_id),
                )
                snapshot_id = CodeBaselineAdmission(self.db, self.source_root).publish(
                    source_id, admission, frozen
                )
                proof = {
                    "local_snapshot_id": local_snapshot_id,
                    "svn_source_snapshot_id": snapshot_id,
                    "revision": revision,
                    **mapping,
                }
                collection = {
                    "baseline_mapping": proof,
                    "origin_revision": revision,
                    "last_source_snapshot_id": snapshot_id,
                    "state": "IDLE",
                }
                self.db.execute(
                    f"update {table(self.db, 'code_binding')} set collection_json=? where source_id=?",
                    (canonical_json(collection), source_id),
                )
                return {**result, "source_snapshot_id": snapshot_id, "enabled": False}
