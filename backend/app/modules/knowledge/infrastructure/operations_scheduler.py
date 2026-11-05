"""一个调度进程串行领取采集计划；来源锁仍由既有同步流程持有。"""

from datetime import UTC, datetime, timedelta
import json
from typing import Any
from uuid import uuid4

from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.domain.operations import RETRYABLE
from app.modules.knowledge.infrastructure.incremental_repository import IncrementalSyncRepository
from app.modules.knowledge.infrastructure.chunk_repository import json_value
from app.modules.knowledge.infrastructure.operations_repository import OperationsRepository


class KnowledgeSyncScheduler:
    def __init__(self, operations: OperationsRepository):
        self.ops = operations
        self.db = operations.database
        self.sync = IncrementalSyncRepository(self.db)

    def select(self) -> dict[str, Any] | None:
        self._adopt_active()
        self._schedule_due()
        for operation in self.ops.waiting(sync=True):
            if operation["retry_at"] and datetime.fromisoformat(
                operation["retry_at"]
            ) > datetime.now(UTC):
                continue
            binding = self.sync.binding(operation["binding_id"])
            if (
                not binding["enabled"]
                or binding["configuration_revision"] != operation["parameters"]["binding_revision"]
            ):
                self.finish(operation, 1, "knowledge_sync_configuration_changed")
                continue
            active = self.sync.active_run(binding["id"])
            if active and operation["run_id"] != active["id"]:
                continue
            return operation
        return None

    def _adopt_active(self) -> None:
        rows = self.db.execute(
            f"select id,binding_id,manifest_json from {self.sync.t('sync_run')} where active=1 and incremental=1 order by created_at limit 100"
        )
        for row in rows:
            existing = self.db.execute_one(
                f"select id from {self.ops.t('ops_operation')} where run_id=? limit 1", (row["id"],)
            )
            if existing:
                continue
            binding = self.sync.binding(row["binding_id"])
            if not binding["enabled"]:
                continue
            manifest: dict[str, Any] = next(iter(json_value(row["manifest_json"]).values()), {})
            is_backfill = manifest.get("scan_mode") == "backfill"
            # begin_collection 提交后、任务关联前崩溃：接回原 RUNNING 操作，不能创建第二个任务。
            unlinked = self.db.execute_one(
                f"select id from {self.ops.t('ops_operation')} where binding_id=? and state='RUNNING' and run_id is null limit 1",
                (binding["id"],),
            )
            if unlinked:
                pending = self.ops.operation(unlinked["id"])
                expected = pending["kind"] == "backfill"
                if expected == is_backfill and (
                    not expected
                    or (pending["parameters"]["first_day"], pending["parameters"]["last_day"])
                    == (manifest.get("scan_first"), manifest.get("scan_last"))
                ):
                    self.ops.update(pending["id"], run_id=row["id"])
                    continue
            operation = self._enqueue(
                kind="backfill" if is_backfill else "sync",
                request_key="resume-" + row["id"],
                actor_id="system:knowledge-sync",
                binding_id=binding["id"],
                first_day=manifest.get("scan_first") if is_backfill else None,
                last_day=manifest.get("scan_last") if is_backfill else None,
                automatic=True,
            )
            if operation is None:
                break
            self.ops.update(operation["id"], run_id=row["id"])

    def _schedule_due(self) -> None:
        rows = self.db.execute(
            f"select id from {self.sync.t('sync_binding')} where enabled=1 and schedule_enabled=1 order by next_run_at,id limit 100"
        )
        for row in rows:
            if self.sync.active_run(row["id"]):
                continue
            pending = self.db.execute_one(
                f"select id from {self.ops.t('ops_operation')} where binding_id=? and state in ('QUEUED','RUNNING','RETRY_WAIT') limit 1",
                (row["id"],),
            )
            if not pending and self.sync.scheduled_due(row["id"], datetime.now(UTC)):
                operation = self._enqueue(
                    kind="sync",
                    request_key="scheduled-" + uuid4().hex,
                    actor_id="system:knowledge-sync",
                    binding_id=row["id"],
                    automatic=True,
                )
                if operation is None:
                    break

    def _enqueue(self, **values: Any) -> dict[str, Any] | None:
        try:
            return self.ops.submit(**values)
        except KnowledgeGovernanceError as exc:
            if exc.error_code == "knowledge_ops_queue_full":
                return None
            raise

    def command(self, operation: dict[str, Any], executable: str, capacity_path: str) -> list[str]:
        binding = self.sync.binding(operation["binding_id"])
        command = [
            executable,
            "-m",
            "app.cli.sync_ones_knowledge",
            "--mode",
            "once",
            "--binding-code",
            binding["code"],
            "--capacity-path",
            capacity_path,
            "--operation-id",
            operation["id"],
            "--commit",
        ]
        if operation["kind"] == "backfill":
            command += [
                "--from-date",
                operation["parameters"]["first_day"],
                "--through-date",
                operation["parameters"]["last_day"],
            ]
        return command

    def finish(self, operation: dict[str, Any], returncode: int, error_code: str | None) -> None:
        operation = self.ops.operation(operation["id"])
        run = self.sync.run(operation["run_id"]) if operation["run_id"] else None
        if run and run["phase"] == "ACTIVATED":
            state, error = "SUCCEEDED", None
        elif returncode == 0:
            state, error = "INTERRUPTED", "knowledge_sync_interrupted"
        elif error_code in RETRYABLE and operation["attempts"] < 3:
            retry = (datetime.now(UTC) + timedelta(seconds=60 * operation["attempts"])).isoformat()
            self.ops.update(
                operation["id"],
                state="RETRY_WAIT",
                stage="retry_pending",
                error_code=error_code,
                retry_at=retry,
            )
            self.ops.event(
                operation["id"],
                "sync",
                "retry_pending",
                {
                    "error_code": error_code or "knowledge_sync_failed",
                    "attempt": operation["attempts"],
                },
            )
            return
        else:
            state = "PARTIAL" if run and run["error_code"] == "knowledge_sync_partial" else "FAILED"
            error = error_code or (run["error_code"] if run else None) or "knowledge_sync_failed"
        self.ops.update(
            operation["id"],
            state=state,
            stage="completed" if state == "SUCCEEDED" else "failed",
            error_code=error,
        )
        self.ops.event(
            operation["id"],
            "sync",
            "completed" if state == "SUCCEEDED" else "failed",
            {"error_code": error or "none"},
        )
        interval = self.sync.binding(operation["binding_id"])["interval_seconds"]
        self.db.execute(
            f"update {self.sync.t('sync_binding')} set next_run_at=?,updated_at=? where id=?",
            (
                (datetime.now(UTC) + timedelta(seconds=interval)).isoformat(),
                now(),
                operation["binding_id"],
            ),
        )

    def observe(self, operation_id: str, line: str) -> str | None:
        try:
            event = json.loads(line)
        except (ValueError, RecursionError):
            return None
        if not isinstance(event, dict) or event.get("event") not in {
            "knowledge_sync_progress",
            "knowledge_sync_completed",
            "knowledge_sync_failed",
            "knowledge_sync_stopped",
            "knowledge_source_same_stamp_revised",
        }:
            return None
        self.ops.event(
            operation_id,
            "sync",
            "sync_progress" if event["event"] == "knowledge_sync_progress" else "sync_event",
            event,
        )
        code = event.get("error_code")
        return (
            code
            if isinstance(code, str)
            and code.startswith("knowledge_")
            and len(code) <= 160
            and code.replace("_", "").isalnum()
            else None
        )
