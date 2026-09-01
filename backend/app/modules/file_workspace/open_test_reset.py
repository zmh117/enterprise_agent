from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError


CONFIRMATION = "DELETE-OPEN-TEST-FILE-DOMAIN"
_ROOT_TABLES = (
    "agent_job",
    "task_workspace",
    "managed_file",
    "message_attachment",
    # Polymorphic resource references have no database foreign key, so the
    # topology walk cannot discover them from the file-domain roots.
    "file_cleanup_fact",
    "file_domain_outbox",
)
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
        "status = 'CLAIMED'",
    ),
}
_CURRENT_AGENT_PUBLICATION_SCHEMA_VERSION = 3
_CURRENT_AGENT_RUNTIME_KIND = "python-v1"
_CURRENT_AGENT_RUNTIME_PROTOCOL_VERSIONS = ["1.5"]
_CURRENT_APPLICATION_PUBLICATION_SCHEMA_VERSION = 6
_CURRENT_DOCUMENT_PROCESSING_PROFILES = frozenset({"NONE", "docling-layout-ocr-v2"})


class ManagedObjectStorage(Protocol):
    def list_keys(self) -> list[str]: ...

    def delete(self, *, internal_object_key: str) -> None: ...


class OpenTestFileDomainResetService:
    """Destructive, explicitly confirmed reset for non-production test facts.

    The service deletes the File Service-owned object namespaces, database rows
    rooted in open-test file/Job facts, and configuration facts that violate the
    one current runtime/document contract. It never reads or prints file content,
    credentials, object keys, messages, or identifiers.
    """

    def __init__(
        self,
        database: Database,
        storage: ManagedObjectStorage,
    ) -> None:
        self.database = database
        self.storage = storage

    def report(self) -> dict[str, Any]:
        tables = self._reset_tables()
        table_counts = {table: self._count(table) for table in sorted(tables)}
        current_keys = self.storage.list_keys()
        blockers = {
            name: self._conditional_count(table, predicate)
            for name, (table, predicate) in _NON_TERMINAL_CHECKS.items()
        }
        contract_inventory = self._legacy_contract_inventory()
        legacy_contract_counts = {
            name: len(identifiers) for name, identifiers in contract_inventory.items()
        }
        inventory = {
            "schema_head": self._schema_head(),
            "table_counts": table_counts,
            "managed_object_count": len(current_keys),
            "managed_object_digest": self._object_digest(current_keys),
            "blockers": blockers,
            "legacy_contract_counts": legacy_contract_counts,
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
        for key in current_keys:
            self.storage.delete(internal_object_key=key)

        self._clear_database_rows()
        self._delete_legacy_contract_configuration()

        after = self.report()
        remaining_rows = sum(after["table_counts"].values())
        remaining_legacy_contracts = sum(after["legacy_contract_counts"].values())
        if remaining_rows or remaining_legacy_contracts or after["managed_object_count"]:
            self._deny("open_test_reset_incomplete", "文件域重置未完整清空")
        return {
            "status": "APPLIED",
            "deleted_database_rows": sum(before["table_counts"].values()),
            "deleted_legacy_contract_rows": sum(before["legacy_contract_counts"].values()),
            "deleted_managed_objects": before["managed_object_count"],
            "verification_digest": after["inventory_digest"],
        }

    def _clear_database_rows(self) -> None:
        tables = self._reset_tables()
        if self.database.engine == "postgres":
            quoted_tables = ", ".join(f'"{table}"' for table in sorted(tables))
            self.database.execute(f"truncate table {quoted_tables} cascade")
        else:
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

    def _delete_legacy_contract_configuration(self) -> None:
        inventory = self._legacy_contract_inventory()
        application_publication_ids = inventory["application_publications"]
        application_revision_ids = inventory["application_revisions"]
        agent_publication_ids = inventory["agent_publications"]
        agent_definition_ids = inventory["agent_definitions"]

        with self.database.unit_of_work():
            for table, column in (
                ("business_application_active_route", "publication_id"),
                ("business_application_deployment", "publication_id"),
                (
                    "business_application_publication_mcp_tool",
                    "application_publication_id",
                ),
            ):
                self._delete_rows_by_ids(
                    table,
                    column,
                    application_publication_ids,
                )
            self._delete_rows_by_ids(
                "business_application_publication",
                "id",
                application_publication_ids,
            )

            for table, column in (
                ("business_application_revision_delivery", "revision_id"),
                ("business_application_revision_trigger", "revision_id"),
                ("business_application_revision_mcp_tool", "application_revision_id"),
            ):
                self._delete_rows_by_ids(table, column, application_revision_ids)
            self._delete_rows_by_ids(
                "business_application_revision",
                "id",
                application_revision_ids,
            )

            for table, column in (
                ("agent_channel_binding", "publication_id"),
                ("agent_publication_mcp_tool", "agent_publication_id"),
                ("agent_skill_binding", "publication_id"),
                ("webhook_trigger_publication", "agent_publication_id"),
                ("business_application_revision_mcp_tool", "agent_publication_id"),
                ("business_application_publication_mcp_tool", "agent_publication_id"),
            ):
                self._delete_rows_by_ids(table, column, agent_publication_ids)
            self._update_rows_by_ids(
                "agent_definition",
                "current_publication_id",
                agent_publication_ids,
                assignment="current_publication_id = null",
            )
            self._delete_rows_by_ids(
                "agent_publication",
                "id",
                agent_publication_ids,
            )
            self._delete_rows_by_ids(
                "agent_revision",
                "agent_id",
                agent_definition_ids,
            )
            self._delete_rows_by_ids(
                "agent_definition",
                "id",
                agent_definition_ids,
            )

    def _legacy_contract_inventory(self) -> dict[str, tuple[str, ...]]:
        definition_rows = self.database.execute("select id, runtime_kind from agent_definition")
        old_definition_ids = {
            str(row["id"])
            for row in definition_rows
            if str(row.get("runtime_kind") or "") != _CURRENT_AGENT_RUNTIME_KIND
        }

        publication_rows = self.database.execute(
            """
            select p.id, p.schema_version, p.runtime_kind, p.snapshot_json,
                   p.config_hash, a.runtime_kind as definition_runtime_kind
              from agent_publication p
              join agent_definition a on a.id = p.agent_id
            """
        )
        old_publication_ids = {
            str(row["id"])
            for row in publication_rows
            if not self._is_current_agent_publication(row)
        }

        revision_rows = self.database.execute(
            """
            select id, agent_publication_id, document_processing_profile_code
              from business_application_revision
            """
        )
        old_revision_ids = {
            str(row["id"])
            for row in revision_rows
            if str(row.get("document_processing_profile_code") or "")
            not in _CURRENT_DOCUMENT_PROCESSING_PROFILES
            or str(row.get("agent_publication_id") or "") in old_publication_ids
        }

        application_publication_rows = self.database.execute(
            """
            select id, revision_id, schema_version,
                   document_processing_profile_code
              from business_application_publication
            """
        )
        old_application_publication_ids = {
            str(row["id"])
            for row in application_publication_rows
            if int(row.get("schema_version") or 0)
            != _CURRENT_APPLICATION_PUBLICATION_SCHEMA_VERSION
            or str(row.get("document_processing_profile_code") or "")
            not in _CURRENT_DOCUMENT_PROCESSING_PROFILES
            or str(row.get("revision_id") or "") in old_revision_ids
        }
        return {
            "agent_definitions": tuple(sorted(old_definition_ids)),
            "agent_publications": tuple(sorted(old_publication_ids)),
            "application_revisions": tuple(sorted(old_revision_ids)),
            "application_publications": tuple(sorted(old_application_publication_ids)),
        }

    @classmethod
    def _is_current_agent_publication(cls, row: dict[str, Any]) -> bool:
        try:
            snapshot = json.loads(str(row.get("snapshot_json") or ""))
        except (TypeError, json.JSONDecodeError):
            return False
        if not isinstance(snapshot, dict):
            return False
        expected_hash = hashlib.sha256(cls._canonical(snapshot).encode("utf-8")).hexdigest()
        return (
            int(row.get("schema_version") or 0) == _CURRENT_AGENT_PUBLICATION_SCHEMA_VERSION
            and str(row.get("runtime_kind") or "") == _CURRENT_AGENT_RUNTIME_KIND
            and str(row.get("definition_runtime_kind") or "") == _CURRENT_AGENT_RUNTIME_KIND
            and snapshot.get("runtime_kind") == _CURRENT_AGENT_RUNTIME_KIND
            and snapshot.get("supported_runtime_protocol_versions")
            == _CURRENT_AGENT_RUNTIME_PROTOCOL_VERSIONS
            and str(row.get("config_hash") or "") == expected_hash
        )

    def _delete_rows_by_ids(
        self,
        table: str,
        column: str,
        identifiers: tuple[str, ...],
    ) -> None:
        if not identifiers:
            return
        placeholders = ", ".join("?" for _ in identifiers)
        self.database.execute(
            f'delete from "{table}" where "{column}" in ({placeholders})',
            identifiers,
        )

    def _update_rows_by_ids(
        self,
        table: str,
        column: str,
        identifiers: tuple[str, ...],
        *,
        assignment: str,
    ) -> None:
        if not identifiers:
            return
        placeholders = ", ".join("?" for _ in identifiers)
        self.database.execute(
            f'update "{table}" set {assignment} where "{column}" in ({placeholders})',
            identifiers,
        )

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
    def _object_digest(current_keys: list[str]) -> str:
        return hashlib.sha256("\n".join(sorted(current_keys)).encode("utf-8")).hexdigest()

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
