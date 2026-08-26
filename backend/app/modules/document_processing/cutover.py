from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.modules.document_processing.profile import DOCLING_LAYOUT_OCR_V2
from app.shared.database import Database


PARENT_NON_TERMINAL = ("QUEUED", "SUBMITTED", "RUNNING", "RETRY_WAIT")
PICTURE_NON_TERMINAL = ("QUEUED", "CLAIMED", "SUBMITTED")


class DoclingProfileCutoverPreflight:
    """Read-only old-Profile drain gate with count-only output."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def run(self) -> dict[str, Any]:
        if not self._table_exists("file_processing_run"):
            return self._report(parent={}, picture={}, external_tasks=0, schema_present=False)
        parent = self._grouped_parent_counts()
        picture = (
            self._grouped_picture_counts()
            if self._table_exists("document_picture_processing_item")
            else {}
        )
        external_tasks = self._external_task_count(
            include_picture=self._table_exists("document_picture_processing_item")
        )
        return self._report(
            parent=parent,
            picture=picture,
            external_tasks=external_tasks,
            schema_present=True,
        )

    def _grouped_parent_counts(self) -> dict[str, int]:
        rows = self.database.execute(
            """
            select status, count(*) as count
              from file_processing_run
             where profile_code = 'docling-layout-ocr-v2'
               and profile_hash <> ?
               and status in ('QUEUED', 'SUBMITTED', 'RUNNING', 'RETRY_WAIT')
             group by status order by status
            """,
            (DOCLING_LAYOUT_OCR_V2.profile_hash,),
        )
        return {str(row["status"]): int(row["count"]) for row in rows}

    def _grouped_picture_counts(self) -> dict[str, int]:
        rows = self.database.execute(
            """
            select i.status, count(*) as count
              from document_picture_processing_item i
              join file_processing_run r on r.id = i.processing_run_id
             where r.profile_code = 'docling-layout-ocr-v2'
               and r.profile_hash <> ?
               and i.status in ('QUEUED', 'CLAIMED', 'SUBMITTED')
             group by i.status order by i.status
            """,
            (DOCLING_LAYOUT_OCR_V2.profile_hash,),
        )
        return {str(row["status"]): int(row["count"]) for row in rows}

    def _external_task_count(self, *, include_picture: bool) -> int:
        parent = self.database.execute_one(
            """
            select count(*) as count from file_processing_run
             where profile_code = 'docling-layout-ocr-v2'
               and profile_hash <> ?
               and status in ('QUEUED', 'SUBMITTED', 'RUNNING', 'RETRY_WAIT')
               and external_task_id <> ''
            """,
            (DOCLING_LAYOUT_OCR_V2.profile_hash,),
        )
        picture_count = 0
        if include_picture:
            picture = self.database.execute_one(
                """
                select count(*) as count
                  from document_picture_processing_item i
                  join file_processing_run r on r.id = i.processing_run_id
                 where r.profile_code = 'docling-layout-ocr-v2'
                   and r.profile_hash <> ?
                   and i.status in ('QUEUED', 'CLAIMED', 'SUBMITTED')
                   and i.external_task_id <> ''
                """,
                (DOCLING_LAYOUT_OCR_V2.profile_hash,),
            )
            picture_count = int((picture or {}).get("count") or 0)
        return int((parent or {}).get("count") or 0) + picture_count

    def _table_exists(self, table: str) -> bool:
        if self.database.engine == "postgres":
            row = self.database.execute_one("select to_regclass(?) as name", (table,))
            return bool((row or {}).get("name"))
        row = self.database.execute_one(
            "select name from sqlite_master where type = 'table' and name = ?",
            (table,),
        )
        return row is not None

    @staticmethod
    def _report(
        *,
        parent: dict[str, int],
        picture: dict[str, int],
        external_tasks: int,
        schema_present: bool,
    ) -> dict[str, Any]:
        parent_total = sum(parent.values())
        picture_total = sum(picture.values())
        ready = parent_total == 0 and picture_total == 0 and external_tasks == 0
        return {
            "status": "ready" if ready else "blocked",
            "reason_code": "ready" if ready else "old_profile_processing_not_drained",
            "schema_present": schema_present,
            "current_profile_hash": DOCLING_LAYOUT_OCR_V2.profile_hash,
            "parent_non_terminal": parent,
            "parent_non_terminal_total": parent_total,
            "picture_non_terminal": picture,
            "picture_non_terminal_total": picture_total,
            "external_task_bindings": external_tasks,
        }


class DoclingQuarantineRecovery:
    """Release quarantined slots only after workers stopped and Docling reset."""

    def __init__(self, database: Database, *, now: datetime | None = None) -> None:
        self.database = database
        self.now = now or datetime.now(UTC)

    def run(self, *, docling_restarted: bool) -> dict[str, Any]:
        slot_schema_present = self._table_exists("document_processing_docling_slot")
        if not docling_restarted:
            return {
                "status": "blocked",
                "reason_code": "docling_restart_not_confirmed",
                "active_workers": 0,
                "quarantined_slots": self._quarantined_count(),
                "recovered_slots": 0,
            }
        if not slot_schema_present:
            return {
                "status": "recovered",
                "reason_code": "ready",
                "active_workers": 0,
                "quarantined_slots": 0,
                "recovered_slots": 0,
            }
        active_workers = self._active_worker_count()
        quarantined = self._quarantined_count()
        if active_workers:
            return {
                "status": "blocked",
                "reason_code": "file_processing_workers_still_active",
                "active_workers": active_workers,
                "quarantined_slots": quarantined,
                "recovered_slots": 0,
            }
        with self.database.unit_of_work():
            recovered = self.database.execute(
                """
                update document_processing_docling_slot
                   set state = 'AVAILABLE', owner_kind = '', owner_id = '',
                       worker_instance_id = '', lease_expires_at = null,
                       reason_code = '', acquired_at = null, updated_at = ?
                 where state = 'QUARANTINED'
                returning slot_no
                """,
                (self.now.isoformat(),),
            )
        return {
            "status": "recovered",
            "reason_code": "ready",
            "active_workers": 0,
            "quarantined_slots": quarantined,
            "recovered_slots": len(recovered),
        }

    def _active_worker_count(self) -> int:
        if not self._table_exists("file_processing_worker_heartbeat"):
            return 0
        row = self.database.execute_one(
            """
            select count(*) as count from file_processing_worker_heartbeat
             where expires_at > ?
            """,
            (self.now.isoformat(),),
        )
        return int((row or {}).get("count") or 0)

    def _quarantined_count(self) -> int:
        if not self._table_exists("document_processing_docling_slot"):
            return 0
        row = self.database.execute_one(
            """
            select count(*) as count from document_processing_docling_slot
             where state = 'QUARANTINED'
            """
        )
        return int((row or {}).get("count") or 0)

    def _table_exists(self, table: str) -> bool:
        if self.database.engine == "postgres":
            row = self.database.execute_one("select to_regclass(?) as name", (table,))
            return bool((row or {}).get("name"))
        row = self.database.execute_one(
            "select name from sqlite_master where type = 'table' and name = ?",
            (table,),
        )
        return row is not None
