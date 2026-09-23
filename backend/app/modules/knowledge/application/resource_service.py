"""知识资源配置、不可变发布和单调用版本固定；不代替用户业务授权。"""

from typing import Any
from collections.abc import Iterator
from contextlib import AbstractContextManager, nullcontext, contextmanager
import uuid

from app.modules.knowledge.application.content_access import ContentAccess, KnowledgeContent
from app.modules.knowledge.domain.storage_connection import storage_config, stored_config

from app.modules.knowledge.application.source_service import (
    KnowledgeAdministration,
)
from app.modules.knowledge.domain.governance import (
    KnowledgeGovernanceError,
    checked_identifier,
    checked_revision,
)
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.application.ports import (
    GovernanceRepository,
    VectorRepository,
    EmbeddingPort,
    QdrantPort,
)
from app.modules.knowledge.domain.vector_contract import fingerprint
from app.modules.platform_config.application.validation import assert_no_secret_payload


from app.modules.knowledge.domain.models import PinnedKnowledgeResource
from app.modules.knowledge.domain.resource_configuration import configuration_values


class KnowledgeResourceReader:
    """只读解析器：平台读取发布状态，通过内容端口读取已绑定的数据与索引。"""

    def __init__(
        self,
        store: GovernanceRepository,
        vectors: VectorRepository,
        *,
        content_access: ContentAccess | None = None,
    ) -> None:
        self.store = store
        self.vectors = vectors
        self.content_access = content_access

    def content(
        self, config: dict[str, Any] | None, *, base_id: str, revision_id: str = ""
    ) -> AbstractContextManager[KnowledgeContent]:
        if self.content_access is not None:
            return self.content_access.open(
                config, knowledge_base_id=base_id, revision_id=revision_id
            )
        if config is not None:
            raise KnowledgeGovernanceError("knowledge_storage_unavailable")
        return nullcontext(KnowledgeContent(self.store, self.vectors))

    def content_for(self, pin: PinnedKnowledgeResource) -> AbstractContextManager[KnowledgeContent]:
        revision = self.store.get("retrieval_revision", pin.revision_id)
        return self.content(
            stored_config(revision.get("storage_config_json")),
            base_id=pin.knowledge_base_id,
            revision_id=pin.revision_id,
        )

    def _configuration(
        self,
        resource: dict[str, Any],
        index_id: str,
        *,
        storage: dict[str, Any] | None = None,
        revision_id: str = "",
        version: int = 4,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        with self.content(
            storage, base_id=resource["knowledge_base_id"], revision_id=revision_id
        ) as content:
            return self._content_configuration(
                resource, index_id, content, storage, version=version
            )

    def _content_configuration(
        self,
        resource: dict[str, Any],
        index_id: str,
        content: KnowledgeContent,
        storage: dict[str, Any] | None,
        *,
        version: int = 4,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        base = content.records.get("knowledge_base", resource["knowledge_base_id"])
        raw_index = content.records.get("vector_index", index_id)
        index = content.vectors.get(raw_index["code"])
        if (
            not index
            or index["state"] != "READY"
            or base["state"] != "storage_only"
            or index["knowledge_base_id"] != resource["knowledge_base_id"]
            or index["profile"] != content.vectors.profile
            or index["profile_hash"] != fingerprint(content.vectors.profile)
        ):
            raise KnowledgeGovernanceError("knowledge_index_unavailable")
        members = content.records.members(base["id"])
        sources = {row["source_id"] for row in members}
        if len(sources) == 1:
            source_id = sources.pop()
        elif not sources and version == 4 and index.get("source_id"):
            source_id = index["source_id"]
        else:
            raise KnowledgeGovernanceError("knowledge_source_unavailable")
        if version == 4 and index.get("source_id") not in {None, source_id}:
            raise KnowledgeGovernanceError("knowledge_source_changed")
        source = content.records.get("source", source_id)
        source_items = (
            content.records.member_source_items(base["id"], source["id"])
            if version == 4
            else content.records.source_items(source["id"])
        )
        source_ids = {item.document_id for item in source_items}
        if len(members) != index["expected_document_count"] or any(
            row["id"] not in source_ids for row in members
        ):
            raise KnowledgeGovernanceError("knowledge_source_changed")
        values = configuration_values(
            resource_id=resource["id"],
            base_id=base["id"],
            index=index,
            source_id=source["id"],
            source_hash=content.records.source_hash(source_items),
            members=members,
            storage=storage,
            version=version,
        )
        return values, source, index

    def resolve(self, knowledge_base_id: str) -> PinnedKnowledgeResource:
        checked_identifier(knowledge_base_id)
        resources = self.store.enabled_resources(knowledge_base_id)
        if len(resources) != 1 or not resources[0]["published_revision_id"]:
            raise KnowledgeGovernanceError("knowledge_resource_unavailable")
        resource = resources[0]
        revision = self.store.get("retrieval_revision", resource["published_revision_id"])
        config, source, index = self._configuration(
            resource,
            revision["index_id"],
            storage=stored_config(revision.get("storage_config_json")),
            revision_id=revision["id"],
            version=revision["configuration_version"],
        )
        if not revision["published_at"] or any(revision[k] != v for k, v in config.items()):
            raise KnowledgeGovernanceError("knowledge_resource_unavailable")
        digest = fingerprint(
            {
                "config": config,
                "published": revision["id"],
                "state_revision": resource["state_revision"],
                "index_updated_at": str(index["updated_at"]),
            }
        )
        return PinnedKnowledgeResource(
            knowledge_base_id,
            resource["id"],
            revision["id"],
            source["id"],
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
        administration: KnowledgeAdministration,
        vectors: VectorRepository,
        *,
        embedding: EmbeddingPort | None = None,
        qdrant: QdrantPort | None = None,
        content_access: ContentAccess | None = None,
    ) -> None:
        KnowledgeAdministration.__init__(
            self, administration.store, administration.permissions, administration.audit
        )
        self.vectors = vectors
        self.embedding = embedding
        self.qdrant = qdrant
        self.content_access = content_access

    def create(
        self,
        *,
        actor_id: str,
        knowledge_base_id: str,
        code: str,
        name: str,
        storage: dict[str, Any] | None = None,
        index_id: str | None = None,
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        checked_identifier(knowledge_base_id)
        checked_identifier(code)
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise KnowledgeGovernanceError("knowledge_input_invalid")
        assert_no_secret_payload({"name": name})
        selected = storage_config(storage)
        if (selected is None) != (index_id is None):
            raise KnowledgeGovernanceError("knowledge_input_invalid")
        initial_config = None
        initial_source = None
        if selected is not None:
            checked_identifier(index_id)
            with self.content(selected, base_id=knowledge_base_id) as content:
                remote_base = content.records.get("knowledge_base", knowledge_base_id)
            if remote_base["state"] != "storage_only":
                raise KnowledgeGovernanceError("knowledge_resource_unavailable")
        identifier = str(uuid.uuid4())
        if index_id is not None:
            initial_config, initial_source, _ = self._configuration(
                {"id": identifier, "knowledge_base_id": knowledge_base_id},
                index_id,
                storage=selected,
            )
        with self._source_mutation_lock(initial_source["id"] if initial_source else None):
            if initial_config is not None:
                assert index_id is not None
                refreshed, _, _ = self._configuration(
                    {"id": identifier, "knowledge_base_id": knowledge_base_id},
                    index_id,
                    storage=selected,
                )
                if refreshed != initial_config:
                    raise KnowledgeGovernanceError("knowledge_source_changed")
            with self.store.unit_of_work():
                self.require_admin(actor_id)
                try:
                    base = self.store.get("knowledge_base", knowledge_base_id, lock=True)
                except KnowledgeGovernanceError as exc:
                    if selected is None or exc.error_code != "knowledge_resource_unavailable":
                        raise
                    base = {
                        "id": knowledge_base_id,
                        "code": remote_base["code"],
                        "display_name": name.strip(),
                        "state": "storage_only",
                        "description": "外部知识内容的平台注册身份",
                        "created_at": now(),
                    }
                    self.store.add("knowledge_base", base)
                if base["state"] != "storage_only":
                    raise KnowledgeGovernanceError("knowledge_resource_unavailable")
                self._unique_enabled(knowledge_base_id)
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
                self.record(
                    "resource.created", actor_id=actor_id, identifier=identifier, revision=1
                )
                if initial_config is not None:
                    revision_id = str(uuid.uuid4())
                    self.store.add(
                        "retrieval_revision",
                        {
                            "id": revision_id,
                            "resource_id": identifier,
                            "revision": 1,
                            **initial_config,
                            "created_by": actor_id,
                            "created_at": now(),
                        },
                    )
                    self.store.save_draft(identifier, revision_id)
                return self.view(identifier)

    @contextmanager
    def _source_mutation_lock(self, source_id: str | None) -> Iterator[None]:
        try:
            with self.store.source_lock(source_id) if source_id is not None else nullcontext():
                yield
        except ExportValidationError as exc:
            if exc.code == "knowledge_source_import_busy":
                raise KnowledgeGovernanceError("knowledge_verification_busy") from None
            raise

    @contextmanager
    def _mutation_scope(
        self,
        resource: dict[str, Any],
        index_id: str,
        *,
        storage: dict[str, Any] | None,
        version: int = 4,
    ) -> Iterator[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
        _, before_source, _ = self._configuration(
            resource, index_id, storage=storage, version=version
        )
        with self._source_mutation_lock(before_source["id"]):
            values = self._configuration(resource, index_id, storage=storage, version=version)
            if values[1]["id"] != before_source["id"]:
                raise KnowledgeGovernanceError("knowledge_source_changed")
            yield values

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
        index_id: str,
        storage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        checked_identifier(index_id)
        selected = storage_config(storage)
        resource = self.store.get("retrieval_resource", resource_id)
        if resource["revision"] != checked_revision(expected_revision):
            raise KnowledgeGovernanceError("knowledge_revision_conflict")
        with self._mutation_scope(resource, index_id, storage=selected) as (config, _, _):
            with self.store.unit_of_work():
                self.require_admin(actor_id)
                resource = self._write_resource(resource_id, expected_revision)
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
            selected = stored_config(draft.get("storage_config_json"))
            config, _, index = self._configuration(
                resource,
                draft["index_id"],
                storage=selected,
                version=draft["configuration_version"],
            )
            if any(draft[key] != value for key, value in config.items()) or self.embedding is None:
                raise KnowledgeGovernanceError("knowledge_verification_failed")
            with self.content(selected, base_id=resource["knowledge_base_id"]) as content:
                qdrant = content.qdrant or self.qdrant
                if qdrant is None:
                    raise KnowledgeGovernanceError("knowledge_verification_failed")
                content.vectors.assert_current(index)
                self.embedding.check()
                qdrant.check(index)
                count = qdrant.count(index)
            if type(count) is not int or count != index["expected_chunk_count"]:
                raise KnowledgeGovernanceError("knowledge_verification_failed")
            evidence = fingerprint(
                {
                    "config_hash": config["config_hash"],
                    "points": count,
                }
            )
        except Exception:
            failure = "knowledge_verification_failed"
            evidence = fingerprint({"config_hash": draft["config_hash"], "error_code": failure})
        if not failure:
            config, _, current_index = self._configuration(
                resource,
                draft["index_id"],
                storage=selected,
                version=draft["configuration_version"],
            )
            if any(draft[k] != v for k, v in config.items()) or current_index != index:
                raise KnowledgeGovernanceError("knowledge_resource_changed")
            with self.content(selected, base_id=resource["knowledge_base_id"]) as content:
                content.vectors.assert_current(current_index)
        with self.store.unit_of_work():
            self.require_admin(actor_id)
            current = self._write_resource(resource_id, expected_revision)
            if current != resource:
                raise KnowledgeGovernanceError("knowledge_revision_conflict")
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
        before = self.store.get("retrieval_resource", resource_id)
        draft = self._draft(before)
        selected = stored_config(draft.get("storage_config_json"))
        with self._mutation_scope(
            before, draft["index_id"], storage=selected, version=draft["configuration_version"]
        ) as (config, _, index):
            with self.content(selected, base_id=before["knowledge_base_id"]) as content:
                content.vectors.assert_current(index)
            with self.store.unit_of_work():
                resource = self._write_resource(resource_id, expected_revision)
                self.require_admin(actor_id)
                if resource != before:
                    raise KnowledgeGovernanceError("knowledge_revision_conflict")
                draft = self._draft(resource)
                proof = self._verification(draft["id"])
                if (
                    resource["status"] != "enabled"
                    or not proof
                    or proof["status"] != "VERIFIED"
                    or proof["config_hash"] != draft["config_hash"]
                    or any(draft[k] != v for k, v in config.items())
                ):
                    raise KnowledgeGovernanceError("knowledge_resource_unavailable")
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
            "draft": {**draft, "storage": stored_config(draft["storage_config_json"])}
            if draft and draft.get("storage_config_json")
            else draft,
            "published": {**published, "storage": stored_config(published["storage_config_json"])}
            if published and published.get("storage_config_json")
            else published,
            "verification": self._verification(draft["id"]) if draft else None,
        }

    def list_resources(self) -> dict[str, Any]:
        return {"resources": [self.view(identifier) for identifier in self.store.resource_ids()]}

    def catalog(self, *, storage: dict[str, Any] | None = None) -> dict[str, Any]:
        with self.content(storage_config(storage), base_id="") as content:
            return content.records.catalog()
