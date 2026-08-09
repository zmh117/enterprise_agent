from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError


_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST_PATH = _ROOT / "config" / "legacy-platform-retirement.json"
_SCRIPT_PATH = _ROOT / "backend" / "maintenance" / "legacy_platform_cutover.sql"
_TERMINAL_JOB_STATUSES = ("SUCCEEDED", "FAILED", "CANCELLED", "DEAD_LETTER")


class LegacyPlatformCutoverService:
    def __init__(self, database: Database, *, destructive_enabled: bool) -> None:
        self.database = database
        self.destructive_enabled = destructive_enabled

    def check(self) -> dict[str, Any]:
        manifest, manifest_hash, script_hash = self._artifacts()
        existing = self._existing_tables()
        existing_columns = self._existing_columns(existing)
        drop_tables = tuple(str(value) for value in manifest["drop_tables"])
        drop_columns = tuple(
            (str(value["table"]), str(value["column"])) for value in manifest["drop_columns"]
        )
        preserve_tables = tuple(str(value) for value in manifest["preserve_tables"])
        active_jobs = self._active_job_count(existing)
        policy = dict(manifest["policy"])
        policy_safe = all(policy.get(key) is False for key in policy)
        checks = {
            "postgresql": self.database.engine == "postgres",
            "destructive_mode_enabled": self.destructive_enabled,
            "no_active_jobs": active_jobs == 0,
            "policy_forbids_backup_export_transform": policy_safe,
            "preserved_tables_present": all(name in existing for name in preserve_tables),
            "legacy_objects_detected": any(name in existing for name in drop_tables)
            or any(value in existing_columns for value in drop_columns),
        }
        return {
            "ready": all(checks.values()),
            "checks": checks,
            "active_job_count": active_jobs,
            "manifest_hash": manifest_hash,
            "script_hash": script_hash,
            "drop_table_count": len(drop_tables),
            "detected_drop_table_count": sum(name in existing for name in drop_tables),
            "drop_column_count": len(drop_columns),
            "detected_drop_column_count": sum(value in existing_columns for value in drop_columns),
            "confirmation_phrase": manifest["confirmation_phrase"],
            "irreversible": True,
        }

    def clean(
        self,
        *,
        actor_id: str,
        manifest_hash: str,
        confirmation: str,
        entrances_stopped: bool,
        workers_stopped: bool,
        legacy_services_stopped: bool,
    ) -> dict[str, Any]:
        manifest, current_manifest_hash, script_hash = self._artifacts()
        before = self.check()
        if not before["ready"]:
            raise self._blocked("cutover_preconditions_failed")
        if manifest_hash != current_manifest_hash:
            raise self._blocked("cutover_manifest_changed")
        if confirmation != str(manifest["confirmation_phrase"]):
            raise self._blocked("cutover_confirmation_invalid")
        if not all((entrances_stopped, workers_stopped, legacy_services_stopped)):
            raise self._blocked("cutover_processes_not_stopped")
        script = _SCRIPT_PATH.read_text(encoding="utf-8")
        self.database.execute_script(script, ignore_existing_errors=False)
        self.database.execute(
            """
            insert into platform_cutover_record
              (id, manifest_hash, script_hash, actor_id, status, completed_at)
            values (?, ?, ?, ?, 'COMPLETED', ?)
            """,
            (
                f"platform_cutover_{uuid.uuid4().hex}",
                current_manifest_hash,
                script_hash,
                actor_id,
                datetime.now(UTC).isoformat(),
            ),
        )
        return self.verify()

    def verify(self) -> dict[str, Any]:
        manifest, manifest_hash, script_hash = self._artifacts()
        existing = self._existing_tables()
        existing_columns = self._existing_columns(existing)
        remaining = [str(name) for name in manifest["drop_tables"] if str(name) in existing]
        remaining_columns = [
            f"{value['table']}.{value['column']}"
            for value in manifest["drop_columns"]
            if (str(value["table"]), str(value["column"])) in existing_columns
        ]
        missing_preserved = [
            str(name) for name in manifest["preserve_tables"] if str(name) not in existing
        ]
        old_credentials = self._count_if_present(existing, "external_api_credential")
        old_challenges = self._count_if_present(existing, "external_api_verification_challenge")
        identity_violation = 0
        if "user_external_identity" in existing:
            row = self.database.execute_one(
                """
                select count(*) as count from user_external_identity
                 where provider = 'ones' and status <> 'REVERIFICATION_REQUIRED'
                """
            )
            identity_violation = int((row or {}).get("count") or 0)
        completed = self.database.execute_one(
            """
            select count(*) as count from platform_cutover_record
             where manifest_hash = ? and script_hash = ? and status = 'COMPLETED'
            """,
            (manifest_hash, script_hash),
        )
        verified = not any(
            (
                remaining,
                remaining_columns,
                missing_preserved,
                old_credentials,
                old_challenges,
                identity_violation,
                int((completed or {}).get("count") or 0) == 0,
            )
        )
        return {
            "verified": verified,
            "irreversible": True,
            "remaining_legacy_tables": remaining,
            "remaining_legacy_columns": remaining_columns,
            "missing_preserved_tables": missing_preserved,
            "old_credential_rows": old_credentials,
            "old_challenge_rows": old_challenges,
            "ones_identity_reverification_violations": identity_violation,
            "legacy_history_queryable": bool(remaining or remaining_columns),
        }

    def _artifacts(self) -> tuple[dict[str, Any], str, str]:
        manifest_raw = _MANIFEST_PATH.read_bytes()
        script_raw = _SCRIPT_PATH.read_bytes()
        manifest = json.loads(manifest_raw)
        if not isinstance(manifest, dict) or int(manifest.get("schema_version") or 0) != 2:
            raise self._blocked("cutover_manifest_invalid")
        return (
            manifest,
            hashlib.sha256(manifest_raw).hexdigest(),
            hashlib.sha256(script_raw).hexdigest(),
        )

    def _existing_tables(self) -> set[str]:
        if self.database.engine == "postgres":
            rows = self.database.execute(
                """
                select table_name from information_schema.tables
                 where table_schema = current_schema() and table_type = 'BASE TABLE'
                """
            )
        else:
            rows = self.database.execute(
                "select name as table_name from sqlite_master where type = 'table'"
            )
        return {str(row["table_name"]) for row in rows}

    def _active_job_count(self, existing: set[str]) -> int:
        if "agent_job" not in existing:
            return 0
        placeholders = ",".join("?" for _ in _TERMINAL_JOB_STATUSES)
        row = self.database.execute_one(
            f"select count(*) as count from agent_job where status not in ({placeholders})",
            _TERMINAL_JOB_STATUSES,
        )
        return int((row or {}).get("count") or 0)

    def _existing_columns(self, existing_tables: set[str]) -> set[tuple[str, str]]:
        if self.database.engine == "postgres":
            rows = self.database.execute(
                """
                select table_name, column_name from information_schema.columns
                 where table_schema = current_schema()
                """
            )
            return {(str(row["table_name"]), str(row["column_name"])) for row in rows}
        columns: set[tuple[str, str]] = set()
        for table in existing_tables:
            if not table.replace("_", "").isalnum():
                continue
            for row in self.database.execute(f'pragma table_info("{table}")'):
                columns.add((table, str(row["name"])))
        return columns

    def _count_if_present(self, existing: set[str], table: str) -> int:
        if table not in existing:
            return 0
        row = self.database.execute_one(f"select count(*) as count from {table}")
        return int((row or {}).get("count") or 0)

    @staticmethod
    def _blocked(code: str) -> NonRetryableExecutionError:
        return NonRetryableExecutionError(
            "Legacy platform destructive cutover is blocked",
            safe_message="破坏性切换前置条件未满足",
            error_code=code,
        )
