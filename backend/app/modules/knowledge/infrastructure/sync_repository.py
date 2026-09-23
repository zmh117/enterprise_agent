"""同来源候选运行的持久事实；不调用网络、不发布、不修改当前收录。"""

from collections import Counter
from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import Any

from app.modules.knowledge.domain.identity import now, stable_id
from app.modules.knowledge.domain.normalization import (
    ExportValidationError,
    PreparedExport,
    PreparedRecord,
    canonical_json,
    digest,
    identifier,
)
from app.modules.knowledge.domain.sync import (
    checked_configuration,
    semantic_hash,
    next_phase,
    replacement_manifest,
)
from app.modules.knowledge.domain.work_items import KIND_LABELS, compare_version
from app.modules.knowledge.infrastructure.chunk_repository import json_value
from app.modules.knowledge.infrastructure.revision_store import save_revision
from app.modules.knowledge.infrastructure.storage import insert, source_lock, table
from app.shared.database import Database


class SyncRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def t(self, name: str) -> str:
        return table(self.database, name)

    def source_lock(self, source_id: str) -> AbstractContextManager[None]:
        return source_lock(self.database, source_id)

    def configure(
        self,
        *,
        code: str,
        source_code: str,
        configuration: dict[str, Any],
        expected_revision: int,
    ) -> dict[str, Any]:
        identifier(code)
        identifier(source_code)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ExportValidationError("knowledge_sync_configuration_invalid")
        config = checked_configuration(configuration)
        source_id, binding_id = stable_id("source", source_code), stable_id("sync-binding", code)
        with self.source_lock(source_id), self.database.unit_of_work():
            old = self.database.execute_one(
                f"select * from {self.t('sync_binding')} where id=?", (binding_id,)
            )
            if (
                old
                and (
                    old["configuration_revision"] != expected_revision
                    or old["source_id"] != source_id
                )
            ) or (not old and expected_revision != 0):
                raise ExportValidationError("knowledge_sync_configuration_changed")
            if old:
                self.database.execute(
                    f"update {self.t('sync_binding')} set configuration_revision=configuration_revision+1,configuration_hash=?,configuration_json=?,enabled=0,updated_at=? where id=?",
                    (digest(config), canonical_json(config), now(), binding_id),
                )
            else:
                insert(
                    self.database,
                    "source",
                    {
                        "id": source_id,
                        "code": source_code,
                        "display_name": "ONES 离线导出（来源待确认）",
                        "source_system": "ones",
                        "origin_state": "offline_unverified",
                        "identity_metadata": {},
                        "created_at": now(),
                    },
                    conflict="on conflict(code) do nothing",
                )
                source = self.database.execute_one(
                    f"select id,source_system from {self.t('source')} where code=?", (source_code,)
                )
                if not source or source != {"id": source_id, "source_system": "ones"}:
                    raise ExportValidationError("knowledge_source_binding_conflict")
                insert(
                    self.database,
                    "sync_binding",
                    {
                        "id": binding_id,
                        "code": code,
                        "source_id": source_id,
                        "configuration_revision": 1,
                        "configuration_hash": digest(config),
                        "configuration_json": config,
                        "enabled": 0,
                        "interval_seconds": 3600,
                        "next_run_at": None,
                        "created_at": now(),
                        "updated_at": now(),
                    },
                )
            for kind, base_code in config["base_codes"].items():
                base_id = stable_id("base", base_code)
                insert(
                    self.database,
                    "knowledge_base",
                    {
                        "id": base_id,
                        "code": base_code,
                        "display_name": f"ONES {KIND_LABELS[kind]}知识库",
                        "description": "来源文本与关联引用；收录不授予访问权限。",
                        "state": "storage_only",
                        "created_at": now(),
                    },
                    conflict="on conflict(code) do nothing",
                )
                base = self.database.execute_one(
                    f"select id,state from {self.t('knowledge_base')} where code=?", (base_code,)
                )
                if not base or base != {"id": base_id, "state": "storage_only"}:
                    raise ExportValidationError("knowledge_base_binding_conflict")
        return self.binding(binding_id)

    def binding(self, binding_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            f"select * from {self.t('sync_binding')} where id=?", (binding_id,)
        )
        if not row:
            raise ExportValidationError("knowledge_sync_binding_unavailable")
        row["configuration_json"] = checked_configuration(json_value(row["configuration_json"]))
        if digest(row["configuration_json"]) != row["configuration_hash"]:
            raise ExportValidationError("knowledge_sync_configuration_changed")
        return row

    def run(self, run_id: str, *, lock: bool = False) -> dict[str, Any]:
        suffix = " for update" if lock and self.database.engine == "postgres" else ""
        row = self.database.execute_one(
            f"select * from {self.t('sync_run')} where id=?{suffix}", (run_id,)
        )
        if not row:
            raise ExportValidationError("knowledge_sync_run_unavailable")
        for key in ("manifest_json", "checkpoint_json", "resource_baseline_json"):
            row[key] = json_value(row[key])
        return row

    def assert_configuration(self, run: dict[str, Any]) -> dict[str, Any]:
        binding = self.binding(run["binding_id"])
        if (
            binding["configuration_revision"] != run["binding_revision"]
            or binding["configuration_hash"] != run["configuration_hash"]
        ):
            raise ExportValidationError("knowledge_sync_configuration_changed")
        return binding

    def _members(self, document_id: str) -> dict[str, str]:
        rows = self.database.execute(
            f"select knowledge_base_id,state from {self.t('knowledge_base_document')} where document_id=? order by knowledge_base_id",
            (document_id,),
        )
        return {row["knowledge_base_id"]: row["state"] for row in rows}

    def begin(self, binding_id: str, exports: tuple[PreparedExport, ...]) -> dict[str, Any]:
        run = self._begin(binding_id, exports)
        if run["phase"] == "COLLECTING":
            try:
                while self._freeze_page(run["id"]):
                    pass
            except Exception as exc:
                self.fail(
                    run["id"],
                    exc.code if isinstance(exc, ExportValidationError) else "knowledge_sync_failed",
                )
                raise ExportValidationError(
                    exc.code if isinstance(exc, ExportValidationError) else "knowledge_sync_failed"
                ) from None
        return self.run(run["id"])

    def _begin(self, binding_id: str, exports: tuple[PreparedExport, ...]) -> dict[str, Any]:
        manifests = {item.manifest["document_kind"]: item.manifest for item in exports}
        replacement_manifest(manifests)
        input_hash = digest(manifests)
        with self.database.unit_of_work():
            binding = self.binding(binding_id)
            run_id = stable_id(
                "sync-run", binding_id, str(binding["configuration_revision"]), input_hash
            )
            existing = self.database.execute_one(
                f"select id from {self.t('sync_run')} where id=?", (run_id,)
            )
            if existing:
                run = self.run(run_id)
                self.assert_configuration(run)
                if run["phase"] == "CANCELLED":
                    raise ExportValidationError("knowledge_sync_run_cancelled")
                return run
            busy = self.database.execute_one(
                f"select id from {self.t('sync_run')} where source_id=? and active=1",
                (binding["source_id"],),
            )
            if busy:
                raise ExportValidationError("knowledge_source_import_busy")
            resources = self.database.execute(
                f"select r.id,r.status,r.revision,r.state_revision,r.draft_revision_id,r.published_revision_id "
                f"from {self.t('retrieval_resource')} r where exists(select 1 from {self.t('knowledge_base_document')} m "
                f"join {self.t('document')} d on d.id=m.document_id where m.knowledge_base_id=r.knowledge_base_id and d.source_id=?) order by r.id",
                (binding["source_id"],),
            )
            insert(
                self.database,
                "sync_run",
                {
                    "id": run_id,
                    "binding_id": binding_id,
                    "source_id": binding["source_id"],
                    "binding_revision": binding["configuration_revision"],
                    "configuration_hash": binding["configuration_hash"],
                    "input_hash": input_hash,
                    "phase": "COLLECTING",
                    "active": 1,
                    "manifest_json": manifests,
                    "checkpoint_json": {
                        "processed": 0,
                        "total": sum(len(item.records) for item in exports),
                    },
                    "resource_baseline_json": resources,
                    "activated_watermark": None,
                    "error_code": None,
                    "created_at": now(),
                    "updated_at": now(),
                },
            )
            for item in exports:
                kind = item.manifest["document_kind"]
                base_id = stable_id("base", binding["configuration_json"]["base_codes"][kind])
                insert(
                    self.database,
                    "import_run",
                    {
                        "id": stable_id("sync-import", run_id, kind),
                        "source_id": binding["source_id"],
                        "knowledge_base_id": base_id,
                        "input_hash": digest([run_id, item.manifest]),
                        "input_manifest": item.manifest,
                        "state": "running",
                        "total_count": len(item.records),
                        "started_at": now(),
                        "updated_at": now(),
                    },
                )
        return self.run(run_id)

    def _freeze_page(self, run_id: str) -> bool:
        # 来源锁跨批次持有，数据库只锁住本页；进度与本页事实一并提交。
        with self.database.unit_of_work():
            run = self.run(run_id, lock=True)
            binding = self.assert_configuration(run)
            checkpoint = run["checkpoint_json"]
            if checkpoint.get("baseline_complete"):
                return False
            if run["phase"] != "COLLECTING" or checkpoint["processed"]:
                raise ExportValidationError("knowledge_sync_phase_invalid")
            source_id, cursor = run["source_id"], checkpoint.get("baseline_cursor", "")
            rows = self.database.execute(
                f"select d.*,r.source_update_stamp_raw from {self.t('document')} d "
                f"left join {self.t('document_revision')} r on r.id=d.current_revision_id "
                "where d.source_id=? and d.id>? order by d.id limit 200",
                (source_id, cursor),
            )
            count = checkpoint.get("baseline_seen", 0) + len(rows)
            if count > 200_000:
                raise ExportValidationError("knowledge_sync_source_limit")
            for row in rows:
                if row["lifecycle_state"] != "active":
                    continue
                if row["document_kind"] not in KIND_LABELS or not row["current_revision_id"]:
                    raise ExportValidationError("knowledge_sync_baseline_invalid")
                members = self._members(row["id"])
                selected_members = members
                if replacement_manifest(run["manifest_json"]):
                    targets = {
                        stable_id("base", code)
                        for code in binding["configuration_json"]["base_codes"].values()
                    }
                    if any(
                        state == "included" and key not in targets for key, state in members.items()
                    ):
                        raise ExportValidationError("knowledge_replacement_scope_invalid")
                    selected_members = {
                        key: "removed" if key in targets else state
                        for key, state in members.items()
                    }
                stamp = row["source_observed_stamp_raw"] or row["source_update_stamp_raw"]
                insert(
                    self.database,
                    "sync_candidate",
                    {
                        "run_id": run_id,
                        "source_id": source_id,
                        "external_id": row["external_id"],
                        "document_id": row["id"],
                        "baseline_revision_id": row["current_revision_id"],
                        "baseline_kind": row["document_kind"],
                        "baseline_members_json": members,
                        "baseline_stamp": stamp,
                        "candidate_revision_id": row["current_revision_id"],
                        "candidate_kind": row["document_kind"],
                        "candidate_members_json": selected_members,
                        "observed_stamp": stamp,
                        "record_hash": None,
                        "outcome": "baseline",
                    },
                )
            checkpoint = {
                **checkpoint,
                "baseline_complete": not rows,
                "baseline_seen": count,
                "baseline_cursor": rows[-1]["id"] if rows else cursor,
            }
            self.database.execute(
                f"update {self.t('sync_run')} set checkpoint_json=?,updated_at=? where id=?",
                (canonical_json(checkpoint), now(), run_id),
            )
            return bool(rows)

    def candidate(self, run_id: str, document_id: str) -> dict[str, Any] | None:
        row = self.database.execute_one(
            f"select * from {self.t('sync_candidate')} where run_id=? and document_id=?",
            (run_id, document_id),
        )
        if row:
            for key in ("baseline_members_json", "candidate_members_json"):
                row[key] = json_value(row[key])
        return row

    def revision(self, revision_id: str) -> dict[str, Any]:
        row = self.database.execute_one(
            f"select * from {self.t('document_revision')} where id=?", (revision_id,)
        )
        if not row:
            raise ExportValidationError("knowledge_sync_baseline_invalid")
        for key in ("attributes", "source_snapshot", "completeness"):
            row[key] = json_value(row[key])
        for key in ("source_created_at", "source_updated_at"):
            if hasattr(row[key], "isoformat"):
                row[key] = row[key].isoformat()
        return row

    def stage(self, run_id: str, record: PreparedRecord) -> str:
        from app.modules.knowledge.domain.sync import candidate_members

        with self.database.unit_of_work():
            run = self.run(run_id, lock=True)
            binding = self.assert_configuration(run)
            if run["phase"] != "COLLECTING" or not run["checkpoint_json"].get("baseline_complete"):
                raise ExportValidationError("knowledge_sync_phase_invalid")
            kind, source_id = record.document_kind, run["source_id"]
            if kind not in run["manifest_json"]:
                raise ExportValidationError("knowledge_source_type_mismatch")
            document_id = stable_id("document", source_id, "ones_work_item", record.external_id)
            candidate = self.candidate(run_id, document_id)
            if candidate and candidate["record_hash"] is not None:
                if (
                    candidate["record_hash"] != record.content_hash
                    or candidate["candidate_kind"] != kind
                    and candidate["outcome"] != "stale"
                ):
                    raise ExportValidationError("knowledge_sync_candidate_conflict")
                return str(candidate["outcome"])
            if not candidate:
                old_document = self.database.execute_one(
                    f"select lifecycle_state,current_revision_id from {self.t('document')} where id=?",
                    (document_id,),
                )
                if old_document and (
                    old_document["lifecycle_state"] != "pending"
                    or old_document["current_revision_id"] is not None
                ):
                    raise ExportValidationError("knowledge_sync_baseline_changed")
                if not old_document:
                    insert(
                        self.database,
                        "document",
                        {
                            "id": document_id,
                            "source_id": source_id,
                            "source_object_type": "ones_work_item",
                            "external_id": record.external_id,
                            "external_number": record.external_number,
                            "document_kind": kind,
                            "lifecycle_state": "pending",
                            "created_at": now(),
                            "last_seen_at": now(),
                        },
                    )
                candidate = {
                    "run_id": run_id,
                    "source_id": source_id,
                    "external_id": record.external_id,
                    "document_id": document_id,
                    "baseline_revision_id": None,
                    "baseline_kind": kind,
                    "baseline_members_json": {},
                    "baseline_stamp": None,
                    "candidate_revision_id": None,
                    "candidate_kind": kind,
                    "candidate_members_json": {},
                    "observed_stamp": None,
                    "record_hash": None,
                    "outcome": "baseline",
                }
                insert(self.database, "sync_candidate", candidate)
            outcome = "created"
            if candidate["baseline_revision_id"]:
                old = self.revision(candidate["baseline_revision_id"])
                if replacement_manifest(run["manifest_json"]):
                    # 明确替换测试快照，不是把同时间戳冲突普遍改为后写覆盖。
                    outcome = (
                        "unchanged"
                        if old["content_hash"] == record.content_hash
                        and candidate["baseline_kind"] == kind
                        else "revised"
                    )
                else:
                    outcome = compare_version(
                        old_stamp=candidate["baseline_stamp"],
                        new_stamp=record.values["source_update_stamp_raw"],
                        old_hash=semantic_hash(old),
                        new_hash=semantic_hash(record.values),
                        old_kind=candidate["baseline_kind"],
                        new_kind=kind,
                    )
            revision_id = candidate["baseline_revision_id"]
            if outcome in {"created", "revised"}:
                revision_id = stable_id("sync-revision", run_id, document_id)
                number_row = self.database.execute_one(
                    f"select coalesce(max(revision_no),0)+1 as n from {self.t('document_revision')} where document_id=?",
                    (document_id,),
                )
                assert number_row is not None
                number = number_row["n"]
                save_revision(
                    self.database,
                    record,
                    source_id=source_id,
                    document_id=document_id,
                    revision_id=revision_id,
                    import_run_id=stable_id("sync-import", run_id, kind),
                    revision_no=number,
                )
            base_ids = {
                key: stable_id("base", code)
                for key, code in binding["configuration_json"]["base_codes"].items()
            }
            members = (
                candidate["baseline_members_json"]
                if outcome == "stale"
                else candidate_members(
                    candidate["baseline_members_json"],
                    kind=kind,
                    old_kind=candidate["baseline_kind"],
                    base_ids=base_ids,
                )
            )
            self.database.execute(
                f"update {self.t('sync_candidate')} set candidate_revision_id=?,candidate_kind=?,candidate_members_json=?,observed_stamp=?,record_hash=?,outcome=? where run_id=? and document_id=?",
                (
                    revision_id,
                    candidate["baseline_kind"] if outcome == "stale" else kind,
                    canonical_json(members),
                    candidate["baseline_stamp"]
                    if outcome == "stale"
                    else record.values["source_update_stamp_raw"],
                    record.content_hash,
                    outcome,
                    run_id,
                    document_id,
                ),
            )
            self.database.execute(
                f"update {self.t('import_run')} set processed_count=processed_count+1,{outcome}_count={outcome}_count+1,updated_at=? where id=?",
                (now(), stable_id("sync-import", run_id, kind)),
            )
            checkpoint = {
                **run["checkpoint_json"],
                "processed": run["checkpoint_json"]["processed"] + 1,
            }
            self.database.execute(
                f"update {self.t('sync_run')} set checkpoint_json=?,error_code=NULL,updated_at=? where id=?",
                (canonical_json(checkpoint), now(), run_id),
            )
        return outcome

    def finish_staging(self, run_id: str) -> dict[str, Any]:
        with self.database.unit_of_work():
            run = self.run(run_id, lock=True)
            self.assert_configuration(run)
            if (
                run["phase"] != "COLLECTING"
                or run["checkpoint_json"]["processed"] != run["checkpoint_json"]["total"]
            ):
                raise ExportValidationError("knowledge_sync_incomplete")
            for kind in run["manifest_json"]:
                imported = self.database.execute_one(
                    f"select total_count,processed_count from {self.t('import_run')} where id=?",
                    (stable_id("sync-import", run_id, kind),),
                )
                if not imported or imported["total_count"] != imported["processed_count"]:
                    raise ExportValidationError("knowledge_sync_incomplete")
                self.database.execute(
                    f"update {self.t('import_run')} set state='completed',updated_at=?,completed_at=? where id=?",
                    (now(), now(), stable_id("sync-import", run_id, kind)),
                )
            self.database.execute(
                f"update {self.t('sync_run')} set phase='STAGED',error_code=NULL,updated_at=? where id=?",
                (now(), run_id),
            )
        return self.summary(run_id)

    def fail(self, run_id: str, code: str) -> None:
        # 只接受内部预定义错误码，不能把异常正文写入数据库。
        safe = (
            code
            if code.startswith("knowledge_")
            and len(code) < 128
            and all(c.islower() or c == "_" for c in code)
            else "knowledge_sync_failed"
        )
        self.database.execute(
            f"update {self.t('sync_run')} set error_code=?,updated_at=? where id=? and active=1",
            (safe, now(), run_id),
        )

    def advance(self, run_id: str, *, expected_phase: str, phase: str) -> None:
        # ACTIVATED 必须由内容、索引与发布一起提交，不能经通用阶段推进绕过。
        next_phase(expected_phase, phase)
        if phase in {"STAGED", "ACTIVATED"}:
            raise ExportValidationError("knowledge_sync_phase_invalid")
        with self.database.unit_of_work():
            run = self.run(run_id, lock=True)
            self.assert_configuration(run)
            if run["phase"] != expected_phase:
                raise ExportValidationError("knowledge_sync_phase_invalid")
            self.database.execute(
                f"update {self.t('sync_run')} set phase=?,error_code=NULL,updated_at=? where id=?",
                (phase, now(), run_id),
            )

    def cancel(self, run_id: str) -> None:
        initial = self.run(run_id)
        with self.source_lock(initial["source_id"]), self.database.unit_of_work():
            run = self.run(run_id, lock=True)
            if run["phase"] == "CANCELLED":
                return
            if run["phase"] == "ACTIVATED":
                raise ExportValidationError("knowledge_sync_phase_invalid")
            self.database.execute(
                f"update {self.t('sync_run')} set phase='CANCELLED',active=0,updated_at=? where id=?",
                (now(), run_id),
            )

    def assert_baseline(self, run_id: str) -> None:
        run = self.run(run_id)
        self.assert_configuration(run)
        for candidate in self.candidates(run_id):
            current = self.database.execute_one(
                f"select d.current_revision_id,d.lifecycle_state,d.document_kind,d.source_observed_stamp_raw,r.source_update_stamp_raw "
                f"from {self.t('document')} d left join {self.t('document_revision')} r on r.id=d.current_revision_id where d.id=?",
                (candidate["document_id"],),
            )
            expected_state = "active" if candidate["baseline_revision_id"] else "pending"
            if (
                not current
                or current["current_revision_id"] != candidate["baseline_revision_id"]
                or current["lifecycle_state"] != expected_state
                or current["document_kind"] != candidate["baseline_kind"]
                or (current["source_observed_stamp_raw"] or current["source_update_stamp_raw"])
                != candidate["baseline_stamp"]
                or self._members(candidate["document_id"]) != candidate["baseline_members_json"]
            ):
                raise ExportValidationError("knowledge_sync_baseline_changed")
        added = self.database.execute_one(
            f"select d.id from {self.t('document')} d where d.source_id=? and d.lifecycle_state='active' "
            f"and not exists(select 1 from {self.t('sync_candidate')} c where c.run_id=? and c.document_id=d.id) limit 1",
            (run["source_id"], run_id),
        )
        if added:
            raise ExportValidationError("knowledge_sync_baseline_changed")

    def changed_bases(self, run_id: str) -> set[str]:
        run = self.run(run_id)
        self.assert_configuration(run)
        changed: set[str] = set()
        for item in self.candidates(run_id):
            before, after = item["baseline_members_json"], item["candidate_members_json"]
            for base_id in before.keys() | after.keys():
                if before.get(base_id) != after.get(base_id) or (
                    after.get(base_id) == "included"
                    and (
                        item["baseline_revision_id"] != item["candidate_revision_id"]
                        or item["baseline_kind"] != item["candidate_kind"]
                    )
                ):
                    changed.add(base_id)
        return changed

    def summary(self, run_id: str) -> dict[str, Any]:
        run = self.run(run_id)
        counts = self.database.execute(
            f"select outcome,count(*) as n from {self.t('sync_candidate')} where run_id=? group by outcome",
            (run_id,),
        )
        return {
            "run_id": run_id,
            "phase": run["phase"],
            "checkpoint": {key: run["checkpoint_json"][key] for key in ("processed", "total")},
            "counts": dict(Counter({row["outcome"]: row["n"] for row in counts})),
            "error_code": run["error_code"],
        }

    def candidates(self, run_id: str) -> Iterator[dict[str, Any]]:
        cursor = ""
        while True:
            rows = self.database.execute(
                f"select * from {self.t('sync_candidate')} where run_id=? and document_id>? order by document_id limit 100",
                (run_id, cursor),
            )
            if not rows:
                return
            for row in rows:
                row["baseline_members_json"] = json_value(row["baseline_members_json"])
                row["candidate_members_json"] = json_value(row["candidate_members_json"])
                yield row
            cursor = rows[-1]["document_id"]
