"""受管全量同步的候选索引、资源 CAS 和激活持久化。"""

from typing import Any

from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.infrastructure.candidate_corpus import CandidateCorpus
from app.modules.knowledge.infrastructure.sync_repository import SyncRepository
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
from app.modules.knowledge.domain.identity import now, stable_id
from app.modules.knowledge.domain.normalization import canonical_json


class ManagedActivationRepository(SyncRepository):
    def _online(self, run: dict[str, Any]) -> None:
        if not all(
            item.get("export_format") == "ones-online-full/v1"
            for item in run["manifest_json"].values()
        ):
            raise ExportValidationError("knowledge_sync_activation_scope_invalid")

    def indexes(self, run_id: str) -> dict[str, dict[str, Any]]:
        run = self.run(run_id)
        self._online(run)
        binding = self.assert_configuration(run)
        if run["phase"] not in {"INDEXING", "VERIFIED"}:
            raise ExportValidationError("knowledge_sync_phase_invalid")
        allowed = {
            stable_id("base", code) for code in binding["configuration_json"]["base_codes"].values()
        }
        changed = self.changed_bases(run_id)
        if not changed <= allowed:
            raise ExportValidationError("knowledge_sync_candidate_conflict")
        corpus, vectors = CandidateCorpus(self, run_id), VectorRepository(self.database)
        result: dict[str, dict[str, Any]] = {}
        for base_id in sorted(changed):
            code = "sync-" + stable_id("sync-index", run_id, base_id)
            index = vectors.get(code)
            if (
                not index
                or index["state"] != "READY"
                or index["knowledge_base_id"] != base_id
                or index["source_id"] != run["source_id"]
                or index["sync_run_id"] != run_id
                or index["expected_document_count"] != corpus.count(base_id)
            ):
                raise ExportValidationError("knowledge_sync_indexes_not_ready")
            result[base_id] = index
        return result

    def resources(
        self, run_id: str, *, lock: bool = False, changed_bases: set[str] | None = None
    ) -> list[dict[str, Any]]:
        run = self.run(run_id, lock=lock)
        self._online(run)
        binding = self.assert_configuration(run, lock=lock)
        current = self.scoped_resources(binding, lock=lock)
        baseline = {row["id"]: row for row in run["resource_baseline_json"]}
        keys = (
            "id",
            "knowledge_base_id",
            "status",
            "revision",
            "state_revision",
            "draft_revision_id",
            "published_revision_id",
        )
        if {row["id"] for row in current} != set(baseline) or any(
            {key: row[key] for key in keys} != baseline[row["id"]] for row in current
        ):
            raise ExportValidationError("knowledge_sync_resource_changed")
        pins = self.current_resource_pins(binding, lock=lock)
        if pins != binding["resource_pins_json"]:
            raise ExportValidationError("knowledge_sync_resource_changed")
        affected = changed_bases if changed_bases is not None else self.changed_bases(run_id)
        return [
            row for row in current if row["id"] in pins and row["knowledge_base_id"] in affected
        ]

    def finish_managed(self, run_id: str) -> None:
        """仅供内容/资源发布同一事务结尾调用。"""
        run = self.run(run_id, lock=True)
        binding = self.assert_configuration(run, lock=True)
        pins = self.current_resource_pins(binding, lock=True)
        self.database.execute(
            f"update {self.t('sync_binding')} set resource_pins_json=?,updated_at=? "
            "where id=? and configuration_revision=? and enabled=1",
            (canonical_json(pins), now(), binding["id"], binding["configuration_revision"]),
        )
        self.finish(run_id)
