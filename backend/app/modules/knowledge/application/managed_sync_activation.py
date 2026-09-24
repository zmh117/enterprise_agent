"""受管 ONES 同步激活：候选先验证，平台同库事务一次切换。"""

from contextlib import AbstractContextManager
from collections.abc import Callable
from typing import Any, Protocol
import uuid

from app.modules.knowledge.application.content_access import ContentRepository, KnowledgeContent
from app.modules.knowledge.application.ports import VectorRepository
from app.modules.knowledge.application.resource_service import KnowledgeResourceService
from app.modules.knowledge.application.vector_service import VectorService
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.domain.storage_connection import stored_config
from app.modules.knowledge.domain.vector_contract import fingerprint


class ManagedActivationStore(Protocol):
    def run(self, run_id: str, *, lock: bool = False) -> dict[str, Any]: ...
    def source_lock(self, source_id: str) -> AbstractContextManager[None]: ...
    def assert_configuration(
        self, run: dict[str, Any], *, lock: bool = False
    ) -> dict[str, Any]: ...
    def indexes(self, run_id: str) -> dict[str, dict[str, Any]]: ...
    def resources(
        self, run_id: str, *, lock: bool = False, changed_bases: set[str] | None = None
    ) -> list[dict[str, Any]]: ...
    def assert_same_content(self, records: ContentRepository) -> None: ...
    def advance(self, run_id: str, *, expected_phase: str, phase: str) -> None: ...
    def apply_content(self, run_id: str) -> None: ...
    def finish_managed(self, run_id: str) -> None: ...
    def summary(self, run_id: str) -> dict[str, Any]: ...


class ManagedSyncActivation:
    def __init__(
        self,
        repository: ManagedActivationStore,
        resources: KnowledgeResourceService,
        candidates: VectorRepository,
        *,
        check_active: Callable[[], None] | None = None,
    ) -> None:
        self.repository, self.resources, self.candidates = repository, resources, candidates
        self.check_active = check_active

    def run(self, run_id: str) -> dict[str, Any]:
        repo, store = self.repository, self.resources.store
        initial = repo.run(run_id)
        with repo.source_lock(initial["source_id"]):
            if self.check_active is not None:
                self.check_active()
            run = repo.run(run_id)
            if run["phase"] == "ACTIVATED":
                return repo.summary(run_id)
            repo.assert_configuration(run)
            indexes = repo.indexes(run_id)
            affected = set(indexes)
            resources = repo.resources(run_id, changed_bases=affected)
            proofs = self._verify_indexes(indexes)
            selections = self._verify_resources(run, indexes, resources)
            if run["phase"] == "INDEXING":
                repo.advance(run_id, expected_phase="INDEXING", phase="VERIFIED")
            if self.check_active is not None:
                self.check_active()
            with store.unit_of_work():
                self._commit(run_id, indexes, resources, selections, proofs)
            return repo.summary(run_id)

    def _verify_indexes(self, indexes: dict[str, dict[str, Any]]) -> dict[str, str]:
        service = self.resources
        if indexes and (service.embedding is None or service.qdrant is None):
            raise ExportValidationError("knowledge_sync_verifier_unavailable")
        proofs: dict[str, str] = {}
        for base, index in indexes.items():
            assert service.embedding is not None and service.qdrant is not None
            proofs[base] = VectorService(self.candidates, service.embedding, service.qdrant).verify(
                index, check_active=self.check_active
            )
        return proofs

    def _verify_resources(
        self,
        run: dict[str, Any],
        indexes: dict[str, dict[str, Any]],
        resources: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any] | None]:
        repo, service, store = self.repository, self.resources, self.resources.store
        pins = repo.assert_configuration(run)["resource_pins_json"]
        if resources and (service.embedding is None or service.qdrant is None):
            raise ExportValidationError("knowledge_sync_verifier_unavailable")
        selections: dict[str, dict[str, Any] | None] = {}
        for resource in resources:
            assert service.embedding is not None and service.qdrant is not None
            base_id = resource["knowledge_base_id"]
            pinned = service.resolve(base_id)
            if (
                pinned.resource_id != resource["id"]
                or pinned.revision_id != resource["published_revision_id"]
            ):
                raise ExportValidationError("knowledge_sync_resource_changed")
            pin = pins[resource["id"]]
            if (
                indexes[base_id]["profile_hash"] != pin["profile_hash"]
                or indexes[base_id]["chunk_profile_hash"] != pin["chunk_profile_hash"]
            ):
                raise ExportValidationError("knowledge_sync_resource_profile_changed")
            previous = store.get("retrieval_revision", resource["published_revision_id"])
            selected = stored_config(previous.get("storage_config_json"))
            with service.content(selected, base_id=base_id, revision_id=previous["id"]) as content:
                repo.assert_same_content(content.records)
                VectorService(
                    self.candidates, service.embedding, content.qdrant or service.qdrant
                ).verify(indexes[base_id], check_active=self.check_active)
            selections[resource["id"]] = selected
        return selections

    def _commit(
        self,
        run_id: str,
        indexes: dict[str, dict[str, Any]],
        resources: list[dict[str, Any]],
        selections: dict[str, dict[str, Any] | None],
        proofs: dict[str, str],
    ) -> None:
        repo, service, store = self.repository, self.resources, self.resources.store
        locked = repo.run(run_id, lock=True)
        repo.assert_configuration(locked, lock=True)
        if (
            repo.resources(run_id, lock=True, changed_bases=set(indexes)) != resources
            or repo.indexes(run_id) != indexes
        ):
            raise ExportValidationError("knowledge_sync_resource_changed")
        repo.apply_content(run_id)
        for index in indexes.values():
            service.vectors.assert_current(index)
        local = KnowledgeContent(store, service.vectors)
        for resource in resources:
            self._publish_resource(resource, indexes, selections, proofs, local)
        repo.finish_managed(run_id)

    def _publish_resource(
        self,
        resource: dict[str, Any],
        indexes: dict[str, dict[str, Any]],
        selections: dict[str, dict[str, Any] | None],
        proofs: dict[str, str],
        local: KnowledgeContent,
    ) -> None:
        service, store = self.resources, self.resources.store
        base_id = resource["knowledge_base_id"]
        config, _, _ = service._content_configuration(
            resource, indexes[base_id]["id"], local, selections[resource["id"]], version=4
        )
        revision_id = str(uuid.uuid4())
        store.add(
            "retrieval_revision",
            {
                "id": revision_id,
                "resource_id": resource["id"],
                "revision": store.next_resource_revision(resource["id"]),
                **config,
                "created_by": "knowledge-sync",
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
                    {"config_hash": config["config_hash"], "index_verification": proofs[base_id]}
                ),
                "error_code": None,
                "created_by": "knowledge-sync",
                "created_at": now(),
            },
        )
        store.publish(resource["id"], revision_id, "knowledge-sync")
        service.record(
            "resource.managed_content_activated",
            actor_id="knowledge-sync",
            identifier=resource["id"],
            revision=resource["revision"] + 1,
        )
