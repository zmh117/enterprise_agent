from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.cli import platformctl
from app.modules.cutover.service import LegacyPlatformCutoverService
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.migrations import Migrator
from backend.tests.helpers import container


ROOT = Path(__file__).resolve().parents[2]


def test_cutover_manifest_and_sql_have_one_exact_irreversible_drop_set() -> None:
    manifest = json.loads(
        (ROOT / "config/legacy-platform-retirement.json").read_text(encoding="utf-8")
    )
    sql = (ROOT / "backend/maintenance/legacy_platform_cutover.sql").read_text(encoding="utf-8")
    dropped = {
        match.group(1)
        for match in re.finditer(
            r"DROP\s+TABLE\s+IF\s+EXISTS\s+([a-z0-9_]+)\s+CASCADE",
            sql,
            re.IGNORECASE,
        )
    }
    dropped_columns = {
        (match.group(1), match.group(2))
        for match in re.finditer(
            r"ALTER\s+TABLE\s+([a-z0-9_]+)\s+"
            r"DROP\s+COLUMN\s+IF\s+EXISTS\s+([a-z0-9_]+)",
            sql,
            re.IGNORECASE,
        )
    }
    assert dropped == set(manifest["drop_tables"])
    assert dropped_columns == {
        (value["table"], value["column"]) for value in manifest["drop_columns"]
    }
    assert "agent_tool_call" in dropped
    assert not dropped.intersection(manifest["preserve_tables"])
    assert all(value is False for value in manifest["policy"].values())
    lowered = sql.lower()
    assert "pg_dump" not in lowered
    assert "\\copy" not in lowered
    assert "create table as" not in lowered
    assert "insert into" not in lowered
    assert "reverification_required" in lowered


def test_cutover_clean_is_blocked_outside_explicit_postgres_maintenance_mode() -> None:
    database = Database("sqlite:///:memory:")
    Migrator(database, default_migrations_dir(), migrator_build="cutover-test").run()
    try:
        service = LegacyPlatformCutoverService(database, destructive_enabled=False)
        check = service.check()
        assert check["ready"] is False
        assert check["checks"]["postgresql"] is False
        assert check["checks"]["destructive_mode_enabled"] is False
        with pytest.raises(NonRetryableExecutionError):
            service.clean(
                actor_id="nobody",
                manifest_hash=check["manifest_hash"],
                confirmation=check["confirmation_phrase"],
                entrances_stopped=True,
                workers_stopped=True,
                legacy_services_stopped=True,
            )
        assert database.execute_one("select count(*) as count from app_user")["count"] == 0
    finally:
        database.close()


def test_platformctl_cutover_clean_sends_all_explicit_assertions() -> None:
    captured = {}

    class Client:
        def request(self, path, *, method="GET", body=None):
            captured.update(path=path, method=method, body=body)
            return {"verified": True}

    args = SimpleNamespace(
        command="cutover",
        cutover_command="clean",
        manifest_hash="a" * 64,
        confirm="DELETE-LEGACY-PLATFORM-IRREVERSIBLY",
        entrances_stopped=True,
        workers_stopped=True,
        legacy_services_stopped=True,
    )
    assert platformctl.execute(args, Client()) == {"verified": True}
    assert captured == {
        "path": "/api/admin/cutover/clean",
        "method": "POST",
        "body": {
            "manifest_hash": "a" * 64,
            "confirmation": "DELETE-LEGACY-PLATFORM-IRREVERSIBLY",
            "entrances_stopped": True,
            "workers_stopped": True,
            "legacy_services_stopped": True,
        },
    }


def test_maintenance_rejects_new_jobs_but_preserves_idempotent_lookup() -> None:
    runtime = container()
    try:
        command = CreateAgentJobCommand(
            idempotency_key="cutover-existing-job",
            dingding_conversation_id="conversation-1",
            dingding_user_id="local-user",
            user_message="existing request",
        )
        existing = runtime.create_agent_job_service.execute(command)
        runtime.create_agent_job_service.accept_new_jobs = False
        assert runtime.create_agent_job_service.execute(command).id == existing.id

        with pytest.raises(NonRetryableExecutionError) as raised:
            runtime.create_agent_job_service.execute(
                CreateAgentJobCommand(
                    idempotency_key="cutover-new-job",
                    dingding_conversation_id="conversation-2",
                    dingding_user_id="local-user",
                    user_message="new request",
                )
            )
        assert raised.value.error_code == "job_ingress_maintenance"
    finally:
        runtime.database.close()
