"""受管文档增量事实；只检查本轮观察和当前处理文档。"""

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.knowledge.domain.chunking import ChunkProfile, prepare_chunks
from app.modules.knowledge.domain.collection_content import content_hash, record_hash
from app.modules.knowledge.domain.identity import now, stable_id
from app.modules.knowledge.domain.normalization import (
    ExportValidationError,
    PreparedExport,
    PreparedRecord,
    canonical_json,
)
from app.modules.knowledge.domain.vector_contract import VectorError, fingerprint
from app.modules.knowledge.domain.work_items import compare_version
from app.modules.knowledge.domain.storage_connection import DEFAULT_QDRANT, stored_config
from app.modules.knowledge.infrastructure.chunk_repository import ChunkRepository
from app.modules.knowledge.infrastructure.storage import insert
from app.modules.knowledge.infrastructure.sync_repository import SyncRepository
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository


class IncrementalSyncRepository(SyncRepository):
    def cancel_disabled_collection(self, run_id: str) -> None:
        # 停用仅暂停；保留已采集页面和已完成文档，重新启用后续跑。
        return None

    def assert_configuration(self, run: dict[str, Any], *, lock: bool = False) -> dict[str, Any]:
        if run.get("incremental") != 1:
            raise ExportValidationError("knowledge_sync_migration_required")
        return super().assert_configuration(run, lock=lock)

    def current_resource_pins(
        self, binding: dict[str, Any], *, lock: bool = False
    ) -> dict[str, Any]:
        # 发布/草稿/停用不控制采集；历史 pins 只为首次迁移保留分块配置。
        return dict(binding["resource_pins_json"])

    def begin(self, binding_id: str, exports: tuple[PreparedExport, ...]) -> dict[str, Any]:
        existing = self.active_collection(binding_id)
        if existing and not existing["incremental"]:
            raise ExportValidationError("knowledge_sync_migration_required")
        with self.database.unit_of_work():
            run = self._begin(binding_id, exports)
            checkpoint = {**run["checkpoint_json"], "baseline_complete": True}
            self.database.execute(
                f"update {self.t('sync_run')} set incremental=1,checkpoint_json=? where id=?",
                (canonical_json(checkpoint), run["id"]),
            )
        return self.run(run["id"])

    def stage(self, run_id: str, record: PreparedRecord) -> str:
        with self.database.unit_of_work():
            run = self.run(run_id, lock=True)
            if run["incremental"] != 1:
                raise ExportValidationError("knowledge_sync_migration_required")
            document_id = stable_id(
                "document", run["source_id"], "ones_work_item", record.external_id
            )
            if self.candidate(run_id, document_id) is None:
                old = self.database.execute_one(
                    f"select d.*,r.source_update_stamp_raw from {self.t('document')} d "
                    f"left join {self.t('document_revision')} r on r.id=d.current_revision_id where d.id=?",
                    (document_id,),
                )
                if old and old["current_revision_id"]:
                    if old["lifecycle_state"] != "active":
                        raise ExportValidationError("knowledge_sync_baseline_changed")
                    members = self._members(document_id)
                    bases = {
                        stable_id("base", code)
                        for code in self.binding(run["binding_id"])["configuration_json"][
                            "base_codes"
                        ].values()
                    }
                    if any(
                        base not in bases and state == "included" for base, state in members.items()
                    ):
                        raise ExportValidationError("knowledge_sync_resource_scope_changed")
                    stamp = old["source_observed_stamp_raw"] or old["source_update_stamp_raw"]
                    insert(
                        self.database,
                        "sync_candidate",
                        {
                            "run_id": run_id,
                            "source_id": run["source_id"],
                            "external_id": record.external_id,
                            "document_id": document_id,
                            "baseline_revision_id": old["current_revision_id"],
                            "baseline_kind": old["document_kind"],
                            "baseline_members_json": members,
                            "baseline_stamp": stamp,
                            "candidate_revision_id": old["current_revision_id"],
                            "candidate_kind": old["document_kind"],
                            "candidate_members_json": members,
                            "observed_stamp": stamp,
                            "record_hash": None,
                            "outcome": "baseline",
                        },
                    )
            return super().stage(run_id, record)

    def _revision_content_hash(self, revision_id: str, values: dict[str, Any]) -> str:
        relations = self.database.execute(
            f"select to_external_id as target_external_id,source_relation_type,source_direction "
            f"from {self.t('document_relation')} where evidence_revision_id=?",
            (revision_id,),
        )
        return content_hash(values, tuple(relations))

    def _compare_candidate(
        self,
        run: dict[str, Any],
        candidate: dict[str, Any],
        record: PreparedRecord,
        old: dict[str, Any],
    ) -> str:
        if not all(
            m.get("export_format") == "ones-online-full/v1" for m in run["manifest_json"].values()
        ):
            return super()._compare_candidate(run, candidate, record, old)
        try:
            return compare_version(
                old_stamp=candidate["baseline_stamp"],
                new_stamp=record.values["source_update_stamp_raw"],
                old_hash=self._revision_content_hash(candidate["baseline_revision_id"], old),
                new_hash=record_hash(record),
                old_kind=candidate["baseline_kind"],
                new_kind=record.document_kind,
            )
        except ExportValidationError as exc:
            if exc.code != "knowledge_source_version_conflict":
                raise
            # 受管在线采集以本次内容为准；保留来源时间戳及不可变历史修订。
            return "revised"

    def same_stamp_event(self, candidate: dict[str, Any], phase: str) -> dict[str, Any] | None:
        if (
            candidate["outcome"] != "revised"
            or candidate["baseline_stamp"] is None
            or candidate["baseline_stamp"] != candidate["observed_stamp"]
        ):
            return None
        before, after = candidate["baseline_revision_id"], candidate["candidate_revision_id"]
        return {
            "event_id": stable_id(
                "same-stamp-revised", candidate["run_id"], candidate["document_id"], phase
            ),
            "run_id": candidate["run_id"],
            "source_id": candidate["source_id"],
            "document_id": candidate["document_id"],
            "external_id": candidate["external_id"],
            "old_revision_id": before,
            "new_revision_id": after,
            "old_stamp": candidate["baseline_stamp"],
            "new_stamp": candidate["observed_stamp"],
            "old_semantic_hash": self._revision_content_hash(before, self.revision(before)),
            "new_semantic_hash": self._revision_content_hash(after, self.revision(after)),
            "old_kind": candidate["baseline_kind"],
            "new_kind": candidate["candidate_kind"],
            "outcome": "revised",
            "phase": phase,
            "reason": "same_source_stamp_content_changed",
        }

    def collection_page_events(
        self, run: dict[str, Any], records: tuple[PreparedRecord, ...]
    ) -> list[dict[str, Any]]:
        events = []
        for record in records:
            document_id = stable_id(
                "document", run["source_id"], "ones_work_item", record.external_id
            )
            candidate = self.candidate(run["id"], document_id)
            if candidate is not None:
                event = self.same_stamp_event(candidate, "STAGED")
                if event is not None:
                    events.append(event)
        return events

    def check_visibility(self, run: dict[str, Any], binding: dict[str, Any]) -> None:
        manifest = run["manifest_json"]["defect"]
        zone = ZoneInfo("Asia/Shanghai")
        start = datetime.combine(date.fromisoformat(manifest["scan_first"]), time.min, zone)
        end = datetime.combine(
            date.fromisoformat(manifest["scan_last"]) + timedelta(days=1), time.min, zone
        )
        projects = binding["configuration_json"]["collector"]["project_ids"]
        parent = (
            "r.source_snapshot->'detail'->>'parent_uuid'"
            if self.database.engine == "postgres"
            else "json_extract(r.source_snapshot,'$.detail.parent_uuid')"
        )
        missing = self.database.execute_one(
            f"select d.id from {self.t('document')} d join {self.t('document_revision')} r on r.id=d.current_revision_id "
            f"where d.source_id=? and d.lifecycle_state='active' and r.source_project_id in ({','.join('?' for _ in projects)}) "
            f"and r.source_created_at>=? and r.source_created_at<? and coalesce({parent},'')='' "
            f"and not exists(select 1 from {self.t('sync_candidate')} c where c.run_id=? and c.document_id=d.id and c.record_hash is not null) limit 1",
            (
                run["source_id"],
                *projects,
                start.astimezone(timezone.utc).isoformat(),
                end.astimezone(timezone.utc).isoformat(),
                run["id"],
            ),
        )
        if missing:
            raise ExportValidationError("knowledge_collection_visibility_shrank")

    def pending(self, run_id: str) -> Iterator[dict[str, Any]]:
        cursor = ""
        while True:
            rows = self.database.execute(
                f"select document_id from {self.t('sync_candidate')} where run_id=? and processing_step<>'DONE' and document_id>? order by document_id limit 100",
                (run_id, cursor),
            )
            if not rows:
                return
            for row in rows:
                candidate = self.candidate(run_id, row["document_id"])
                assert candidate is not None
                yield candidate
            cursor = rows[-1]["document_id"]

    def step(self, candidate: dict[str, Any], step: str, error: str | None = None) -> None:
        with self.database.unit_of_work():
            self.database.execute(
                f"update {self.t('sync_candidate')} set processing_step=?,processing_error=? where run_id=? and document_id=?",
                (step, error, candidate["run_id"], candidate["document_id"]),
            )
            self.database.execute(
                f"update {self.t('sync_run')} set updated_at=? where id=?",
                (now(), candidate["run_id"]),
            )

    def summary(self, run_id: str) -> dict[str, Any]:
        result = super().summary(run_id)
        if not self.run(run_id)["incremental"]:
            return result
        rows = self.database.execute(
            f"select processing_step,count(*) as n from {self.t('sync_candidate')} where run_id=? group by processing_step",
            (run_id,),
        )
        states = {r["processing_step"]: r["n"] for r in rows}
        errors = self.database.execute_one(
            f"select count(*) as n from {self.t('sync_candidate')} where run_id=? and processing_error is not null",
            (run_id,),
        )
        result["documents"] = {
            "total": sum(states.values()),
            "completed": states.get("DONE", 0),
            "failed": errors["n"] if errors else 0,
        }
        result["content_status"] = (
            "COMPLETED"
            if result["phase"] == "ACTIVATED"
            else "PARTIAL"
            if result["documents"]["failed"]
            else "PROCESSING"
        )
        return result

    def prepare_document(self, candidate: dict[str, Any], profile: ChunkProfile) -> None:
        record = {
            **self.revision(candidate["candidate_revision_id"]),
            "revision_id": candidate["candidate_revision_id"],
            "document_kind": candidate["candidate_kind"],
        }
        repository = ChunkRepository(self.database, profile=profile)
        if repository.reuse(record) is None:
            prepared = prepare_chunks(record, profile)
            with self.database.unit_of_work():
                repository._save_immutable(record, prepared)

    def apply_document(self, candidate: dict[str, Any]) -> None:
        with self.database.unit_of_work():
            run = self.run(candidate["run_id"], lock=True)
            self.assert_configuration(run)
            stored = self.candidate(run["id"], candidate["document_id"])
            if stored is None or stored["processing_step"] != "PENDING":
                raise ExportValidationError("knowledge_sync_candidate_conflict")
            current = self.database.execute_one(
                f"select d.current_revision_id,d.lifecycle_state,d.document_kind,d.source_observed_stamp_raw,r.source_update_stamp_raw "
                f"from {self.t('document')} d left join {self.t('document_revision')} r on r.id=d.current_revision_id where d.id=?",
                (candidate["document_id"],),
            )
            if (
                not current
                or current["current_revision_id"] != candidate["baseline_revision_id"]
                or current["lifecycle_state"]
                != ("active" if candidate["baseline_revision_id"] else "pending")
                or current["document_kind"] != candidate["baseline_kind"]
                or (current["source_observed_stamp_raw"] or current["source_update_stamp_raw"])
                != candidate["baseline_stamp"]
                or self._members(candidate["document_id"]) != candidate["baseline_members_json"]
            ):
                raise ExportValidationError("knowledge_sync_baseline_changed")
            if (
                candidate["candidate_revision_id"] == candidate["baseline_revision_id"]
                and candidate["candidate_members_json"] == candidate["baseline_members_json"]
            ):
                self.database.execute(
                    f"update {self.t('document')} set source_observed_stamp_raw=?,last_seen_at=? where id=?",
                    (candidate["observed_stamp"], now(), candidate["document_id"]),
                )
                self.step(candidate, "APPLIED")
                return
            revision = self.revision(candidate["candidate_revision_id"])
            self.database.execute(
                f"update {self.t('document')} set current_revision_id=?,document_kind=?,lifecycle_state='active',source_observed_stamp_raw=?,external_number=?,last_seen_at=? where id=?",
                (
                    revision["id"],
                    candidate["candidate_kind"],
                    candidate["observed_stamp"],
                    str(revision["source_snapshot"]["detail"]["number"]),
                    now(),
                    candidate["document_id"],
                ),
            )
            for base_id, state in candidate["candidate_members_json"].items():
                if state != candidate["baseline_members_json"].get(base_id):
                    insert(
                        self.database,
                        "knowledge_base_document",
                        {
                            "knowledge_base_id": base_id,
                            "document_id": candidate["document_id"],
                            "state": state,
                            "created_at": now(),
                        },
                        conflict="on conflict(knowledge_base_id,document_id) do update set state=excluded.state",
                    )
                index = self.database.execute_one(
                    f"select id,chunk_profile_hash from {self.t('vector_index')} where knowledge_base_id=? and incremental=1 and state='READY'",
                    (base_id,),
                )
                if index:
                    before = candidate["baseline_members_json"].get(base_id) == "included"
                    after = state == "included"

                    def chunk_count(revision_id: str | None, included: bool) -> int:
                        row = (
                            self.database.execute_one(
                                f"select chunk_count from {self.t('document_chunk_set')} where document_revision_id=? and profile_hash=?",
                                (revision_id, index["chunk_profile_hash"]),
                            )
                            if included
                            else None
                        )
                        return int(row["chunk_count"]) if row else 0

                    delta = chunk_count(candidate["candidate_revision_id"], after) - chunk_count(
                        candidate["baseline_revision_id"], before
                    )
                    self.database.execute(
                        f"update {self.t('vector_index')} set expected_document_count=expected_document_count+?,expected_chunk_count=expected_chunk_count+?,updated_at=? where id=?",
                        (int(after) - int(before), delta, now(), index["id"]),
                    )
            self._resolve_document_relations(candidate, run["source_id"])
            self.step(candidate, "APPLIED")

    def _resolve_document_relations(self, candidate: dict[str, Any], source_id: str) -> None:
        relations, documents = self.t("document_relation"), self.t("document")
        self.database.execute(
            f"update {relations} as r set to_document_id=(select d.id from {documents} d "
            "where d.source_id=r.to_source_id and d.source_object_type=r.to_object_type "
            "and d.external_id=r.to_external_id) where r.evidence_revision_id=? and r.to_document_id is null",
            (candidate["candidate_revision_id"],),
        )
        self.database.execute(
            f"update {relations} set to_document_id=? where to_source_id=? and to_object_type='ones_work_item' and to_external_id=? and to_document_id is null",
            (candidate["document_id"], source_id, candidate["external_id"]),
        )


class IncrementalVectorRepository(VectorRepository):
    def index_for(self, base_id: str, source_id: str, profile: ChunkProfile) -> dict[str, Any]:
        found = self.database.execute_one(
            f"select code from {self.t('vector_index')} where knowledge_base_id=? and incremental=1 and state<>'RETIRED'",
            (base_id,),
        )
        if found:
            index = self.get(found["code"])
            if (
                not index
                or index["state"] != "READY"
                or index["source_id"] != source_id
                or index["profile"] != self.profile
                or index["chunk_profile_hash"] != profile.fingerprint
            ):
                raise VectorError("knowledge_sync_resource_profile_changed")
            self._assert_target(index)
            return index
        # 旧语料必须由维护命令转换，不能创建空新集合冒充已准备完整。
        if self._document_count(base_id) or self.database.execute_one(
            f"select id from {self.t('vector_index')} where knowledge_base_id=? and state='READY' limit 1",
            (base_id,),
        ):
            raise VectorError("knowledge_sync_migration_required")
        with self.database.unit_of_work():
            index = self.create(
                "incremental-" + base_id,
                {
                    "knowledge_base_id": base_id,
                    "chunk_profile_hash": profile.fingerprint,
                    "corpus_hash": fingerprint(
                        {"content_contract": "incremental/v1", "base_id": base_id}
                    ),
                    "expected_document_count": 0,
                    "expected_chunk_count": 0,
                },
            )
            self._assert_target(index)
            self.database.execute(
                f"update {self.t('vector_index')} set incremental=1,source_id=?,state='READY' where id=?",
                (source_id, index["id"]),
            )
        return {**index, "incremental": 1, "source_id": source_id, "state": "READY"}

    def _assert_target(self, index: dict[str, Any]) -> None:
        revisions = self.database.execute(
            f"select v.index_id,v.storage_config_json from {self.t('retrieval_resource')} r join {self.t('retrieval_revision')} v on v.id=r.published_revision_id "
            "where r.knowledge_base_id=? and r.status<>'archived'",
            (index["knowledge_base_id"],),
        )
        for revision in revisions:
            config = stored_config(revision["storage_config_json"])
            local = config is None or config == {
                "postgres": {"mode": "platform"},
                "qdrant": {"url": DEFAULT_QDRANT, "api_key_ref": ""},
            }
            if revision["index_id"] != index["id"] or not local:
                raise VectorError("knowledge_sync_resource_profile_changed")

    def document_rows(self, revision_id: str, chunk_profile: str) -> Iterator[dict[str, Any]]:
        cursor = ""
        while True:
            rows = self.database.execute(
                f"select c.*,s.document_id,s.document_revision_id,s.profile_hash as chunk_profile_hash,s.source_content_hash,r.content_hash "
                f"from {self.t('document_chunk_set')} s join {self.t('document_chunk')} c on c.chunk_set_id=s.id "
                f"join {self.t('document_revision')} r on r.id=s.document_revision_id "
                "where s.document_revision_id=? and s.profile_hash=? and c.id>? order by c.id limit 32",
                (revision_id, chunk_profile, cursor),
            )
            if not rows:
                return
            for row in rows:
                if (
                    row["source_content_hash"] != row["content_hash"]
                    or fingerprint(row["embedding_text"]) != row["embedding_hash"]
                    or fingerprint(row["evidence_text"]) != row["evidence_hash"]
                ):
                    raise VectorError("knowledge_vector_source_invalid")
                yield row
            cursor = rows[-1]["id"]

    def register(self, index: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        from app.modules.knowledge.domain.vector_points import point_id

        with self.database.unit_of_work():
            stamp = now()
            self.database.execute(
                f"insert into {self.t('vector_index_item')} "
                "(index_id,chunk_id,point_id,embedding_text_hash,state,attempt_count,error_code,created_at,updated_at) values "
                + ",".join("(?,?,?,?,'PENDING',0,NULL,?,?)" for _ in rows)
                + " on conflict(index_id,chunk_id) do nothing",
                tuple(
                    value
                    for row in rows
                    for value in (
                        index["id"],
                        row["id"],
                        point_id(index, row),
                        row["embedding_hash"],
                        stamp,
                        stamp,
                    )
                ),
            )
            stored = self.database.execute(
                f"select chunk_id,point_id,embedding_text_hash from {self.t('vector_index_item')} where index_id=? and chunk_id in ({','.join('?' for _ in rows)})",
                (index["id"], *(row["id"] for row in rows)),
            )
            actual = {
                row["chunk_id"]: (row["point_id"], row["embedding_text_hash"]) for row in stored
            }
            if actual != {row["id"]: (point_id(index, row), row["embedding_hash"]) for row in rows}:
                raise VectorError("knowledge_vector_manifest_conflict")

    def remove_items(self, index: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        self.database.execute(
            f"delete from {self.t('vector_index_item')} where index_id=? and chunk_id in ({','.join('?' for _ in rows)})",
            (index["id"], *(row["id"] for row in rows)),
        )
