"""Code knowledge management using the existing resource publication lifecycle."""

from pathlib import Path
from typing import Any
import uuid
import os

from app.modules.knowledge.application.resource_service import KnowledgeResourceService
from app.modules.knowledge.domain.code_answers import path_in_scope
from app.modules.knowledge.domain.code_configuration import CODE_CHUNK_PROFILE, code_storage
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.governance import checked_identifier, KnowledgeGovernanceError
from app.modules.knowledge.domain.identity import now, stable_id
from app.modules.knowledge.domain.normalization import canonical_json, digest
from app.modules.knowledge.infrastructure.code_checkout_client import registry
from app.modules.knowledge.infrastructure.code_checkout_store import checkout_scope, json_value
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.infrastructure.storage import insert
from app.modules.platform_config.application.validation import assert_no_secret_payload
from app.shared.io_deadline import io_deadline


class CodeResourceService(KnowledgeResourceService):
    def create_code(
        self, *, actor_id: str, code: str, name: str, storage: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        checked_identifier(code)
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
            raise KnowledgeGovernanceError("knowledge_input_invalid")
        assert_no_secret_payload({"name": name})
        selected = code_storage(storage)
        base_id, resource_id = str(uuid.uuid4()), str(uuid.uuid4())
        with self.store.unit_of_work():
            self.require_admin(actor_id)
            self.store.add(
                "knowledge_base",
                dict(
                    id=base_id,
                    code=code,
                    display_name=name.strip(),
                    description="",
                    state="storage_only",
                    kind="code",
                    created_at=now(),
                ),
            )
            self.store.add(
                "retrieval_resource",
                dict(
                    id=resource_id,
                    knowledge_base_id=base_id,
                    code=code,
                    name=name.strip(),
                    created_by=actor_id,
                    created_at=now(),
                    updated_at=now(),
                ),
            )
            self._new_draft(
                self.store.get("retrieval_resource", resource_id),
                actor_id,
                selected,
                {
                    "source_id": None,
                    "checkout_id": None,
                    "svn_access_ref": None,
                    "allowed_paths_json": [],
                },
                None,
            )
            self.record(
                "code_resource.created", actor_id=actor_id, identifier=resource_id, revision=1
            )
        return self.view(resource_id)

    def _new_draft(
        self,
        resource: dict[str, Any],
        actor: str,
        storage: dict[str, Any],
        source: dict[str, Any],
        index: dict[str, Any] | None,
    ) -> str:
        identifier = str(uuid.uuid4())
        if index:
            from app.modules.knowledge.domain.resource_configuration import configuration_values

            values = configuration_values(
                resource_id=resource["id"],
                base_id=resource["knowledge_base_id"],
                index=index,
                source_id=source["source_id"],
                source_hash="",
                members=[],
                storage=storage,
                version=5,
                code_config=source,
            )
        else:
            values = dict(
                index_id=None,
                profile_hash=digest(self.vectors.profile),
                corpus_hash=digest([]),
                config_hash=digest(["code-draft/v1", resource["id"], source, storage]),
                storage_config_json=canonical_json(storage),
                configuration_version=5,
            )
        self.store.add(
            "retrieval_revision",
            dict(
                id=identifier,
                resource_id=resource["id"],
                revision=self.store.next_resource_revision(resource["id"]),
                **values,
                created_by=actor,
                created_at=now(),
            ),
        )
        self.store.add("code_resource_config", dict(revision_id=identifier, **source))
        self.store.save_draft(resource["id"], identifier)
        return identifier

    def save_code_draft(
        self,
        *,
        actor_id: str,
        resource_id: str,
        expected_revision: int,
        checkout_id: str,
        svn_access_ref: str,
        allowed_paths: list[str],
        storage: dict[str, Any] | None = None,
        index_id: str | None = None,
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        selected = code_storage(storage)
        paths = checkout_scope(allowed_paths)
        entries = registry(
            Path(os.environ.get("CODE_CHECKOUT_REGISTRY_FILE", "/etc/code-svn/checkout.json"))
        )
        entry = entries.get(svn_access_ref)
        if not entry:
            raise CodeKnowledgeError("CODE_REGISTRATION_CHANGED")
        with self.store.unit_of_work():
            self.require_admin(actor_id)
            resource = self._write_resource(resource_id, expected_revision)
            self._code_base(resource)
            self.store.assert_code_idle(resource["knowledge_base_id"])
            checkout = self.store.get("code_checkout", checkout_id, lock=True)
            source = self.store.get("source", checkout["source_id"])
            metadata = json_value(source["identity_metadata"])
            if (
                checkout["state"] != "ready"
                or checkout["writer_operation_id"] is not None
                or checkout["physical_key"] is None
                or source["source_system"] != "svn"
                or source["origin_state"] != "verified"
                or metadata["repository_uuid"] != entry["repository_uuid"]
                or metadata["branch_path"] != entry["branch_path"].strip("/")
                or any(
                    not path_in_scope(path, json_value(checkout["selected_paths_json"]))
                    for path in paths
                )
            ):
                raise CodeKnowledgeError("CODE_CHECKOUT_BINDING_INVALID")
            index = None
            if index_id:
                raw = self.store.get("vector_index", index_id)
                index = self.vectors.get(raw["code"])
                if (
                    not index
                    or index["knowledge_base_id"] != resource["knowledge_base_id"]
                    or index.get("source_id") != source["id"]
                    or index.get("incremental") != 1
                    or index["state"] != "READY"
                    or index["chunk_profile_hash"] != CODE_CHUNK_PROFILE.fingerprint
                    or index["profile_hash"] != digest(self.vectors.profile)
                ):
                    raise CodeKnowledgeError("CODE_INDEX_CONFIGURATION_INVALID")
            self._new_draft(
                resource,
                actor_id,
                selected,
                dict(
                    source_id=source["id"],
                    checkout_id=checkout_id,
                    svn_access_ref=svn_access_ref,
                    allowed_paths_json=paths,
                ),
                index,
            )
            self.record(
                "code_resource.draft_saved",
                actor_id=actor_id,
                identifier=resource_id,
                revision=expected_revision + 1,
            )
        return self.view(resource_id)

    def _code_base(self, resource: dict[str, Any]) -> None:
        if self.store.get("knowledge_base", resource["knowledge_base_id"]).get("kind") != "code":
            raise CodeKnowledgeError("CODE_KNOWLEDGE_BASE_REQUIRED")

    def initialize_index(
        self, *, actor_id: str, resource_id: str, expected_revision: int
    ) -> dict[str, Any]:
        # Fixed managed target only. No administrator-provided collection name to collide with ONES.
        self.require_admin(actor_id)
        if (
            self.qdrant is None
            or self.embedding is None
            or not isinstance(self.store, GovernanceStore)
        ):
            raise CodeKnowledgeError("CODE_INDEX_INITIALIZATION_UNAVAILABLE")
        with io_deadline(30), self.store.source_lock("code-index-initialize:" + resource_id):
            with self.store.unit_of_work():
                resource = self._write_resource(resource_id, expected_revision)
                self._code_base(resource)
                self.store.assert_code_idle(resource["knowledge_base_id"])
                draft = self._draft(resource)
                source = self.store.code_configuration(draft["id"])
                from app.modules.knowledge.domain.code_configuration import source_configuration

                source = source_configuration(source)
                checkout = self.store.get("code_checkout", source["checkout_id"], lock=True)
                if (
                    checkout["state"] != "ready"
                    or checkout["writer_operation_id"]
                    or checkout["source_id"] != source["source_id"]
                ):
                    raise CodeKnowledgeError("CODE_CHECKOUT_BINDING_INVALID")
                identifier = stable_id(
                    "code-index",
                    resource["knowledge_base_id"],
                    source["source_id"],
                    CODE_CHUNK_PROFILE.fingerprint,
                    digest(self.vectors.profile),
                )
                code = "code-" + identifier
                index = self.vectors.get(code)
                if not index:
                    insert(
                        self.store.database,
                        "vector_index",
                        dict(
                            id=identifier,
                            code=code,
                            knowledge_base_id=resource["knowledge_base_id"],
                            source_id=source["source_id"],
                            incremental=1,
                            profile=self.vectors.profile,
                            profile_hash=digest(self.vectors.profile),
                            chunk_profile_hash=CODE_CHUNK_PROFILE.fingerprint,
                            corpus_hash=digest(["code-answer-incremental/v1", identifier]),
                            collection_name="code_answers_" + uuid.UUID(identifier).hex,
                            expected_document_count=0,
                            expected_chunk_count=0,
                            state="BUILDING",
                            created_at=now(),
                            updated_at=now(),
                        ),
                    )
                    index = self.vectors.get(code)
                assert index is not None
                expected = {
                    "id": identifier,
                    "knowledge_base_id": resource["knowledge_base_id"],
                    "source_id": source["source_id"],
                    "incremental": 1,
                    "profile": self.vectors.profile,
                    "profile_hash": digest(self.vectors.profile),
                    "chunk_profile_hash": CODE_CHUNK_PROFILE.fingerprint,
                    "collection_name": "code_answers_" + uuid.UUID(identifier).hex,
                }
                if index["state"] not in {"BUILDING", "READY"} or any(
                    index.get(key) != value for key, value in expected.items()
                ):
                    raise CodeKnowledgeError("CODE_INDEX_CONFIGURATION_INVALID")
            self.embedding.check()
            self.qdrant.ensure(index)
            self.qdrant.check(index)
            with self.store.unit_of_work():
                self.require_admin(actor_id)
                current = self._write_resource(resource_id, expected_revision)
                if current != resource:
                    raise CodeKnowledgeError("CODE_CONFIGURATION_CHANGED")
                self.store.assert_code_idle(resource["knowledge_base_id"])
                self.store.database.execute(
                    f"UPDATE {self.store.t('vector_index')} SET state='READY',updated_at=? WHERE id=?",
                    (now(), identifier),
                )
                index = self.vectors.get(code)
                self._new_draft(resource, actor_id, code_storage(), source, index)
        return self.view(resource_id)

    def view(self, resource_id: str) -> dict[str, Any]:
        result = super().view(resource_id)
        for key in ("draft", "published"):
            if result[key] and result[key]["configuration_version"] == 5:
                result[key]["code_configuration"] = self.store.code_configuration(result[key]["id"])
        result["chunk_profile"] = {
            "version": CODE_CHUNK_PROFILE.version,
            "hash": CODE_CHUNK_PROFILE.fingerprint,
        }
        result["embedding_profile_hash"] = digest(self.vectors.profile)
        return result

    def indexing_status(self, *, actor_id: str, resource_id: str) -> dict[str, Any]:
        self.require_admin(actor_id)
        resource = self.store.get("retrieval_resource", resource_id)
        self._code_base(resource)
        assert isinstance(self.store, GovernanceStore)
        base = self.store.get("knowledge_base", resource["knowledge_base_id"])
        indexes = self.store.database.execute(
            f"SELECT id,code,state,collection_name,profile_hash,chunk_profile_hash FROM {self.store.t('vector_index')} WHERE knowledge_base_id=? ORDER BY created_at,id",
            (base["id"],),
        )
        for index in indexes:
            index["counts"] = {
                row["state"]: row["n"]
                for row in self.store.database.execute(
                    f"SELECT state,count(*) AS n FROM {self.store.t('code_index_task')} WHERE index_id=? GROUP BY state",
                    (index["id"],),
                )
            }
            index["tasks"] = self.store.database.execute(
                f"SELECT id,action,state,step,expected_chunks,completed_chunks,error_code,attempt_count,updated_at "
                f"FROM {self.store.t('code_index_task')} WHERE index_id=? AND state<>'succeeded' ORDER BY updated_at DESC,id LIMIT 20",
                (index["id"],),
            )
        return {"paused": bool(base["code_indexing_paused"]), "indexes": indexes}

    def set_indexing(self, *, actor_id: str, resource_id: str, paused: bool) -> dict[str, Any]:
        if type(paused) is not bool:
            raise CodeKnowledgeError("CODE_INDEX_CONFIGURATION_INVALID")
        self.require_admin(actor_id)
        assert isinstance(self.store, GovernanceStore)
        with self.store.unit_of_work():
            resource = self.store.get("retrieval_resource", resource_id, lock=True)
            self._code_base(resource)
            self.store.database.execute(
                f"UPDATE {self.store.t('knowledge_base')} SET code_indexing_paused=? WHERE id=?",
                (int(paused), resource["knowledge_base_id"]),
            )
            self.record(
                "code_resource.indexing_paused" if paused else "code_resource.indexing_resumed",
                actor_id=actor_id,
                identifier=resource_id,
                revision=resource["revision"],
            )
        return self.indexing_status(actor_id=actor_id, resource_id=resource_id)

    def retry_indexing(self, *, actor_id: str, resource_id: str, task_id: str) -> dict[str, Any]:
        self.require_admin(actor_id)
        assert isinstance(self.store, GovernanceStore)
        from app.modules.knowledge.infrastructure.code_index_store import CodeIndexStore

        tasks = CodeIndexStore(self.store.database)
        with self.store.unit_of_work():
            resource = self.store.get("retrieval_resource", resource_id, lock=True)
            self._code_base(resource)
            task = tasks.row("code_index_task", task_id)
            tasks._document_lock(task["document_id"])
            task = tasks.row("code_index_task", task_id, lock=True)
            index, wanted, _ = tasks._current(task)
            if index["knowledge_base_id"] != resource["knowledge_base_id"] or not wanted:
                raise CodeKnowledgeError("CODE_INDEX_INTENT_CHANGED")
            if self.store.database.execute_one(
                f"SELECT id FROM {tasks.t('code_index_task')} WHERE index_id=? AND document_id=? AND state='running'",
                (index["id"], task["document_id"]),
            ):
                raise CodeKnowledgeError("CODE_INDEX_BUSY")
            tasks.enqueue(
                index, task["document_id"], task["revision_id"], task["action"], restart=True
            )
            self.record(
                "code_resource.index_retry",
                actor_id=actor_id,
                identifier=task_id,
                revision=task["claim_version"],
            )
        return self.indexing_status(actor_id=actor_id, resource_id=resource_id)
