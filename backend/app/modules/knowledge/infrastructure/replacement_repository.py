"""显式三库测试替换的事务适配器；不适用于跨物理内容库写入。"""

from typing import Any

from app.modules.knowledge.application.content_access import ContentRepository
from app.modules.knowledge.domain.chunking import KEEP_IDS_PROFILE
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.domain.sync import replacement_manifest
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.infrastructure.sync_repository import SyncRepository
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository


class ReplacementRepository(SyncRepository):
    def assert_same_content(self, records: ContentRepository) -> None:
        try:
            super().assert_same_content(records)
        except ExportValidationError as exc:
            suffix = exc.code.removeprefix("knowledge_sync_content_")
            raise ExportValidationError("knowledge_replacement_content_" + suffix) from None

    def indexes(self, run_id: str) -> dict[str, dict[str, Any]]:
        run = self.run(run_id)
        binding = self.assert_configuration(run)
        if not replacement_manifest(run["manifest_json"]) or run["phase"] not in {
            "INDEXING",
            "VERIFIED",
        }:
            raise ExportValidationError("knowledge_replacement_scope_invalid")
        result = {}
        vectors = VectorRepository(self.database)
        for kind, code in binding["configuration_json"]["base_codes"].items():
            base_id = stable_id("base", code)
            index = vectors.get("sync-" + stable_id("sync-index", run_id, base_id))
            if not index or (
                index["state"] != "READY"
                or index["knowledge_base_id"] != base_id
                or index["source_id"] != run["source_id"]
                or index["sync_run_id"] != run_id
                or index["chunk_profile_hash"] != KEEP_IDS_PROFILE.fingerprint
                or index["expected_document_count"] != run["manifest_json"][kind]["record_count"]
            ):
                raise ExportValidationError("knowledge_replacement_indexes_not_ready")
            result[base_id] = index
        return result

    def resources(self, run_id: str, *, lock: bool = False) -> list[dict[str, Any]]:
        run = self.run(run_id)
        binding = self.assert_configuration(run)
        expected = {row["id"]: row for row in run["resource_baseline_json"]}
        if set(expected) != set(binding["configuration_json"]["resource_ids"]):
            raise ExportValidationError("knowledge_replacement_resource_scope_changed")
        store = GovernanceStore(self.database)
        base_ids = [
            stable_id("base", code) for code in binding["configuration_json"]["base_codes"].values()
        ]
        current = self.database.execute(
            f"select id from {self.t('retrieval_resource')} where knowledge_base_id in ({','.join('?' for _ in base_ids)})",
            tuple(base_ids),
        )
        if {row["id"] for row in current} != set(expected):
            raise ExportValidationError("knowledge_replacement_resource_scope_changed")
        result = []
        for resource_id, before in expected.items():
            resource = store.get("retrieval_resource", resource_id, lock=lock)
            if (
                any(resource[key] != value for key, value in before.items())
                or resource["status"] != "enabled"
                or resource["draft_revision_id"] is not None
                or not resource["published_revision_id"]
            ):
                raise ExportValidationError("knowledge_replacement_resource_changed")
            result.append(resource)
        return result
