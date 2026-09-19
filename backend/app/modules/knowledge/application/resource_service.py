"""知识资源配置、不可变发布和单调用版本固定；不代替用户业务授权。"""

from typing import Any
import uuid

from app.modules.knowledge.application.source_service import (
    KnowledgeAdministration,
    SourceBindingService,
)
from app.modules.knowledge.domain.governance import (
    SourceItem,
    checked_hash,
    KnowledgeGovernanceError,
    checked_identifier,
    checked_revision,
)
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.application.ports import (
    GovernanceRepository,
    VectorRepository,
    EmbeddingPort,
    QdrantPort,
)
from app.modules.knowledge.domain.vector_contract import fingerprint
from app.modules.platform_config.application.validation import assert_no_secret_payload


from app.modules.knowledge.domain.models import PinnedKnowledgeResource


class KnowledgeResourceReader:
    """消费者只读解析器：固定部署来源，不依赖管理权限、JWT 签发器或外部客户端。"""

    def __init__(
        self,
        store: GovernanceRepository,
        vectors: VectorRepository,
        *,
        instance_code: str,
        target_hash: str,
    ) -> None:
        self.store = store
        self.vectors = vectors
        self.instance_code = checked_identifier(instance_code)
        self.target_hash = checked_hash(target_hash)

    def _source_items(self, binding: dict[str, Any]) -> tuple[SourceItem, ...]:
        return self.store.assert_current_source(
            binding, instance_code=self.instance_code, target_hash=self.target_hash
        )

    def _configuration(
        self, resource: dict[str, Any], binding_id: str, index_id: str, *, lock: bool = False
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        binding = self.store.get("source_binding", binding_id, lock=lock)
        source_items = self._source_items(binding)
        base = self.store.get("knowledge_base", resource["knowledge_base_id"])
        raw_index = self.store.get("vector_index", index_id, lock=lock)
        index = self.vectors.get(raw_index["code"])
        if (
            not index
            or index["state"] != "READY"
            or base["state"] != "storage_only"
            or index["knowledge_base_id"] != resource["knowledge_base_id"]
            or index["profile"] != self.vectors.profile
            or index["profile_hash"] != fingerprint(self.vectors.profile)
        ):
            raise KnowledgeGovernanceError("knowledge_index_unavailable")
        members = self.store.members(base["id"])
        source_ids = {item.document_id for item in source_items}
        if len(members) != index["expected_document_count"] or any(
            row["source_id"] != binding["source_id"] or row["id"] not in source_ids
            for row in members
        ):
            raise KnowledgeGovernanceError("knowledge_source_changed")
        values = {
            "binding_id": binding_id,
            "index_id": index_id,
            "profile_hash": index["profile_hash"],
            "corpus_hash": index["corpus_hash"],
        }
        values["config_hash"] = fingerprint(
            {
                "resource_id": resource["id"],
                "knowledge_base_id": base["id"],
                **values,
                "chunk_profile_hash": index["chunk_profile_hash"],
                "collection_name": index["collection_name"],
                "expected_document_count": index["expected_document_count"],
                "expected_chunk_count": index["expected_chunk_count"],
            }
        )
        return values, binding, index

    def resolve(self, knowledge_base_id: str) -> PinnedKnowledgeResource:
        checked_identifier(knowledge_base_id)
        resources = self.store.enabled_resources(knowledge_base_id)
        if len(resources) != 1 or not resources[0]["published_revision_id"]:
            raise KnowledgeGovernanceError("knowledge_resource_unavailable")
        resource = resources[0]
        revision = self.store.get("retrieval_revision", resource["published_revision_id"])
        config, binding, index = self._configuration(
            resource, revision["binding_id"], revision["index_id"]
        )
        if not revision["published_at"] or any(revision[k] != v for k, v in config.items()):
            raise KnowledgeGovernanceError("knowledge_resource_unavailable")
        digest = fingerprint(
            {
                "config": config,
                "binding": binding["verification_hash"],
                "source_confirmation": binding["attestation_hash"],
                "target": binding["target_hash"],
                "source": binding["corpus_hash"],
                "published": revision["id"],
                "state_revision": resource["state_revision"],
                "index_updated_at": str(index["updated_at"]),
            }
        )
        return PinnedKnowledgeResource(
            knowledge_base_id,
            resource["id"],
            revision["id"],
            binding["id"],
            index["id"],
            index["code"],
            digest,
        )

    def recheck(self, pinned: PinnedKnowledgeResource) -> None:
        if self.resolve(pinned.knowledge_base_id) != pinned:
            raise KnowledgeGovernanceError("knowledge_resource_changed")


class KnowledgeResourceService(KnowledgeResourceReader, KnowledgeAdministration):
    def __init__(
        self,
        sources: SourceBindingService,
        vectors: VectorRepository,
        *,
        embedding: EmbeddingPort | None = None,
        qdrant: QdrantPort | None = None,
    ) -> None:
        KnowledgeAdministration.__init__(self, sources.store, sources.permissions, sources.audit)
        self.sources = sources
        self.vectors = vectors
        self.embedding = embedding
        self.qdrant = qdrant

    def _source_items(self, binding: dict[str, Any]) -> tuple[SourceItem, ...]:
        return self.sources.assert_current(binding)

    def create(
        self, *, actor_id: str, knowledge_base_id: str, code: str, name: str
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        checked_identifier(knowledge_base_id)
        checked_identifier(code)
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise KnowledgeGovernanceError("knowledge_input_invalid")
        assert_no_secret_payload({"name": name})
        with self.store.unit_of_work():
            base = self.store.get("knowledge_base", knowledge_base_id, lock=True)
            if base["state"] != "storage_only":
                raise KnowledgeGovernanceError("knowledge_resource_unavailable")
            self._unique_enabled(knowledge_base_id)
            identifier = str(uuid.uuid4())
            self.store.add(
                "retrieval_resource",
                {
                    "id": identifier,
                    "knowledge_base_id": knowledge_base_id,
                    "code": code,
                    "name": name.strip(),
                    "created_by": actor_id,
                    "created_at": now(),
                    "updated_at": now(),
                },
            )
            self.record("resource.created", actor_id=actor_id, identifier=identifier, revision=1)
            return self.view(identifier)

    def _unique_enabled(self, base_id: str, *, excluding: str = "") -> None:
        rows = self.store.enabled_resources(base_id, excluding=excluding)
        if rows:
            raise KnowledgeGovernanceError("knowledge_resource_conflict")

    def _write_resource(self, resource_id: str, expected_revision: int) -> dict[str, Any]:
        checked_revision(expected_revision)
        resource = self.store.get("retrieval_resource", resource_id, lock=True)
        if resource["revision"] != expected_revision:
            raise KnowledgeGovernanceError("knowledge_revision_conflict")
        if resource["status"] == "archived":
            raise KnowledgeGovernanceError("knowledge_resource_unavailable")
        return resource

    def save_draft(
        self,
        *,
        actor_id: str,
        resource_id: str,
        expected_revision: int,
        binding_id: str,
        index_id: str,
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        checked_identifier(binding_id)
        checked_identifier(index_id)
        with self.store.unit_of_work():
            resource = self._write_resource(resource_id, expected_revision)
            config, _, _ = self._configuration(resource, binding_id, index_id, lock=True)
            next_revision = self.store.next_resource_revision(resource_id)
            identifier = str(uuid.uuid4())
            self.store.add(
                "retrieval_revision",
                {
                    "id": identifier,
                    "resource_id": resource_id,
                    "revision": next_revision,
                    **config,
                    "created_by": actor_id,
                    "created_at": now(),
                },
            )
            self.store.save_draft(resource_id, identifier)
            self.record(
                "resource.draft_saved",
                actor_id=actor_id,
                identifier=resource_id,
                revision=expected_revision + 1,
            )
            return self.view(resource_id)

    def _draft(self, resource: dict[str, Any]) -> dict[str, Any]:
        if not resource["draft_revision_id"]:
            raise KnowledgeGovernanceError("knowledge_resource_unavailable")
        return self.store.get("retrieval_revision", resource["draft_revision_id"])

    def verify_draft(
        self, *, actor_id: str, resource_id: str, expected_revision: int
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        with self.store.unit_of_work():
            resource = self._write_resource(resource_id, expected_revision)
            draft = self._draft(resource)
        failure: str | None = None
        try:
            config, binding, index = self._configuration(
                resource, draft["binding_id"], draft["index_id"]
            )
            if (
                any(draft[key] != value for key, value in config.items())
                or self.embedding is None
                or self.qdrant is None
            ):
                raise KnowledgeGovernanceError("knowledge_verification_failed")
            self.vectors.assert_current(index)
            self.embedding.check()
            self.qdrant.check(index)
            count = self.qdrant.count(index)
            if type(count) is not int or count != index["expected_chunk_count"]:
                raise KnowledgeGovernanceError("knowledge_verification_failed")
            evidence = fingerprint(
                {
                    "config_hash": config["config_hash"],
                    "binding": binding["verification_hash"],
                    "points": count,
                }
            )
        except Exception:
            failure = "knowledge_verification_failed"
            evidence = fingerprint({"config_hash": draft["config_hash"], "error_code": failure})
        with self.store.unit_of_work():
            self.require_admin(actor_id)
            current = self._write_resource(resource_id, expected_revision)
            if current != resource:
                raise KnowledgeGovernanceError("knowledge_revision_conflict")
            if not failure:
                config, _, current_index = self._configuration(
                    current, draft["binding_id"], draft["index_id"], lock=True
                )
                if (
                    any(draft[key] != value for key, value in config.items())
                    or current_index != index
                ):
                    raise KnowledgeGovernanceError("knowledge_resource_changed")
                self.vectors.assert_current(current_index)
            self.store.add(
                "retrieval_verification",
                {
                    "id": str(uuid.uuid4()),
                    "resource_id": resource_id,
                    "resource_revision": expected_revision,
                    "revision_id": draft["id"],
                    "config_hash": draft["config_hash"],
                    "status": "FAILED" if failure else "VERIFIED",
                    "evidence_hash": evidence,
                    "error_code": failure,
                    "created_by": actor_id,
                    "created_at": now(),
                },
            )
            self.store.bump_resource_revision(resource_id)
            self.record(
                "resource.verified",
                actor_id=actor_id,
                identifier=resource_id,
                revision=expected_revision + 1,
                error=failure,
            )
        if failure:
            raise KnowledgeGovernanceError(failure)
        return self.view(resource_id)

    def _verification(self, revision_id: str) -> dict[str, Any] | None:
        return self.store.verification(revision_id)

    def publish(self, *, actor_id: str, resource_id: str, expected_revision: int) -> dict[str, Any]:
        self.require_admin(actor_id)
        with self.store.unit_of_work():
            resource = self._write_resource(resource_id, expected_revision)
            draft = self._draft(resource)
            proof = self._verification(draft["id"])
            config, _, index = self._configuration(
                resource, draft["binding_id"], draft["index_id"], lock=True
            )
            if (
                resource["status"] != "enabled"
                or not proof
                or proof["status"] != "VERIFIED"
                or proof["config_hash"] != draft["config_hash"]
                or any(draft[k] != v for k, v in config.items())
            ):
                raise KnowledgeGovernanceError("knowledge_resource_unavailable")
            self.vectors.assert_current(index)
            self.store.publish(resource_id, draft["id"], actor_id)
            self.record(
                "resource.published",
                actor_id=actor_id,
                identifier=resource_id,
                revision=expected_revision + 1,
            )
            return self.view(resource_id)

    def set_status(
        self, *, actor_id: str, resource_id: str, expected_revision: int, status: str
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        if not isinstance(status, str) or status not in {"enabled", "disabled", "archived"}:
            raise KnowledgeGovernanceError("knowledge_input_invalid")
        with self.store.unit_of_work():
            resource = self._write_resource(resource_id, expected_revision)
            if status == "enabled":
                self.store.get("knowledge_base", resource["knowledge_base_id"], lock=True)
                self._unique_enabled(resource["knowledge_base_id"], excluding=resource_id)
            self.store.set_resource_status(resource_id, status)
            self.record(
                "resource." + status,
                actor_id=actor_id,
                identifier=resource_id,
                revision=expected_revision + 1,
            )
            return self.view(resource_id)

    def view(self, resource_id: str) -> dict[str, Any]:
        resource = self.store.get("retrieval_resource", resource_id)
        draft = (
            self.store.get("retrieval_revision", resource["draft_revision_id"])
            if resource["draft_revision_id"]
            else None
        )
        published = (
            self.store.get("retrieval_revision", resource["published_revision_id"])
            if resource["published_revision_id"]
            else None
        )
        return {
            **resource,
            "draft": draft,
            "published": published,
            "verification": self._verification(draft["id"]) if draft else None,
        }

    def list_resources(self) -> dict[str, Any]:
        return {"resources": [self.view(identifier) for identifier in self.store.resource_ids()]}

    def catalog(self) -> dict[str, Any]:
        return self.store.catalog()
