"""显式三库测试替换的事务适配器；不适用于跨物理内容库写入。"""

from typing import Any

from app.modules.knowledge.application.content_access import ContentRepository
from app.modules.knowledge.domain.chunking import KEEP_IDS_PROFILE
from app.modules.knowledge.domain.identity import now, stable_id
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.domain.sync import replacement_manifest
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.infrastructure.import_repository import ImportRepository
from app.modules.knowledge.infrastructure.storage import insert
from app.modules.knowledge.infrastructure.sync_repository import SyncRepository
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
from app.modules.knowledge.infrastructure.chunk_repository import json_value


class ReplacementRepository(SyncRepository):
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

    def assert_same_content(self, records: ContentRepository) -> None:
        if not isinstance(records, GovernanceStore):
            raise ExportValidationError("knowledge_replacement_content_location_mismatch")
        other = records.database
        if other is self.database:
            return
        if self.database.engine != "postgres" or other.engine != "postgres":
            raise ExportValidationError("knowledge_replacement_content_location_mismatch")
        # 连接配置可以使用别名；比较集群身份和数据库 OID，不能只比较主机名或库名。
        query = (
            "select (pg_control_system()).system_identifier::text as cluster_id, "
            "(select oid::text from pg_database where datname=current_database()) as database_id"
        )
        try:
            left, right = self.database.execute_one(query), other.execute_one(query)
        except Exception:
            raise ExportValidationError(
                "knowledge_replacement_content_location_unverified"
            ) from None
        if not left or left != right:
            raise ExportValidationError("knowledge_replacement_content_location_mismatch")

    def apply_content(self, run_id: str) -> None:
        # 必须由调用方在包含发布和 finish 的同一事务内调用。
        run = self.run(run_id, lock=True)
        if run["phase"] != "VERIFIED":
            raise ExportValidationError("knowledge_sync_phase_invalid")
        self.assert_baseline(run_id)
        for candidate in self.candidates(run_id):
            document_id = candidate["document_id"]
            if candidate["outcome"] != "baseline":
                revision = self.revision(candidate["candidate_revision_id"])
                number = json_value(revision["source_snapshot"])["detail"]["number"]
                self.database.execute(
                    f"update {self.t('document')} set current_revision_id=?,document_kind=?,"
                    "lifecycle_state='active',source_observed_stamp_raw=?,external_number=?,last_seen_at=? where id=?",
                    (
                        candidate["candidate_revision_id"],
                        candidate["candidate_kind"],
                        candidate["observed_stamp"],
                        str(number),
                        now(),
                        document_id,
                    ),
                )
            for base_id, state in candidate["candidate_members_json"].items():
                insert(
                    self.database,
                    "knowledge_base_document",
                    {
                        "knowledge_base_id": base_id,
                        "document_id": document_id,
                        "state": state,
                        "created_at": now(),
                    },
                    conflict="on conflict(knowledge_base_id,document_id) do update set state=excluded.state",
                )
        ImportRepository(self.database).resolve_targets(run["source_id"])

    def finish(self, run_id: str) -> None:
        self.database.execute(
            f"update {self.t('sync_run')} set phase='ACTIVATED',active=0,activated_watermark=?,"
            "error_code=NULL,updated_at=? where id=? and phase='VERIFIED'",
            (now(), now(), run_id),
        )
