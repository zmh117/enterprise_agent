from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.shared.database import Database


@dataclass(frozen=True)
class AttachmentBackfillReport:
    mode: str
    status: str
    scanned: int
    expiry_updates: int
    binding_inserts: int
    binding_column_repairs: int
    cleanup_fact_inserts: int
    unassociated_legacy: int
    blocking_count: int
    blocking_attachment_ids: tuple[str, ...]
    next_cursor: str
    has_more: bool
    object_io_performed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "status": self.status,
            "scanned": self.scanned,
            "expiry_updates": self.expiry_updates,
            "binding_inserts": self.binding_inserts,
            "binding_column_repairs": self.binding_column_repairs,
            "cleanup_fact_inserts": self.cleanup_fact_inserts,
            "unassociated_legacy": self.unassociated_legacy,
            "blocking_count": self.blocking_count,
            "blocking_attachment_ids": list(self.blocking_attachment_ids),
            "next_cursor": self.next_cursor,
            "has_more": self.has_more,
            "object_io_performed": self.object_io_performed,
        }


class AttachmentFileBackfill:
    """Database-only, resumable compatibility backfill for message attachments.

    It never reads, copies, or deletes object-storage content. Legacy objects that
    have not already crossed the File Service boundary remain intentionally
    unassociated and are reported for re-upload rather than being trusted as a
    managed file version.
    """

    def __init__(self, database: Database, *, now: datetime | None = None) -> None:
        self.database = database
        self.now = (now or datetime.now(UTC)).astimezone(UTC)

    def run(
        self,
        *,
        apply: bool = False,
        cursor: str = "",
        batch_size: int = 100,
        reconcile: bool = False,
    ) -> dict[str, object]:
        if not 1 <= batch_size <= 10_000:
            raise ValueError("batch_size must be between 1 and 10000")
        rows = self.database.execute(
            """
            select a.id, a.created_at, a.retention_days, a.expires_at,
                   a.managed_file_id, a.managed_file_version_id,
                   b.file_id as binding_file_id, b.version_id as binding_version_id,
                   b.retention_expires_at as binding_expires_at,
                   v.file_id as version_file_id,
                   case when c.id is null then 0 else 1 end as cleanup_exists
              from message_attachment a
              left join message_attachment_file_binding b on b.attachment_id = a.id
              left join managed_file_version v on v.id = coalesce(
                   nullif(a.managed_file_version_id, ''), b.version_id
              )
              left join file_cleanup_fact c
                on c.resource_type = 'ATTACHMENT_CONTENT'
               and c.resource_id = a.id
               and c.reason = 'RETENTION_EXPIRED'
             where a.id > ?
             order by a.id
             limit ?
            """,
            (cursor, batch_size + 1),
        )
        has_more = len(rows) > batch_size
        batch = rows[:batch_size]
        plans: list[dict[str, Any]] = []
        blockers: list[str] = []
        unassociated = 0
        for row in batch:
            plan, blocked, is_unassociated = self._plan(row)
            plans.append(plan)
            if blocked:
                blockers.append(str(row["id"]))
            if is_unassociated:
                unassociated += 1

        mode = "reconcile" if reconcile else ("apply" if apply else "dry-run")
        status = "blocked" if blockers else "ready"
        counters = {
            "expiry_updates": sum(int(plan["update_expiry"]) for plan in plans),
            "binding_inserts": sum(int(plan["insert_binding"]) for plan in plans),
            "binding_column_repairs": sum(int(plan["repair_columns"]) for plan in plans),
            "cleanup_fact_inserts": sum(int(plan["insert_cleanup"]) for plan in plans),
        }
        if apply and not reconcile and not blockers:
            with self.database.unit_of_work():
                for plan in plans:
                    self._apply(plan)
        report = AttachmentBackfillReport(
            mode=mode,
            status=status,
            scanned=len(batch),
            unassociated_legacy=unassociated,
            blocking_count=len(blockers),
            blocking_attachment_ids=tuple(blockers[:20]),
            next_cursor=str(batch[-1]["id"]) if batch else cursor,
            has_more=has_more,
            **counters,
        )
        return report.to_dict()

    def _plan(self, row: dict[str, Any]) -> tuple[dict[str, Any], bool, bool]:
        attachment_id = str(row["id"])
        expected_expiry = self._expiry(row)
        column_file = str(row.get("managed_file_id") or "")
        column_version = str(row.get("managed_file_version_id") or "")
        binding_file = str(row.get("binding_file_id") or "")
        binding_version = str(row.get("binding_version_id") or "")
        version_file = str(row.get("version_file_id") or "")
        effective_file = column_file or binding_file
        effective_version = column_version or binding_version
        partial = bool(effective_file) != bool(effective_version)
        disagreement = any(
            (
                column_file and binding_file and column_file != binding_file,
                column_version and binding_version and column_version != binding_version,
                effective_version and not version_file,
                effective_file and version_file and effective_file != version_file,
                bool(binding_file) != bool(binding_version),
            )
        )
        blocked = partial or disagreement
        unassociated = not effective_file and not effective_version
        plan = {
            "attachment_id": attachment_id,
            "expected_expiry": expected_expiry,
            "update_expiry": not str(row.get("expires_at") or ""),
            "insert_binding": bool(effective_file and effective_version and not binding_file),
            "repair_columns": bool(
                binding_file
                and binding_version
                and (not column_file or not column_version)
            ),
            "insert_cleanup": not bool(row.get("cleanup_exists")),
            "file_id": effective_file,
            "version_id": effective_version,
            "created_at": str(row["created_at"]),
        }
        binding_expiry = str(row.get("binding_expires_at") or "")
        if binding_expiry and binding_expiry != str(row.get("expires_at") or expected_expiry):
            blocked = True
        return plan, blocked, unassociated

    def _apply(self, plan: dict[str, Any]) -> None:
        attachment_id = str(plan["attachment_id"])
        expiry = str(plan["expected_expiry"])
        if plan["update_expiry"]:
            self.database.execute(
                "update message_attachment set expires_at = ? where id = ? and expires_at is null",
                (expiry, attachment_id),
            )
        if plan["insert_binding"]:
            self.database.execute(
                """
                insert into message_attachment_file_binding
                  (attachment_id, file_id, version_id, retention_expires_at, created_at)
                values (?, ?, ?, ?, ?)
                """,
                (
                    attachment_id,
                    plan["file_id"],
                    plan["version_id"],
                    expiry,
                    plan["created_at"],
                ),
            )
        if plan["repair_columns"]:
            self.database.execute(
                """
                update message_attachment
                   set managed_file_id = ?, managed_file_version_id = ?
                 where id = ?
                """,
                (plan["file_id"], plan["version_id"], attachment_id),
            )
        if plan["insert_cleanup"]:
            self.database.execute(
                """
                insert into file_cleanup_fact
                  (id, resource_type, resource_id, reason, status, due_at,
                   attempt_count, next_attempt_at, created_at, updated_at)
                values (?, 'ATTACHMENT_CONTENT', ?, 'RETENTION_EXPIRED',
                        'PENDING', ?, 0, ?, ?, ?)
                """,
                (
                    f"cleanup_attachment_{attachment_id}",
                    attachment_id,
                    expiry,
                    expiry,
                    self.now.isoformat(),
                    self.now.isoformat(),
                ),
            )

    @staticmethod
    def _expiry(row: dict[str, Any]) -> str:
        created = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        return (created.astimezone(UTC) + timedelta(days=int(row["retention_days"]))).isoformat()
