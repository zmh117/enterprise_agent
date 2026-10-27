"""显式维护转换；保留原集合与数值，只验证并登记可变内容合同。"""

from typing import Any
import uuid

from app.modules.knowledge.application.ports import IncrementalQdrantPort
from app.modules.knowledge.application.source_service import KnowledgeAdministration
from app.modules.knowledge.domain.chunking import KEEP_IDS_PROFILE
from app.modules.knowledge.domain.hybrid import hybrid_index, validate_sparse
from app.modules.knowledge.domain.identity import now, stable_id
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.domain.resource_configuration import configuration_values
from app.modules.knowledge.domain.storage_connection import DEFAULT_QDRANT, stored_config
from app.modules.knowledge.domain.vector_contract import VectorError, fingerprint, validate_vector
from app.modules.knowledge.domain.vector_points import batches, payload, point_id
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.infrastructure.incremental_repository import IncrementalVectorRepository
from app.modules.knowledge.infrastructure.sync_repository import SyncRepository
from app.shared.database import Database


class IncrementalAdoption:
    def __init__(
        self,
        database: Database,
        administration: KnowledgeAdministration,
        qdrant: IncrementalQdrantPort,
    ) -> None:
        self.database, self.administration, self.qdrant = database, administration, qdrant
        self.repo, self.vectors = SyncRepository(database), IncrementalVectorRepository(database)
        self.store = GovernanceStore(database)

    def _scope(self, binding_id: str, code: str) -> tuple[dict[str, Any], dict[str, Any]]:
        binding = self.repo.binding(binding_id)
        if binding["enabled"] or self.repo.active_run(binding_id):
            raise ExportValidationError("knowledge_incremental_adoption_stop_required")
        index = self.vectors.get(code)
        bases = {
            stable_id("base", code) for code in binding["configuration_json"]["base_codes"].values()
        }
        if (
            not index
            or index["state"] != "READY"
            or index["knowledge_base_id"] not in bases
            or index["source_id"] not in {None, binding["source_id"]}
            or index["profile"] != self.vectors.profile
        ):
            raise VectorError("knowledge_incremental_adoption_scope_invalid")
        conflict = self.database.execute_one(
            f"select id from {self.repo.t('vector_index')} where knowledge_base_id=? and incremental=1 and state<>'RETIRED' and id<>?",
            (index["knowledge_base_id"], index["id"]),
        )
        foreign = self.database.execute_one(
            f"select d.id from {self.repo.t('knowledge_base_document')} m join {self.repo.t('document')} d on d.id=m.document_id "
            "where m.knowledge_base_id=? and m.state='included' and d.lifecycle_state='active' and d.source_id<>? limit 1",
            (index["knowledge_base_id"], binding["source_id"]),
        )
        if conflict or foreign:
            raise VectorError("knowledge_incremental_adoption_scope_invalid")
        if (
            binding["configuration_json"].get("collector")
            and index["chunk_profile_hash"] != KEEP_IDS_PROFILE.fingerprint
        ):
            raise VectorError("knowledge_sync_resource_profile_changed")
        return binding, index

    def _resources(self, index: dict[str, Any], *, lock: bool = False) -> list[dict[str, Any]]:
        suffix = " for update" if lock and self.database.engine == "postgres" else ""
        resources = self.database.execute(
            f"select * from {self.repo.t('retrieval_resource')} where knowledge_base_id=? and status<>'archived' order by id{suffix}",
            (index["knowledge_base_id"],),
        )
        for resource in resources:
            for key in ("published_revision_id", "draft_revision_id"):
                if not resource[key]:
                    continue
                revision = self.store.get("retrieval_revision", resource[key])
                config = stored_config(revision.get("storage_config_json"))
                local = config is None or config == {
                    "postgres": {"mode": "platform"},
                    "qdrant": {"url": DEFAULT_QDRANT, "api_key_ref": ""},
                }
                if revision["index_id"] != index["id"] or not local:
                    raise VectorError("knowledge_incremental_adoption_resource_conflict")
        return resources

    def run(self, binding_id: str, code: str, *, actor_id: str, commit: bool) -> dict[str, Any]:
        self.administration.require_admin(actor_id)
        initial = self.repo.binding(binding_id)
        with self.repo.source_lock(initial["source_id"]):
            binding, index = self._scope(binding_id, code)
            resources = self._resources(index)
            if index.get("incremental") == 1:
                return {"index_id": index["id"], "mode": "already_adopted", "encoded": 0}
            self.vectors.assert_current(index)
            self.qdrant.check(index)
            verified = self._verify_points(index, commit=commit)
            if not commit:
                return {
                    "index_id": index["id"],
                    "mode": "preflight",
                    "verified": verified,
                    "encoded": 0,
                }
            target = {**index, "incremental": 1, "source_id": binding["source_id"]}
            self.qdrant.ensure(target)
            with self.database.unit_of_work():
                self.administration.require_admin(actor_id)
                current_binding, current_index = self._scope(binding_id, code)
                if (
                    binding != current_binding
                    or index != current_index
                    or self._resources(index, lock=True) != resources
                ):
                    raise VectorError("knowledge_incremental_adoption_scope_changed")
                self.database.execute(
                    f"update {self.repo.t('vector_index')} set incremental=1,source_id=?,updated_at=? where id=?",
                    (binding["source_id"], now(), index["id"]),
                )
                for resource in resources:
                    self._convert_resource(resource, target, actor_id)
            return {
                "index_id": index["id"],
                "mode": "adopted",
                "verified": verified,
                "encoded": 0,
                "resources": len(resources),
            }

    def _verify_points(self, index: dict[str, Any], *, commit: bool) -> int:
        verified = 0
        target = {**index, "incremental": 1}
        for batch in batches(
            self.vectors.rows(index["knowledge_base_id"], index["chunk_profile_hash"]), 32
        ):
            ids = [point_id(index, row) for row in batch]
            points = self.qdrant.retrieve(index, ids)
            ledger = self.database.execute(
                f"select chunk_id,point_id,state,embedding_text_hash from {self.repo.t('vector_index_item')} where index_id=? and chunk_id in ({','.join('?' for _ in batch)})",
                (index["id"], *(row["id"] for row in batch)),
            )
            actual = {
                row["chunk_id"]: (row["point_id"], row["state"], row["embedding_text_hash"])
                for row in ledger
            }
            if actual != {
                row["id"]: (point_id(index, row), "INDEXED", row["embedding_hash"]) for row in batch
            }:
                raise VectorError("knowledge_vector_manifest_conflict")
            for row in batch:
                point = points.get(point_id(index, row))
                # 上次转换中断可能已经设置该批 searchable；两种已知形状均可恢复。
                if not point or point.get("payload") not in (
                    payload(index, row),
                    payload(target, row),
                ):
                    raise VectorError("knowledge_vector_point_conflict")
                validate_vector(point.get("vector"))
                if hybrid_index(index):
                    validate_sparse(point.get("sparse_vector"))
            if commit:
                self.qdrant.set_searchable(target, ids, True)
            verified += len(batch)
        if verified != index["expected_chunk_count"] or self.qdrant.count(index) != verified:
            raise VectorError("knowledge_vector_count_mismatch")
        return verified

    def _convert_resource(
        self, resource: dict[str, Any], index: dict[str, Any], actor_id: str
    ) -> None:
        updates = {}
        for key in ("published_revision_id", "draft_revision_id"):
            if not resource[key]:
                continue
            old = self.store.get("retrieval_revision", resource[key])
            identifier = str(uuid.uuid4())
            values = configuration_values(
                resource_id=resource["id"],
                base_id=resource["knowledge_base_id"],
                index=index,
                source_id=index["source_id"],
                source_hash="",
                members=[],
                storage=stored_config(old.get("storage_config_json")),
                version=4,
            )
            self.store.add(
                "retrieval_revision",
                {
                    "id": identifier,
                    "resource_id": resource["id"],
                    "revision": self.store.next_resource_revision(resource["id"]),
                    **values,
                    "created_by": actor_id,
                    "created_at": now(),
                    "published_by": actor_id if key == "published_revision_id" else None,
                    "published_at": now() if key == "published_revision_id" else None,
                },
            )
            self.store.add(
                "retrieval_verification",
                {
                    "id": str(uuid.uuid4()),
                    "resource_id": resource["id"],
                    "resource_revision": resource["revision"] + 1,
                    "revision_id": identifier,
                    "config_hash": values["config_hash"],
                    "status": "VERIFIED",
                    "evidence_hash": fingerprint(
                        {"adopted_index": index["id"], "config_hash": values["config_hash"]}
                    ),
                    "error_code": None,
                    "created_by": actor_id,
                    "created_at": now(),
                },
            )
            updates[key] = identifier
        if updates:
            self.database.execute(
                f"update {self.repo.t('retrieval_resource')} set {','.join(key + '=?' for key in updates)},revision=revision+1,updated_at=? where id=?",
                (*updates.values(), now(), resource["id"]),
            )
            self.administration.record(
                "resource.incremental_adopted",
                actor_id=actor_id,
                identifier=resource["id"],
                revision=resource["revision"] + 1,
            )
