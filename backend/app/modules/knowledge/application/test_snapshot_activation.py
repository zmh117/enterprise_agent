"""显式维护用例：验证三库快照，再原子接续已有发布；绝不首次授权新库。"""

from typing import Any, Protocol
from contextlib import AbstractContextManager
import uuid

from app.modules.knowledge.application.content_access import ContentRepository, KnowledgeContent
from app.modules.knowledge.application.ports import VectorRepository
from app.modules.knowledge.application.resource_service import KnowledgeResourceService
from app.modules.knowledge.application.vector_service import VectorService
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.domain.storage_connection import stored_config
from app.modules.knowledge.domain.vector_contract import fingerprint


class ReplacementStore(Protocol):
    def run(self, run_id: str, *, lock: bool = False) -> dict[str, Any]: ...
    def source_lock(self, source_id: str) -> AbstractContextManager[None]: ...
    def indexes(self, run_id: str) -> dict[str, dict[str, Any]]: ...
    def resources(self, run_id: str, *, lock: bool = False) -> list[dict[str, Any]]: ...
    def assert_same_content(self, records: ContentRepository) -> None: ...
    def advance(self, run_id: str, *, expected_phase: str, phase: str) -> None: ...
    def apply_content(self, run_id: str) -> None: ...
    def finish(self, run_id: str) -> None: ...
    def summary(self, run_id: str) -> dict[str, Any]: ...


class TestSnapshotActivation:
    __test__ = False

    def __init__(
        self,
        repository: ReplacementStore,
        resources: KnowledgeResourceService,
        candidates: VectorRepository,
    ) -> None:
        self.repository, self.resources, self.candidates = repository, resources, candidates

    def run(self, run_id: str, *, actor_id: str) -> dict[str, Any]:
        repo, service, store = self.repository, self.resources, self.resources.store
        service.require_admin(actor_id)
        initial = repo.run(run_id)
        with repo.source_lock(initial["source_id"]):
            run = repo.run(run_id)
            if run["phase"] == "ACTIVATED":
                return repo.summary(run_id)
            indexes, resources = repo.indexes(run_id), repo.resources(run_id)
            if service.embedding is None or service.qdrant is None:
                raise ExportValidationError("knowledge_replacement_verifier_unavailable")
            proofs = {
                base: VectorService(self.candidates, service.embedding, service.qdrant).verify(
                    index
                )
                for base, index in indexes.items()
            }
            selections = {}
            for resource in resources:
                previous = store.get("retrieval_revision", resource["published_revision_id"])
                selected = stored_config(previous.get("storage_config_json"))
                base_id = resource["knowledge_base_id"]
                if base_id not in indexes:
                    raise ExportValidationError("knowledge_replacement_resource_scope_changed")
                with service.content(
                    selected, base_id=base_id, revision_id=previous["id"]
                ) as content:
                    repo.assert_same_content(content.records)
                    # 同库别名不等于同向量端点：已发布连接也须看到完整候选集合。
                    VectorService(
                        self.candidates, service.embedding, content.qdrant or service.qdrant
                    ).verify(indexes[base_id])
                selections[resource["id"]] = selected
            if run["phase"] == "INDEXING":
                repo.advance(run_id, expected_phase="INDEXING", phase="VERIFIED")
            with store.unit_of_work():
                service.require_admin(actor_id)
                repo.run(run_id, lock=True)
                if (
                    repo.resources(run_id, lock=True) != resources
                    or repo.indexes(run_id) != indexes
                ):
                    raise ExportValidationError("knowledge_replacement_resource_changed")
                repo.apply_content(run_id)
                for index in indexes.values():
                    service.vectors.assert_current(index)
                local = KnowledgeContent(store, service.vectors)
                for resource in resources:
                    base_id = resource["knowledge_base_id"]
                    config, _, _ = service._content_configuration(
                        resource,
                        indexes[base_id]["id"],
                        local,
                        selections[resource["id"]],
                        version=4,
                    )
                    revision_id = str(uuid.uuid4())
                    store.add(
                        "retrieval_revision",
                        {
                            "id": revision_id,
                            "resource_id": resource["id"],
                            "revision": store.next_resource_revision(resource["id"]),
                            **config,
                            "created_by": actor_id,
                            "created_at": now(),
                        },
                    )
                    store.add(
                        "retrieval_verification",
                        {
                            "id": str(uuid.uuid4()),
                            "resource_id": resource["id"],
                            "resource_revision": resource["revision"],
                            "revision_id": revision_id,
                            "config_hash": config["config_hash"],
                            "status": "VERIFIED",
                            "evidence_hash": fingerprint(
                                {
                                    "config_hash": config["config_hash"],
                                    "index_verification": proofs[base_id],
                                }
                            ),
                            "error_code": None,
                            "created_by": actor_id,
                            "created_at": now(),
                        },
                    )
                    store.publish(resource["id"], revision_id, actor_id)
                    service.record(
                        "resource.test_snapshot_replaced",
                        actor_id=actor_id,
                        identifier=resource["id"],
                        revision=resource["revision"] + 1,
                    )
                repo.finish(run_id)
            return repo.summary(run_id)
