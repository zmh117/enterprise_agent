"""显式接续旧发布摘要，不改变 KB、连接、索引、授权或管理员草稿。"""

import uuid

from app.modules.knowledge.application.resource_service import KnowledgeResourceService
from app.modules.knowledge.application.vector_service import VectorService
from app.modules.knowledge.domain.governance import (
    KnowledgeGovernanceError,
    checked_identifier,
    checked_revision,
)
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.domain.storage_connection import stored_config
from app.modules.knowledge.domain.vector_contract import fingerprint, VectorError


class KnowledgeScopeUpgrade:
    def __init__(self, resources: KnowledgeResourceService) -> None:
        self.resources = resources

    def run(
        self, *, actor_id: str, source_id: str, expected_resources: dict[str, int]
    ) -> dict[str, int]:
        service, store = self.resources, self.resources.store
        service.require_admin(actor_id)
        checked_identifier(source_id)
        if not isinstance(expected_resources, dict) or not 1 <= len(expected_resources) <= 100:
            raise KnowledgeGovernanceError("knowledge_input_invalid")
        for resource_id, expected_revision in expected_resources.items():
            checked_identifier(resource_id)
            checked_revision(expected_revision)
        with service._source_mutation_lock(source_id):
            resources = store.published_resources_for_source(source_id)
            if {row["id"] for row in resources} != set(expected_resources):
                raise KnowledgeGovernanceError("knowledge_resource_maintenance_scope_changed")
            prepared = []
            for resource in resources:
                if (
                    resource["status"] != "enabled"
                    or resource["draft_revision_id"] is not None
                    or resource["revision"] != expected_resources[resource["id"]]
                ):
                    raise KnowledgeGovernanceError("knowledge_revision_conflict")
                revision = store.get("retrieval_revision", resource["published_revision_id"])
                selected = stored_config(revision.get("storage_config_json"))
                with service.content(
                    selected, base_id=resource["knowledge_base_id"], revision_id=revision["id"]
                ) as content:
                    config, source, index = service._content_configuration(
                        resource,
                        revision["index_id"],
                        content,
                        selected,
                        version=revision["configuration_version"],
                    )
                    if (
                        source["id"] != source_id
                        or not revision["published_at"]
                        or any(revision[key] != value for key, value in config.items())
                    ):
                        raise KnowledgeGovernanceError("knowledge_resource_unavailable")
                    qdrant = content.qdrant or service.qdrant
                    if qdrant is None or service.embedding is None:
                        raise KnowledgeGovernanceError("knowledge_verification_failed")
                    try:
                        proof = VectorService(content.vectors, service.embedding, qdrant).verify(
                            index
                        )
                    except VectorError:
                        raise KnowledgeGovernanceError("knowledge_verification_failed") from None
                    current, _, _ = service._content_configuration(
                        resource, revision["index_id"], content, selected, version=4
                    )
                    prepared.append((resource, revision, current, proof))
            updated = 0
            with store.unit_of_work():
                service.require_admin(actor_id)
                if {row["id"] for row in store.published_resources_for_source(source_id)} != set(
                    expected_resources
                ):
                    raise KnowledgeGovernanceError("knowledge_resource_maintenance_scope_changed")
                for before, previous, config, proof in prepared:
                    resource = service._write_resource(
                        before["id"], expected_resources[before["id"]]
                    )
                    if resource != before:
                        raise KnowledgeGovernanceError("knowledge_revision_conflict")
                    if previous["configuration_version"] == 4:
                        continue
                    revision_id = str(uuid.uuid4())
                    store.add(
                        "retrieval_revision",
                        {
                            "id": revision_id,
                            "resource_id": before["id"],
                            "revision": store.next_resource_revision(before["id"]),
                            **config,
                            "created_by": actor_id,
                            "created_at": now(),
                        },
                    )
                    store.add(
                        "retrieval_verification",
                        {
                            "id": str(uuid.uuid4()),
                            "resource_id": before["id"],
                            "resource_revision": before["revision"],
                            "revision_id": revision_id,
                            "config_hash": config["config_hash"],
                            "status": "VERIFIED",
                            "evidence_hash": fingerprint(
                                {"config_hash": config["config_hash"], "index_verification": proof}
                            ),
                            "error_code": None,
                            "created_by": actor_id,
                            "created_at": now(),
                        },
                    )
                    store.publish(before["id"], revision_id, actor_id)
                    service.record(
                        "resource.scope_upgraded",
                        actor_id=actor_id,
                        identifier=before["id"],
                        revision=before["revision"] + 1,
                    )
                    updated += 1
            return {"checked": len(prepared), "upgraded": updated}
