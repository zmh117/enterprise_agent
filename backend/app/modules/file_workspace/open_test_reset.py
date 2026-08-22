from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError


CONFIRMATION = "DELETE-OPEN-TEST-FILE-DOMAIN"
_ROOT_TABLES = ("agent_job", "task_workspace", "managed_file", "message_attachment")
_NON_TERMINAL_CHECKS = {
    "agent_jobs": (
        "agent_job",
        "status in ('WAITING_INPUT', 'PENDING', 'RUNNING', 'RETRY_WAIT')",
    ),
    "deliveries": (
        "delivery_outbox",
        "status in ('PENDING', 'RUNNING', 'RETRY_WAIT')",
    ),
    "processing_runs": (
        "file_processing_run",
        "status in ('QUEUED', 'SUBMITTED', 'RUNNING', 'RETRY_WAIT')",
    ),
    "processing_stage_outbox": (
        "document_processing_stage_outbox",
        "status in ('PENDING', 'CLAIMED')",
    ),
    "file_domain_outbox": (
        "file_domain_outbox",
        "status = 'PENDING'",
    ),
    "cleanup_work": (
        "file_cleanup_fact",
        "status in ('PENDING', 'CLAIMED', 'RETRY')",
    ),
}


class ManagedObjectStorage(Protocol):
    def list_keys(self) -> list[str]: ...

    def delete(self, *, internal_object_key: str) -> None: ...


class OpenTestFileDomainResetService:
    """Destructive, explicitly confirmed reset for non-production test facts.

    The service deletes only the File Service-owned ``managed/`` namespace and
    database rows that reference one of the four file/job roots. It never reads
    or prints file content, credentials, object keys, messages, or identifiers.
    """

    def __init__(
        self,
        database: Database,
        storage: ManagedObjectStorage,
        legacy_attachment_storage: ManagedObjectStorage,
    ) -> None:
        self.database = database
        self.storage = storage
        self.legacy_attachment_storage = legacy_attachment_storage

    def report(self) -> dict[str, Any]:
        tables = self._reset_tables()
        table_counts = {
            table: self._count(table)
            for table in sorted(tables)
        }
        current_keys = self.storage.list_keys()
        legacy_keys = self.legacy_attachment_storage.list_keys()
        blockers = {
            name: self._conditional_count(table, predicate)
            for name, (table, predicate) in _NON_TERMINAL_CHECKS.items()
        }
        inventory = {
            "schema_head": self._schema_head(),
            "table_counts": table_counts,
            "managed_object_count": len(current_keys),
            "legacy_managed_object_count": len(legacy_keys),
            "managed_object_digest": self._object_digest(current_keys, legacy_keys),
            "blockers": blockers,
        }
        digest = hashlib.sha256(self._canonical(inventory).encode("utf-8")).hexdigest()
        return {
            **inventory,
            "inventory_digest": digest,
            "required_confirmation": CONFIRMATION,
            "ready": not any(blockers.values()),
        }

    def apply(self, *, expected_digest: str, confirmation: str) -> dict[str, Any]:
        if confirmation != CONFIRMATION:
            self._deny("open_test_reset_confirmation_invalid", "重置确认文本不匹配")
        before = self.report()
        if expected_digest != before["inventory_digest"]:
            self._deny("open_test_reset_inventory_changed", "重置清单已变化，请重新预检")
        if not before["ready"]:
            self._deny("open_test_reset_not_drained", "仍有非终态任务或待发布事件，拒绝重置")

        current_keys = self.storage.list_keys()
        legacy_keys = self.legacy_attachment_storage.list_keys()
        for key in current_keys:
            self.storage.delete(internal_object_key=key)
        for key in legacy_keys:
            self.legacy_attachment_storage.delete(internal_object_key=key)

        if self.database.engine == "postgres":
            self.database.execute(
                "truncate table agent_job, task_workspace, managed_file, "
                "message_attachment cascade"
            )
        else:
            tables = self._reset_tables()
            self.database.execute("pragma foreign_keys = off")
            try:
                with self.database.unit_of_work():
                    for table in sorted(tables):
                        self.database.execute(f'delete from "{table}"')
            finally:
                self.database.execute("pragma foreign_keys = on")
            if self.database.execute("pragma foreign_key_check"):
                self._deny(
                    "open_test_reset_foreign_key_check_failed",
                    "文件域重置后数据库引用不完整",
                )

        after = self.report()
        remaining_rows = sum(after["table_counts"].values())
        if (
            remaining_rows
            or after["managed_object_count"]
            or after["legacy_managed_object_count"]
        ):
            self._deny("open_test_reset_incomplete", "文件域重置未完整清空")
        return {
            "status": "APPLIED",
            "deleted_database_rows": sum(before["table_counts"].values()),
            "deleted_managed_objects": (
                before["managed_object_count"] + before["legacy_managed_object_count"]
            ),
            "verification_digest": after["inventory_digest"],
        }

    def _reset_tables(self) -> set[str]:
        edges = self._foreign_key_edges()
        tables = set(_ROOT_TABLES)
        changed = True
        while changed:
            changed = False
            for child, parent in edges:
                if parent in tables and child not in tables:
                    tables.add(child)
                    changed = True
        return tables

    def _foreign_key_edges(self) -> set[tuple[str, str]]:
        if self.database.engine == "postgres":
            rows = self.database.execute(
                """
                select tc.table_name as child, ccu.table_name as parent
                  from information_schema.table_constraints tc
                  join information_schema.constraint_column_usage ccu
                    on ccu.constraint_name = tc.constraint_name
                   and ccu.constraint_schema = tc.constraint_schema
                 where tc.constraint_type = 'FOREIGN KEY'
                   and tc.table_schema = current_schema()
                """
            )
            return {(str(row["child"]), str(row["parent"])) for row in rows}
        tables = [
            str(row["name"])
            for row in self.database.execute(
                "select name from sqlite_master where type = 'table' and name not like 'sqlite_%'"
            )
        ]
        edges: set[tuple[str, str]] = set()
        for table in tables:
            for row in self.database.execute(f'pragma foreign_key_list("{table}")'):
                edges.add((table, str(row["table"])))
        return edges

    def _conditional_count(self, table: str, predicate: str) -> int:
        if table not in self._table_names():
            return 0
        row = self.database.execute_one(
            f'select count(*) as value from "{table}" where {predicate}'
        )
        return int((row or {}).get("value") or 0)

    def _count(self, table: str) -> int:
        row = self.database.execute_one(f'select count(*) as value from "{table}"')
        return int((row or {}).get("value") or 0)

    def _table_names(self) -> set[str]:
        if self.database.engine == "postgres":
            rows = self.database.execute(
                "select table_name as name from information_schema.tables "
                "where table_schema = current_schema()"
            )
        else:
            rows = self.database.execute(
                "select name from sqlite_master where type = 'table' and name not like 'sqlite_%'"
            )
        return {str(row["name"]) for row in rows}

    def _schema_head(self) -> str:
        row = self.database.execute_one(
            "select version from schema_migration order by version desc limit 1"
        )
        return str((row or {}).get("version") or "")

    @staticmethod
    def _object_digest(current_keys: list[str], legacy_keys: list[str]) -> str:
        identities = [*(f"current:{key}" for key in current_keys)]
        identities.extend(f"legacy:{key}" for key in legacy_keys)
        return hashlib.sha256("\n".join(sorted(identities)).encode("utf-8")).hexdigest()

    @staticmethod
    def _canonical(value: object) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _deny(code: str, message: str) -> None:
        raise NonRetryableExecutionError(
            "Open-test file-domain reset rejected",
            safe_message=message,
            error_code=code,
        )
