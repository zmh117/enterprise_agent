"""Code knowledge persistence. Callers own current authorization; no DDL or model calls."""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.modules.knowledge.domain.code_contracts import (
    CONTRACT_VERSION,
    SOURCE_REF,
    VERSION_SELECTOR,
    CodeKnowledgeError,
    validate,
)
from app.modules.knowledge.domain.identity import now, stable_id
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.storage import insert, source_lock, table
from app.shared.database import Database


def decoded(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def knowledge_id(source_id: str, business_key: str) -> str:
    return stable_id("document", source_id, "code_business", business_key)


def search_text(record: dict[str, Any]) -> str:
    """Deterministic search projection; structured record remains the authority."""
    return "\n".join(
        [
            record["title"],
            record["summary"],
            "角色：" + record["role"],
            *[
                fact["description"]
                for name in ("check_order", "effects", "outcomes", "configuration")
                for fact in record[name]
            ],
            "成功边界：" + record["success_boundary"]["description"],
        ]
    )


class CodeRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def _table(self, name: str) -> str:
        return table(self.database, name)

    def binding(self, source_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            f"select * from {self._table('code_binding')} where source_id=?", (source_id,)
        )
        if not row:
            raise CodeKnowledgeError("code_source_unavailable")
        return row

    def register(self, *, code: str, base_code: str, config: dict[str, Any]) -> dict[str, str]:
        """Deployment controller only; registration never publishes or grants access."""
        source_id = stable_id("code_source", code)
        base_id = stable_id("code_base", base_code)
        with source_lock(self.database, source_id), self.database.unit_of_work():
            existing = self.database.execute_one(
                f"select * from {self._table('code_binding')} where source_id=?", (source_id,)
            )
            if existing:
                if (
                    existing["config_hash"] != digest(config)
                    or existing["knowledge_base_id"] != base_id
                ):
                    raise CodeKnowledgeError("code_source_configuration_conflict")
                return {"source_id": source_id, "knowledge_base_id": base_id}
            insert(
                self.database,
                "source",
                dict(
                    id=source_id,
                    code=code,
                    display_name=code,
                    source_system="code",
                    origin_state="offline_unverified",
                    identity_metadata={},
                    created_at=now(),
                ),
            )
            insert(
                self.database,
                "knowledge_base",
                dict(
                    id=base_id,
                    code=base_code,
                    display_name=base_code,
                    description="版本化业务代码知识；来源与权限须独立发布",
                    state="storage_only",
                    created_at=now(),
                ),
            )
            insert(
                self.database,
                "code_binding",
                dict(
                    source_id=source_id,
                    knowledge_base_id=base_id,
                    config_revision=1,
                    config_hash=digest(config),
                    config_json=config,
                    created_at=now(),
                    updated_at=now(),
                ),
            )
        return {"source_id": source_id, "knowledge_base_id": base_id}

    def freeze_source(
        self, source_id: str, source_ref: dict[str, Any], manifest: dict[str, Any]
    ) -> str:
        with source_lock(self.database, source_id), self.database.unit_of_work():
            return self._freeze_source(source_id, source_ref, manifest)

    def _freeze_source(
        self, source_id: str, source_ref: dict[str, Any], manifest: dict[str, Any]
    ) -> str:
        validate(source_ref, SOURCE_REF)
        if source_ref["manifest_hash"] != digest(manifest):
            raise CodeKnowledgeError("code_manifest_digest_mismatch")
        binding = self.binding(source_id)
        identifier = stable_id(
            "code_source_snapshot", source_id, binding["config_hash"], digest(source_ref)
        )
        previous = self.database.execute(
            f"select id,source_ref,retired_at from {self._table('code_source_snapshot')} "
            "where source_id=? and config_hash=? and manifest_hash=? order by created_at desc,id limit 101",
            (source_id, binding["config_hash"], source_ref["manifest_hash"]),
        )
        if len(previous) > 100:
            raise CodeKnowledgeError("code_source_import_history_limit")
        matches = [row for row in previous if decoded(row["source_ref"]) == source_ref]
        for row in matches:
            if row["retired_at"] is None:
                return str(row["id"])
        if matches:
            identifier = str(uuid.uuid4())
        insert(
            self.database,
            "code_source_snapshot",
            dict(
                id=identifier,
                source_id=source_id,
                config_hash=binding["config_hash"],
                source_kind=source_ref["kind"],
                svn_revision=source_ref.get("revision"),
                source_ref=source_ref,
                manifest_hash=digest(manifest),
                manifest_json=manifest,
                created_at=now(),
            ),
            conflict="on conflict(id) do nothing",
        )
        return identifier

    def new_build(
        self,
        source_id: str,
        source_snapshot_id: str,
        *,
        purpose: str,
        configuration: dict[str, Any],
    ) -> dict[str, str]:
        if purpose not in {"baseline", "daily", "history", "release"}:
            raise CodeKnowledgeError("code_build_purpose_invalid")
        with source_lock(self.database, source_id), self.database.unit_of_work():
            binding = self.binding(source_id)
            source = self.database.execute_one(
                f"select * from {self._table('code_source_snapshot')} where id=? and source_id=?",
                (source_snapshot_id, source_id),
            )
            if not source or source["config_hash"] != binding["config_hash"]:
                raise CodeKnowledgeError("code_source_configuration_changed")
            if source["retired_at"] is not None:
                raise CodeKnowledgeError("code_source_retired")
            snapshot_id = stable_id(
                "code_snapshot", source_id, source_snapshot_id, digest(configuration)
            )
            key = digest([source_snapshot_id, configuration, purpose])
            build_id = stable_id("code_build", key)
            existing_build = self.database.execute_one(
                f"select id from {self._table('code_build')} where id=?", (build_id,)
            )
            if existing_build:
                return {"build_id": build_id, "snapshot_id": snapshot_id}
            pending = self.database.execute_one(
                f"select count(*) as n from {self._table('code_build')} where source_id=? "
                "and stage in ('QUEUED','SOURCE_READY','EXTRACTING','VALIDATING','INDEXING')",
                (source_id,),
            )
            if pending and pending["n"] >= 20:
                raise CodeKnowledgeError("code_build_queue_full")
            existing_snapshot = self.database.execute_one(
                f"select state from {self._table('code_snapshot')} where id=?", (snapshot_id,)
            )
            if existing_snapshot and existing_snapshot["state"] != "READY":
                other = self.database.execute_one(
                    f"select id from {self._table('code_build')} where snapshot_id=? and id<>? limit 1",
                    (snapshot_id, build_id),
                )
                if other:
                    raise CodeKnowledgeError("code_snapshot_build_pending")
            insert(
                self.database,
                "code_snapshot",
                dict(
                    id=snapshot_id,
                    source_id=source_id,
                    knowledge_base_id=binding["knowledge_base_id"],
                    source_snapshot_id=source_snapshot_id,
                    processing_hash=digest(configuration),
                    state="CANDIDATE",
                    index_manifest={},
                    validation_json={},
                    created_at=now(),
                ),
                conflict="on conflict(id) do nothing",
            )
            insert(
                self.database,
                "code_build",
                dict(
                    id=build_id,
                    source_id=source_id,
                    source_snapshot_id=source_snapshot_id,
                    snapshot_id=snapshot_id,
                    parent_snapshot_id=binding["active_snapshot_id"],
                    config_hash=binding["config_hash"],
                    configuration_json=configuration,
                    purpose=purpose,
                    stage="READY"
                    if existing_snapshot and existing_snapshot["state"] == "READY"
                    else "QUEUED",
                    dedupe_key=key,
                    created_at=now(),
                    updated_at=now(),
                ),
                conflict="on conflict(id) do nothing",
            )
        return {"build_id": build_id, "snapshot_id": snapshot_id}

    def snapshot(self, base_id: str, snapshot_id: str, *, ready: bool = True) -> dict[str, Any]:
        row = self.database.execute_one(
            f"select s.*,r.source_ref,r.svn_revision,r.config_hash,r.retired_at from {self._table('code_snapshot')} s "
            f"join {self._table('code_source_snapshot')} r on r.id=s.source_snapshot_id "
            "where s.id=? and s.knowledge_base_id=?",
            (snapshot_id, base_id),
        )
        if not row or (ready and row["state"] != "READY"):
            raise CodeKnowledgeError("code_snapshot_unavailable")
        return row

    def store_candidate(self, snapshot_id: str, package: dict[str, Any]) -> None:
        """Internal validated importer; never mutate a ready snapshot or current_revision_id."""
        row = self.database.execute_one(
            f"select * from {self._table('code_snapshot')} where id=?", (snapshot_id,)
        )
        if not row:
            raise CodeKnowledgeError("code_snapshot_unavailable")
        with source_lock(self.database, row["source_id"]), self.database.unit_of_work():
            snapshot = self.snapshot(row["knowledge_base_id"], snapshot_id, ready=False)
            if snapshot["state"] != "CANDIDATE":
                raise CodeKnowledgeError("code_snapshot_immutable")
            if package["manifest.json"]["source_snapshot_id"] != snapshot["source_snapshot_id"]:
                raise CodeKnowledgeError("code_candidate_binding_mismatch")
            run_id = self._import_run(snapshot, package)
            for record in package["knowledge.jsonl"]:
                self._store_record(snapshot, run_id, record, package["evidence.jsonl"])
            for relation in package["relations.jsonl"]:
                self._store_relation(snapshot, relation)

    def _import_run(self, snapshot: dict[str, Any], package: dict[str, Any]) -> str:
        package_hash = digest(package)
        run_id = stable_id("code_import", snapshot["id"], package_hash)
        count = len(package["knowledge.jsonl"])
        insert(
            self.database,
            "import_run",
            dict(
                id=run_id,
                source_id=snapshot["source_id"],
                knowledge_base_id=snapshot["knowledge_base_id"],
                input_hash=package_hash,
                input_manifest=package["manifest.json"],
                state="completed",
                total_count=count,
                processed_count=count,
                created_count=count,
                started_at=now(),
                updated_at=now(),
                completed_at=now(),
            ),
            conflict="on conflict(id) do nothing",
        )
        return run_id

    def _store_record(
        self,
        snapshot: dict[str, Any],
        run_id: str,
        record: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> None:
        source_id, base_id = snapshot["source_id"], snapshot["knowledge_base_id"]
        document_id = knowledge_id(source_id, record["business_key"])
        from app.modules.knowledge.domain.code_package import _evidence_references

        used = _evidence_references(record)
        attributes = {
            "contract_version": CONTRACT_VERSION,
            "knowledge": record,
            "evidence": [item for item in evidence if item["id"] in used],
        }
        revision_id = stable_id("code_revision", document_id, digest(attributes))
        insert(
            self.database,
            "document",
            dict(
                id=document_id,
                source_id=source_id,
                source_object_type="code_business",
                external_id=record["business_key"],
                external_number=record["business_key"],
                document_kind=record["kind"],
                lifecycle_state="active",
                created_at=now(),
                last_seen_at=now(),
            ),
            conflict="on conflict(id) do nothing",
        )
        existing = self.database.execute_one(
            f"select id from {self._table('document_revision')} where id=?", (revision_id,)
        )
        if not existing:
            self._insert_revision(snapshot, run_id, record, attributes, document_id, revision_id)
        member = self.database.execute_one(
            f"select revision_id from {self._table('code_member')} where snapshot_id=? and document_id=?",
            (snapshot["id"], document_id),
        )
        if member and member["revision_id"] != revision_id:
            raise CodeKnowledgeError("code_candidate_member_conflict")
        insert(
            self.database,
            "code_member",
            dict(snapshot_id=snapshot["id"], document_id=document_id, revision_id=revision_id),
            conflict="on conflict(snapshot_id,document_id) do nothing",
        )
        insert(
            self.database,
            "knowledge_base_document",
            dict(
                knowledge_base_id=base_id,
                document_id=document_id,
                state="included",
                created_at=now(),
            ),
            conflict="on conflict(knowledge_base_id,document_id) do nothing",
        )

    def _insert_revision(
        self,
        snapshot: dict[str, Any],
        run_id: str,
        record: dict[str, Any],
        attributes: dict[str, Any],
        document_id: str,
        revision_id: str,
    ) -> None:
        count = self.database.execute_one(
            f"select coalesce(max(revision_no),0)+1 as n from {self._table('document_revision')} where document_id=?",
            (document_id,),
        )
        assert count is not None
        insert(
            self.database,
            "document_revision",
            dict(
                id=revision_id,
                document_id=document_id,
                revision_no=count["n"],
                import_run_id=run_id,
                title=record["title"],
                body_text=search_text(record),
                source_project_id=snapshot["source_id"],
                source_project_name="MES code",
                source_snapshot=decoded(snapshot["source_ref"]),
                attributes=attributes,
                completeness={"coverage": record["coverage"], "unknowns": record["unknowns"]},
                normalizer_version=CONTRACT_VERSION,
                content_hash=digest(attributes),
                ingested_at=now(),
            ),
        )
        for evidence in attributes["evidence"]:
            insert(
                self.database,
                "code_dependency",
                dict(
                    revision_id=revision_id,
                    relative_path=evidence["path"],
                    symbol=evidence["symbol"],
                    dependency_kind="source",
                ),
                conflict="on conflict(revision_id,relative_path,symbol,dependency_kind) do nothing",
            )

    def _store_relation(self, snapshot: dict[str, Any], relation: dict[str, Any]) -> None:
        existing = self.database.execute_one(
            f"select relation_json from {self._table('code_relation')} where snapshot_id=? and relation_id=?",
            (snapshot["id"], relation["id"]),
        )
        if existing and decoded(existing["relation_json"]) != relation:
            raise CodeKnowledgeError("code_candidate_relation_conflict")
        insert(
            self.database,
            "code_relation",
            dict(
                snapshot_id=snapshot["id"],
                relation_id=relation["id"],
                from_document_id=knowledge_id(snapshot["source_id"], relation["from_key"]),
                to_document_id=knowledge_id(snapshot["source_id"], relation["to_key"]),
                kind=relation["kind"],
                relation_json=relation,
            ),
            conflict="on conflict(snapshot_id,relation_id) do nothing",
        )

    def read_member(self, base_id: str, snapshot_id: str, document_id: str) -> dict[str, Any]:
        snapshot = self.snapshot(base_id, snapshot_id)
        row = self.database.execute_one(
            f"select r.id,r.attributes from {self._table('code_member')} m "
            f"join {self._table('document_revision')} r on r.id=m.revision_id and r.document_id=m.document_id "
            f"join {self._table('knowledge_base_document')} b on b.document_id=m.document_id "
            "where m.snapshot_id=? and m.document_id=? and b.knowledge_base_id=? and b.state='included'",
            (snapshot_id, document_id, base_id),
        )
        if not row:
            raise CodeKnowledgeError("code_knowledge_unavailable")
        return {
            "knowledge_id": document_id,
            "revision_id": row["id"],
            "snapshot_id": snapshot_id,
            "source_evidence_status": "retired"
            if snapshot["retired_at"] is not None
            else "retained",
            **decoded(row["attributes"]),
        }

    def resolve(self, base_id: str, selector: dict[str, Any] | None) -> dict[str, Any]:
        if selector is not None:
            validate(selector, VERSION_SELECTOR)
        binding = self.database.execute_one(
            f"select source_id,config_hash,active_snapshot_id from {self._table('code_binding')} where knowledge_base_id=?",
            (base_id,),
        )
        if not binding:
            raise CodeKnowledgeError("code_source_unavailable")
        if selector is None:
            rows = self.database.execute(
                f"select s.id from {self._table('code_snapshot')} s join {self._table('code_source_snapshot')} r on r.id=s.source_snapshot_id "
                "where s.knowledge_base_id=? and r.svn_revision is null and r.config_hash=? and s.state='READY' order by s.id limit 21",
                (base_id, binding["config_hash"]),
            )
            return {
                "status": "VERSION_REQUIRED",
                "available_local_baselines": [row["id"] for row in rows[:20]],
                "more_local_baselines": len(rows) > 20,
            }
        if selector["kind"] == "svn":
            rows = self.database.execute(
                f"select s.id from {self._table('code_snapshot')} s join {self._table('code_source_snapshot')} r on r.id=s.source_snapshot_id "
                "where s.knowledge_base_id=? and r.svn_revision=? and r.config_hash=? and s.state='READY' order by s.id limit 2",
                (base_id, selector["revision"], binding["config_hash"]),
            )
            if not rows:
                return {"status": "BUILD_REQUIRED", "requested_revision": selector["revision"]}
            if len(rows) > 1:
                return {"status": "VERSION_UNAVAILABLE", "reason": "processing_version_ambiguous"}
            snapshot_id = rows[0]["id"]
        else:
            snapshot_id = (
                selector.get("snapshot_id")
                if selector["kind"] == "local_baseline"
                else binding["active_snapshot_id"]
            )
        if not snapshot_id:
            return {"status": "VERSION_UNAVAILABLE"}
        snapshot = self.snapshot(base_id, snapshot_id)
        source_ref = decoded(snapshot["source_ref"])
        if selector["kind"] == "local_baseline" and source_ref["kind"] != "local_bundle":
            raise CodeKnowledgeError("code_version_selector_mismatch")
        return {"status": "READY", "snapshot_id": snapshot_id, "source_ref": source_ref}

    def history_facts(self, base_id: str, lower: int, upper: int) -> dict[str, Any]:
        if (
            type(lower) is not int
            or type(upper) is not int
            or not 0 <= lower <= upper
            or upper - lower > 10000
        ):
            raise CodeKnowledgeError("code_history_range_invalid")
        binding = self.database.execute_one(
            f"select source_id,config_hash,collected_from_revision,collected_revision from {self._table('code_binding')} where knowledge_base_id=?",
            (base_id,),
        )
        if not binding:
            raise CodeKnowledgeError("code_source_unavailable")
        rows = self.database.execute(
            f"select revision,complete from {self._table('code_commit')} where source_id=? and config_hash=? and revision>? and revision<=? order by revision limit 51",
            (binding["source_id"], binding["config_hash"], lower, upper),
        )
        historical = self.database.execute_one(
            f"select from_revision from {self._table('code_history_check')} where source_id=? and config_hash=? and from_revision<=? and to_revision>=? and ledger_complete=1 limit 1",
            (binding["source_id"], binding["config_hash"], lower, upper),
        )
        complete = (
            bool(historical)
            or (
                binding["collected_from_revision"] is not None
                and binding["collected_from_revision"] <= lower
                and binding["collected_revision"] is not None
                and binding["collected_revision"] >= upper
            )
        ) and (len(rows) <= 50 and all(row["complete"] for row in rows))
        return {"revisions": [row["revision"] for row in rows[:50]], "ledger_complete": complete}

    def relation_page(
        self, base_id: str, snapshot_id: str, document_id: str, *, after: str = "", limit: int = 51
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 101:
            raise CodeKnowledgeError("code_relation_limit_invalid")
        self.read_member(base_id, snapshot_id, document_id)
        rows = self.database.execute(
            f"select relation_id,to_document_id,relation_json from {self._table('code_relation')} "
            "where snapshot_id=? and from_document_id=? and relation_id>? order by relation_id limit ?",
            (snapshot_id, document_id, after, limit),
        )
        return [
            {
                "relation_id": row["relation_id"],
                "target_id": row["to_document_id"],
                "relation": decoded(row["relation_json"]),
            }
            for row in rows
        ]
