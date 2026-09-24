"""同来源候选运行的持久事实；不调用网络、不发布、不修改当前收录。"""

from collections import Counter
from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import date, datetime, timedelta
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
from app.modules.knowledge.domain.storage_connection import stored_config
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.application.content_access import ContentRepository
from app.modules.knowledge.infrastructure.chunk_repository import json_value
from app.modules.knowledge.infrastructure.import_repository import ImportRepository
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.infrastructure.revision_store import save_revision
from app.modules.knowledge.infrastructure.storage import insert, source_lock, table
from app.shared.database import Database


class SyncRepository:  # noqa: PLR0904
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
                previous = checked_configuration(json_value(old["configuration_json"]))
                if previous.get("collector") and previous["collector"] != config.get("collector"):
                    prior_run = self.database.execute_one(
                        f"select id from {self.t('sync_run')} where binding_id=? limit 1",
                        (binding_id,),
                    )
                    if prior_run:
                        raise ExportValidationError("knowledge_collection_scope_changed")
                self.database.execute(
                    f"update {self.t('sync_binding')} set configuration_revision=configuration_revision+1,configuration_hash=?,configuration_json=?,resource_pins_json='{{}}',enabled=0,next_run_at=NULL,updated_at=? where id=?",
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
                        "resource_pins_json": {},
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

    def binding(self, binding_id: str, *, lock: bool = False) -> dict[str, Any]:
        suffix = " for update" if lock and self.database.engine == "postgres" else ""
        row = self.database.execute_one(
            f"select * from {self.t('sync_binding')} where id=?{suffix}", (binding_id,)
        )
        if not row:
            raise ExportValidationError("knowledge_sync_binding_unavailable")
        row["configuration_json"] = checked_configuration(json_value(row["configuration_json"]))
        row["resource_pins_json"] = json_value(row["resource_pins_json"])
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

    def assert_configuration(self, run: dict[str, Any], *, lock: bool = False) -> dict[str, Any]:
        binding = self.binding(run["binding_id"], lock=lock)
        if (
            binding["configuration_revision"] != run["binding_revision"]
            or binding["configuration_hash"] != run["configuration_hash"]
        ):
            raise ExportValidationError("knowledge_sync_configuration_changed")
        if (
            all(
                item.get("export_format") == "ones-online-full/v1"
                for item in run["manifest_json"].values()
            )
            and binding["enabled"] != 1
        ):
            raise ExportValidationError("knowledge_collection_disabled")
        return binding

    def scoped_resources(
        self, binding: dict[str, Any], *, lock: bool = False
    ) -> list[dict[str, Any]]:
        base_ids = tuple(
            stable_id("base", code) for code in binding["configuration_json"]["base_codes"].values()
        )
        suffix = " for update" if lock and self.database.engine == "postgres" else ""
        return self.database.execute(
            f"select * from {self.t('retrieval_resource')} where knowledge_base_id in "
            f"({','.join('?' for _ in base_ids)}) order by id{suffix}",
            base_ids,
        )

    def resource_pin(self, resource: dict[str, Any], *, source_id: str) -> dict[str, Any]:
        if (
            resource["status"] != "enabled"
            or resource["draft_revision_id"] is not None
            or not resource["published_revision_id"]
        ):
            raise ExportValidationError("knowledge_sync_resource_changed")
        revision = self.database.execute_one(
            f"select * from {self.t('retrieval_revision')} where id=? and resource_id=?",
            (resource["published_revision_id"], resource["id"]),
        )
        if not revision or revision["configuration_version"] != 4 or not revision["published_at"]:
            raise ExportValidationError("knowledge_sync_resource_changed")
        try:
            selected = stored_config(revision.get("storage_config_json"))
        except KnowledgeGovernanceError:
            raise ExportValidationError("knowledge_sync_resource_changed") from None
        if selected is not None and selected["postgres"]["mode"] != "platform":
            raise ExportValidationError("knowledge_sync_external_content_unsupported")
        index = self.database.execute_one(
            f"select id,knowledge_base_id,source_id,state,profile_hash,chunk_profile_hash,expected_document_count "
            f"from {self.t('vector_index')} where id=?",
            (revision["index_id"],),
        )
        if (
            not index
            or index["state"] != "READY"
            or index["knowledge_base_id"] != resource["knowledge_base_id"]
            or index["source_id"] not in {None, source_id}
            or index["profile_hash"] != revision["profile_hash"]
        ):
            raise ExportValidationError("knowledge_sync_resource_changed")
        sources = self.database.execute(
            f"select distinct d.source_id from {self.t('knowledge_base_document')} m "
            f"join {self.t('document')} d on d.id=m.document_id "
            "where m.knowledge_base_id=? and m.state='included' and d.lifecycle_state='active' limit 2",
            (resource["knowledge_base_id"],),
        )
        if (
            sources
            and (len(sources) != 1 or sources[0]["source_id"] != source_id)
            or (
                not sources
                and (index["source_id"] != source_id or index["expected_document_count"] != 0)
            )
        ):
            raise ExportValidationError("knowledge_sync_resource_scope_changed")
        return {
            "knowledge_base_id": resource["knowledge_base_id"],
            "revision": resource["revision"],
            "state_revision": resource["state_revision"],
            "published_revision_id": revision["id"],
            "config_hash": revision["config_hash"],
            "profile_hash": index["profile_hash"],
            "chunk_profile_hash": index["chunk_profile_hash"],
        }

    def current_resource_pins(
        self, binding: dict[str, Any], *, lock: bool = False
    ) -> dict[str, Any]:
        configured = set(binding["configuration_json"]["resource_ids"])
        rows = self.scoped_resources(binding, lock=lock)
        if any(row["published_revision_id"] and row["id"] not in configured for row in rows):
            raise ExportValidationError("knowledge_sync_resource_scope_changed")
        selected = {row["id"]: row for row in rows if row["id"] in configured}
        if set(selected) != configured:
            raise ExportValidationError("knowledge_sync_resource_scope_changed")
        return {
            resource_id: self.resource_pin(row, source_id=binding["source_id"])
            for resource_id, row in selected.items()
        }

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

    def begin_collection(self, binding_id: str, scan_at: str) -> dict[str, Any]:
        """建立在线完整扫描运行；实际总数由逐页提交累加。"""
        binding = self.binding(binding_id)
        collector = binding["configuration_json"].get("collector")
        if not collector or binding["enabled"] != 1:
            raise ExportValidationError("knowledge_collection_disabled")
        try:
            parsed_scan = datetime.fromisoformat(scan_at)
        except (TypeError, ValueError):
            raise ExportValidationError("knowledge_collection_scan_invalid") from None
        if parsed_scan.tzinfo is None or len(scan_at) > 40:
            raise ExportValidationError("knowledge_collection_scan_invalid")
        manifests = tuple(
            PreparedExport(
                (),
                {
                    "document_kind": kind,
                    "export_format": "ones-online-full/v1",
                    "record_count": 0,
                    "scan_at": scan_at,
                    "scope_hash": digest(collector),
                },
                {},
            )
            for kind in ("defect", "ticket", "requirement")
        )
        return self.begin(binding_id, manifests)

    def active_collection(self, binding_id: str) -> dict[str, Any] | None:
        binding = self.binding(binding_id)
        active = self.database.execute_one(
            f"select id,binding_id from {self.t('sync_run')} where source_id=? and active=1",
            (binding["source_id"],),
        )
        if not active:
            return None
        if active["binding_id"] != binding_id:
            raise ExportValidationError("knowledge_source_import_busy")
        run = self.run(active["id"])
        self.assert_configuration(run)
        if not all(
            item.get("export_format") == "ones-online-full/v1"
            for item in run["manifest_json"].values()
        ):
            raise ExportValidationError("knowledge_source_import_busy")
        return run

    def set_collection_enabled(
        self, binding_id: str, *, enabled: bool, expected_revision: int
    ) -> dict[str, Any]:
        """显式双门禁中的绑定开关；更新配置后始终回到关闭。"""
        if type(enabled) is not bool or type(expected_revision) is not int:
            raise ExportValidationError("knowledge_sync_configuration_invalid")
        with self.database.unit_of_work():
            binding = self.binding(binding_id, lock=True)
            if binding["configuration_revision"] != expected_revision:
                raise ExportValidationError("knowledge_sync_configuration_changed")
            if enabled and not binding["configuration_json"].get("collector"):
                raise ExportValidationError("knowledge_collection_configuration_invalid")
            if enabled:
                active = self.database.execute_one(
                    f"select id from {self.t('sync_run')} where source_id=? and active=1",
                    (binding["source_id"],),
                )
                if active:
                    raise ExportValidationError("knowledge_source_import_busy")
                pins = self.current_resource_pins(binding, lock=True)
            else:
                pins = binding["resource_pins_json"]
            self.database.execute(
                f"update {self.t('sync_binding')} set enabled=?,resource_pins_json=?,next_run_at=?,updated_at=? where id=? and configuration_revision=?",
                (
                    int(enabled),
                    canonical_json(pins),
                    (datetime.fromisoformat(now()) + timedelta(seconds=3600)).isoformat()
                    if enabled
                    else None,
                    now(),
                    binding_id,
                    expected_revision,
                ),
            )
        return self.binding(binding_id)

    def active_run(self, binding_id: str) -> dict[str, Any] | None:
        binding = self.binding(binding_id)
        active = self.database.execute_one(
            f"select id,binding_id from {self.t('sync_run')} where source_id=? and active=1",
            (binding["source_id"],),
        )
        if not active:
            return None
        if active["binding_id"] != binding_id:
            raise ExportValidationError("knowledge_source_import_busy")
        return self.run(active["id"])

    def scheduled_due(self, binding_id: str, at: datetime) -> bool:
        if at.tzinfo is None:
            raise ExportValidationError("knowledge_sync_clock_invalid")
        binding = self.binding(binding_id)
        if binding["enabled"] != 1:
            return False
        if self.active_run(binding_id) is not None:
            return True
        due = binding["next_run_at"]
        if due is None:
            raise ExportValidationError("knowledge_sync_schedule_invalid")
        if isinstance(due, str):
            due = datetime.fromisoformat(due)
        if not isinstance(due, datetime) or due.tzinfo is None:
            raise ExportValidationError("knowledge_sync_schedule_invalid")
        return at >= due

    def scheduled_started(self, binding_id: str, run_id: str, at: datetime) -> None:
        if at.tzinfo is None:
            raise ExportValidationError("knowledge_sync_clock_invalid")
        with self.database.unit_of_work():
            binding = self.binding(binding_id, lock=True)
            run = self.run(run_id, lock=True)
            if (
                binding["enabled"] != 1
                or run["binding_id"] != binding_id
                or run["phase"] != "COLLECTING"
            ):
                raise ExportValidationError("knowledge_collection_disabled")
            due = binding["next_run_at"]
            if isinstance(due, str):
                due = datetime.fromisoformat(due)
            if due is None or due.tzinfo is None:
                raise ExportValidationError("knowledge_sync_schedule_invalid")
            if at >= due:
                self.database.execute(
                    f"update {self.t('sync_binding')} set next_run_at=?,updated_at=? where id=?",
                    ((at + timedelta(seconds=3600)).isoformat(), now(), binding_id),
                )

    def cancel_disabled_collection(self, run_id: str) -> None:
        """运行者持有来源锁时响应停用，不等待整轮结束。"""
        with self.database.unit_of_work():
            run = self.run(run_id, lock=True)
            binding = self.binding(run["binding_id"])
            if binding["enabled"] == 0 and run["phase"] == "COLLECTING":
                self.database.execute(
                    f"update {self.t('sync_run')} set phase='CANCELLED',active=0,"
                    "error_code='knowledge_collection_disabled',updated_at=? where id=?",
                    (now(), run_id),
                )

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
            resources = [
                {
                    key: row[key]
                    for key in (
                        "id",
                        "knowledge_base_id",
                        "status",
                        "revision",
                        "state_revision",
                        "draft_revision_id",
                        "published_revision_id",
                    )
                }
                for row in self.scoped_resources(binding)
            ]
            if (
                all(
                    item.get("export_format") == "ones-online-full/v1"
                    for item in manifests.values()
                )
                and self.current_resource_pins(binding) != binding["resource_pins_json"]
            ):
                raise ExportValidationError("knowledge_sync_resource_changed")
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
            online = all(
                item.get("export_format") == "ones-online-full/v1"
                for item in run["manifest_json"].values()
            )
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
                f"update {self.t('import_run')} set processed_count=processed_count+1,"
                f"total_count=total_count+{1 if online else 0},"
                f"{outcome}_count={outcome}_count+1,updated_at=? where id=?",
                (now(), stable_id("sync-import", run_id, kind)),
            )
            checkpoint = {
                **run["checkpoint_json"],
                "processed": run["checkpoint_json"]["processed"] + 1,
                "total": run["checkpoint_json"]["total"] + (1 if online else 0),
            }
            self.database.execute(
                f"update {self.t('sync_run')} set checkpoint_json=?,error_code=NULL,updated_at=? where id=?",
                (canonical_json(checkpoint), now(), run_id),
            )
        return outcome

    def commit_collection_page(
        self,
        run_id: str,
        records: tuple[PreparedRecord, ...],
        checkpoint: dict[str, Any],
    ) -> None:
        """本页候选与安全检查点同事务；崩溃后重放原页不重复计数。"""
        allowed = {
            "kind",
            "issue_type_id",
            "first",
            "last",
            "next_cursor",
            "enumerated",
            "expected",
            "children_processed",
            "children_total",
        }
        if (
            not isinstance(checkpoint, dict)
            or not set(checkpoint) <= allowed
            or checkpoint.get("kind") not in {"defect", "ticket", "requirement"}
            or not records
            or len(records) > 200
            or any(record.content_hash != digest(record.values) for record in records)
        ):
            raise ExportValidationError("knowledge_collection_checkpoint_invalid")
        children_page = "children_processed" in checkpoint
        if children_page:
            if (
                set(checkpoint) != {"kind", "children_processed", "children_total"}
                or checkpoint["kind"] != "requirement"
                or type(checkpoint["children_processed"]) is not int
                or type(checkpoint["children_total"]) is not int
                or not 1
                <= checkpoint["children_processed"]
                <= checkpoint["children_total"]
                <= 200_000
            ):
                raise ExportValidationError("knowledge_collection_checkpoint_invalid")
        else:
            if set(checkpoint) != {
                "kind",
                "issue_type_id",
                "first",
                "last",
                "next_cursor",
                "enumerated",
                "expected",
            }:
                raise ExportValidationError("knowledge_collection_checkpoint_invalid")
            try:
                identifier(checkpoint["issue_type_id"])
                first, last = (
                    date.fromisoformat(checkpoint["first"]),
                    date.fromisoformat(checkpoint["last"]),
                )
            except (TypeError, ValueError, ExportValidationError):
                raise ExportValidationError("knowledge_collection_checkpoint_invalid") from None
            if (
                first > last
                or type(checkpoint["enumerated"]) is not int
                or type(checkpoint["expected"]) is not int
                or not 1 <= checkpoint["enumerated"] <= checkpoint["expected"] < 1000
                or checkpoint["next_cursor"] is not None
                and (
                    not isinstance(checkpoint["next_cursor"], str)
                    or not 1 <= len(checkpoint["next_cursor"]) <= 512
                )
            ):
                raise ExportValidationError("knowledge_collection_checkpoint_invalid")
        with self.database.unit_of_work():
            for record in records:
                if record.document_kind != checkpoint["kind"]:
                    raise ExportValidationError("knowledge_collection_scope_changed")
                self.stage(run_id, record)
            run = self.run(run_id, lock=True)
            self.assert_configuration(run)
            if run["phase"] != "COLLECTING":
                raise ExportValidationError("knowledge_sync_phase_invalid")
            progress = {**run["checkpoint_json"], "collection_page": checkpoint}
            self.database.execute(
                f"update {self.t('sync_run')} set checkpoint_json=?,updated_at=? where id=?",
                (canonical_json(progress), now(), run_id),
            )

    def complete_collection(self, run_id: str, counts: dict[str, int]) -> dict[str, Any]:
        """仅完整枚举且旧项均再次被观察后允许进入分块阶段。"""
        if (
            set(counts) != {"defect", "ticket", "requirement"}
            or any(type(value) is not int or value < 0 for value in counts.values())
            or sum(counts.values()) > 200_000
        ):
            raise ExportValidationError("knowledge_collection_incomplete")
        with self.database.unit_of_work():
            run = self.run(run_id, lock=True)
            binding = self.assert_configuration(run)
            if run["phase"] != "COLLECTING" or not all(
                item.get("export_format") == "ones-online-full/v1"
                for item in run["manifest_json"].values()
            ):
                raise ExportValidationError("knowledge_sync_phase_invalid")
            project_ids = binding["configuration_json"]["collector"]["project_ids"]
            placeholders = ",".join("?" for _ in project_ids)
            missing = self.database.execute_one(
                f"select c.document_id from {self.t('sync_candidate')} c "
                f"join {self.t('document_revision')} r on r.id=c.baseline_revision_id "
                f"where c.run_id=? and c.record_hash is null and r.source_project_id in ({placeholders}) limit 1",
                (run_id, *project_ids),
            )
            if missing:
                raise ExportValidationError("knowledge_collection_visibility_shrank")
            manifests = dict(run["manifest_json"])
            for kind, expected in counts.items():
                imported = self.database.execute_one(
                    f"select processed_count from {self.t('import_run')} where id=?",
                    (stable_id("sync-import", run_id, kind),),
                )
                if not imported or imported["processed_count"] != expected:
                    raise ExportValidationError("knowledge_collection_incomplete")
                manifests[kind] = {**manifests[kind], "record_count": expected}
            progress = {**run["checkpoint_json"], "collection_complete": True}
            self.database.execute(
                f"update {self.t('sync_run')} set manifest_json=?,checkpoint_json=?,updated_at=? where id=?",
                (canonical_json(manifests), canonical_json(progress), now(), run_id),
            )
            return self.finish_staging(run_id)

    def finish_staging(self, run_id: str) -> dict[str, Any]:
        with self.database.unit_of_work():
            run = self.run(run_id, lock=True)
            self.assert_configuration(run)
            if (
                run["phase"] != "COLLECTING"
                or run["checkpoint_json"]["processed"] != run["checkpoint_json"]["total"]
                or (
                    any(
                        item.get("export_format") == "ones-online-full/v1"
                        for item in run["manifest_json"].values()
                    )
                    and run["checkpoint_json"].get("collection_complete") is not True
                )
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

    def apply_content(self, run_id: str) -> None:
        """仅供激活事务调用；候选之外的当前事实不提前变更。"""
        run = self.run(run_id, lock=True)
        if run["phase"] != "VERIFIED":
            raise ExportValidationError("knowledge_sync_phase_invalid")
        self.assert_baseline(run_id)
        content_changed = False
        for candidate in self.candidates(run_id):
            document_id = candidate["document_id"]
            if candidate["outcome"] in {"created", "revised"}:
                content_changed = True
                revision = self.revision(candidate["candidate_revision_id"])
                number = json_value(revision["source_snapshot"])["detail"]["number"]
                self.database.execute(
                    f"update {self.t('document')} set current_revision_id=?,document_kind=?,"
                    "lifecycle_state='active',source_observed_stamp_raw=?,external_number=?,last_seen_at=? where id=?",
                    (
                        candidate["candidate_revision_id"],
                        candidate["candidate_kind"],
                        candidate["observed_stamp"],
                        str(number),
                        now(),
                        document_id,
                    ),
                )
            elif candidate["outcome"] == "unchanged":
                self.database.execute(
                    f"update {self.t('document')} set source_observed_stamp_raw=?,last_seen_at=? where id=?",
                    (candidate["observed_stamp"], now(), document_id),
                )
            for base_id, state in candidate["candidate_members_json"].items():
                if candidate["baseline_members_json"].get(base_id) == state:
                    continue
                insert(
                    self.database,
                    "knowledge_base_document",
                    {
                        "knowledge_base_id": base_id,
                        "document_id": document_id,
                        "state": state,
                        "created_at": now(),
                    },
                    conflict="on conflict(knowledge_base_id,document_id) do update set state=excluded.state",
                )
        if content_changed:
            ImportRepository(self.database).resolve_targets(run["source_id"])

    def finish(self, run_id: str) -> None:
        self.database.execute(
            f"update {self.t('sync_run')} set phase='ACTIVATED',active=0,activated_watermark=?,"
            "error_code=NULL,updated_at=? where id=? and phase='VERIFIED'",
            (now(), now(), run_id),
        )

    def assert_same_content(self, records: ContentRepository) -> None:
        if not isinstance(records, GovernanceStore):
            raise ExportValidationError("knowledge_sync_content_location_mismatch")
        other = records.database
        if other is self.database:
            return
        if self.database.engine != "postgres" or other.engine != "postgres":
            raise ExportValidationError("knowledge_sync_content_location_mismatch")
        query = (
            "select (pg_control_system()).system_identifier::text as cluster_id, "
            "(select oid::text from pg_database where datname=current_database()) as database_id"
        )
        try:
            left, right = self.database.execute_one(query), other.execute_one(query)
        except Exception:
            raise ExportValidationError("knowledge_sync_content_location_unverified") from None
        if not left or left != right:
            raise ExportValidationError("knowledge_sync_content_location_mismatch")

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
