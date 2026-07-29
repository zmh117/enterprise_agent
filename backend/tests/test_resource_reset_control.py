from __future__ import annotations

import pytest

from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
)
from app.modules.job.domain.job_status import JobStatus
from app.modules.platform_config.application.resource_reset import (
    ResourceResetService,
)
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import (
    enqueue_job_result_for_delivery,
)
from backend.tests.test_runtime_generation_reload import (
    _generation_runtime,
)
from scripts.runtime_foundation_gate import manifest_digest


def test_resource_reset_report_is_exact_read_only_and_secret_safe() -> None:
    runtime, _platform, reloader, publication, revision = (
        _generation_runtime()
    )
    try:
        reloader.poll_once(force=True)
        before_operations = _count(
            runtime,
            "resource_reset_operation",
        )
        report = ResourceResetService(runtime.database).report()
        assert report["targets"]
        assert report["counts"]["resource"] == 1
        assert report["counts"]["revision"] == 1
        assert report["counts"]["handler_resource_binding"] == 1
        assert report["counts"]["resource_runtime_state"] == 1
        assert report["counts"]["application_runtime_state"] == 1
        assert report["affected_applications"] == [
            {
                "application_publication_id": str(
                    publication["id"]
                ),
                "application_id": str(
                    publication["application_id"]
                ),
                "application_code": "governed-execution-scope",
                "expected_status": "BLOCKED",
            }
        ]
        assert any(
            target["id"] == str(revision["id"])
            and target["type"] == "revision"
            for target in report["targets"]
        )
        assert (
            _count(runtime, "resource_reset_operation")
            == before_operations
        )
        serialized = str(report)
        assert "governed-scope-password" not in serialized
        assert "config_json" not in serialized
        assert "secret_refs_json" not in serialized
    finally:
        runtime.database.close()


def test_prepare_enters_maintenance_and_manifest_matches_gate_digest() -> None:
    runtime, _platform, reloader, publication, revision = (
        _generation_runtime()
    )
    try:
        reloader.poll_once(force=True)
        service = ResourceResetService(runtime.database)
        prepared = service.prepare(
            actor_id="user_local_admin",
            backup_reference="test-backup://resource-reset/001",
            correlation_id="reset-prepare-test",
            drain_timeout_seconds=0,
        )
        manifest = prepared["manifest"]
        digest, _canonical = manifest_digest(manifest)
        assert digest == prepared["digest"]
        operation = runtime.database.execute_one(
            """
            select * from resource_reset_operation
             where id = ?
            """,
            (manifest["operation_id"],),
        )
        assert operation is not None
        assert operation["status"] == "PREPARED"
        assert operation["inventory_digest"] == digest

        with pytest.raises(
            NonRetryableExecutionError,
            match="maintenance",
        ):
            runtime.create_agent_job_service.execute(
                CreateAgentJobCommand(
                    idempotency_key="reset-maintenance-job",
                    user_message="不应创建",
                    requester_id="user_local_admin",
                    business_application_publication_id=str(
                        publication["id"]
                    ),
                )
            )
        with pytest.raises(
            NonRetryableExecutionError,
            match="maintenance mode",
        ):
            (
                runtime.platform_config_service.governed_resources
                .create_draft_from_revision(
                    "governed_scope_mysql",
                    str(revision["id"]),
                    actor_id="local-user",
                )
            )
    finally:
        runtime.database.close()


def test_prepare_aborts_instead_of_killing_active_resource_job() -> None:
    runtime, _platform, reloader, publication, revision = (
        _generation_runtime()
    )
    try:
        reloader.poll_once(force=True)
        job = _historical_job(runtime)
        _pin_resource_history(
            runtime,
            job_id=job.id,
            publication=publication,
            resource_revision_id=str(revision["id"]),
        )
        runtime.database.execute(
            "update agent_job set status = 'RUNNING' where id = ?",
            (job.id,),
        )
        with pytest.raises(
            NonRetryableExecutionError,
            match="did not drain",
        ):
            ResourceResetService(runtime.database).prepare(
                actor_id="user_local_admin",
                backup_reference="test-backup://resource-reset/active",
                drain_timeout_seconds=0,
            )
        operation = runtime.database.execute_one(
            """
            select status, error_code
              from resource_reset_operation
             order by created_at desc
             limit 1
            """
        )
        assert operation == {
            "status": "ABORTED",
            "error_code": "resource_jobs_not_drained",
        }
        assert runtime.agent_repository.get_job(job.id).status is (
            JobStatus.RUNNING
        )
    finally:
        runtime.database.close()


def test_apply_rejects_post_prepare_change_without_deleting_resources() -> None:
    runtime, _platform, reloader, _publication, _revision = (
        _generation_runtime()
    )
    try:
        reloader.poll_once(force=True)
        service = ResourceResetService(runtime.database)
        prepared = service.prepare(
            actor_id="user_local_admin",
            backup_reference="test-backup://resource-reset/drift",
            drain_timeout_seconds=0,
        )
        resource = runtime.database.execute_one(
            "select id from platform_resource limit 1"
        )
        assert resource is not None
        runtime.database.execute(
            """
            update platform_resource
               set revision = revision + 1
             where id = ?
            """,
            (resource["id"],),
        )
        with pytest.raises(
            NonRetryableExecutionError,
            match="inventory changed",
        ):
            service.apply(
                operation_id=prepared["manifest"]["operation_id"],
                expected_digest=prepared["digest"],
                confirmed_by="user_local_admin",
            )
        assert _count(runtime, "platform_resource") == 1
        operation = runtime.database.execute_one(
            """
            select status from resource_reset_operation
             where id = ?
            """,
            (prepared["manifest"]["operation_id"],),
        )
        assert operation == {"status": "ABORTED"}
    finally:
        runtime.database.close()


def test_apply_database_failure_rolls_back_all_deletes(
    monkeypatch,
) -> None:
    runtime, _platform, reloader, _publication, _revision = (
        _generation_runtime()
    )
    try:
        reloader.poll_once(force=True)
        service = ResourceResetService(runtime.database)
        prepared = service.prepare(
            actor_id="user_local_admin",
            backup_reference="test-backup://resource-reset/rollback",
            drain_timeout_seconds=0,
        )
        original_execute = runtime.database.execute

        def fail_revision_delete(sql, params=()):
            if "delete from platform_resource_revision" in sql:
                raise RuntimeError("injected reset failure")
            return original_execute(sql, params)

        monkeypatch.setattr(
            runtime.database,
            "execute",
            fail_revision_delete,
        )
        with pytest.raises(RuntimeError, match="injected reset failure"):
            service.apply(
                operation_id=prepared["manifest"]["operation_id"],
                expected_digest=prepared["digest"],
                confirmed_by="user_local_admin",
            )
        assert _count(runtime, "platform_resource") == 1
        assert _count(runtime, "platform_resource_revision") == 1
        operation = runtime.database.execute_one(
            """
            select status from resource_reset_operation
             where id = ?
            """,
            (prepared["manifest"]["operation_id"],),
        )
        assert operation == {"status": "PREPARED"}
    finally:
        runtime.database.close()


def test_apply_and_verify_preserve_history_and_protected_categories() -> None:
    runtime, _platform, reloader, publication, revision = (
        _generation_runtime()
    )
    try:
        reloader.poll_once(force=True)
        job = _historical_job(runtime)
        _pin_resource_history(
            runtime,
            job_id=job.id,
            publication=publication,
            resource_revision_id=str(revision["id"]),
        )
        before_job = _count(runtime, "agent_job")
        before_binding = _count(
            runtime,
            "agent_job_execution_binding",
        )
        before_delivery = _count(runtime, "delivery_outbox")
        before_secret = _count(runtime, "platform_secret")
        before_application = _count(
            runtime,
            "business_application",
        )
        before_generation = _count(
            runtime,
            "runtime_snapshot_generation",
        )

        service = ResourceResetService(runtime.database)
        prepared = service.prepare(
            actor_id="user_local_admin",
            backup_reference="test-backup://resource-reset/success",
            drain_timeout_seconds=0,
        )
        applied = service.apply(
            operation_id=prepared["manifest"]["operation_id"],
            expected_digest=prepared["digest"],
            confirmed_by="user_local_admin",
        )
        assert applied["status"] == "APPLIED"
        verified = service.verify(
            operation_id=prepared["manifest"]["operation_id"],
            actor_id="user_local_admin",
        )
        assert verified["status"] == "VERIFIED"
        assert all(
            value
            for key, value in verified["checks"].items()
            if not key.endswith("_count")
        )
        assert _count(runtime, "platform_resource") == 0
        assert _count(runtime, "platform_resource_binding") == 0
        assert _count(runtime, "platform_resource_revision") == 0
        assert _count(
            runtime,
            "business_application_publication_resource",
        ) == 0
        assert _count(runtime, "tool_resource_runtime_state") == 0
        assert _count(runtime, "agent_job") == before_job
        assert _count(
            runtime,
            "agent_job_execution_binding",
        ) == before_binding
        assert _count(runtime, "delivery_outbox") == before_delivery
        assert _count(runtime, "platform_secret") == before_secret
        assert _count(
            runtime,
            "business_application",
        ) == before_application
        assert _count(
            runtime,
            "runtime_snapshot_generation",
        ) == before_generation + 1
        assert runtime.database.execute_one(
            """
            select s.status, s.reason_codes_json
              from business_application_runtime_state s
              join runtime_snapshot_generation g
                on g.id = s.generation_id
             where g.status = 'ACTIVE'
            """
        ) == {
            "status": "BLOCKED",
            "reason_codes_json": '["resource_reset"]',
        }
    finally:
        runtime.database.close()


def _historical_job(runtime):
    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="resource-reset-history-job",
            dingding_conversation_id="history-conversation",
            dingding_user_id="local-user",
            user_message="保留历史任务",
            project_code="default",
        )
    )
    runtime.agent_repository.claim_job(job.id, "history-worker")
    runtime.agent_repository.transition_job(
        job_id=job.id,
        target=JobStatus.SUCCEEDED,
        result="historical result",
    )
    enqueue_job_result_for_delivery(runtime, job.id)
    return job


def _pin_resource_history(
    runtime,
    *,
    job_id: str,
    publication: dict[str, object],
    resource_revision_id: str,
) -> None:
    application = runtime.database.execute_one(
        """
        select application_id from business_application_publication
         where id = ?
        """,
        (publication["id"],),
    )
    resource = runtime.database.execute_one(
        """
        select r.environment_id, r.base_id
          from platform_resource_revision rr
          join platform_resource r on r.id = rr.resource_id
         where rr.id = ?
        """,
        (resource_revision_id,),
    )
    assert application is not None
    assert resource is not None
    scope_id = f"reset_scope_{job_id}"
    scope_hash = "a" * 64
    runtime.database.execute(
        """
        insert into agent_job_execution_scope
          (id, job_id, business_application_id,
           application_publication_id, agent_publication_id,
           environment_id, base_id, workshop_id, scope_hash,
           schema_version, snapshot_json, created_at)
        values (?, ?, ?, ?, 'agent_publication_default_v1',
                ?, ?, null, ?, 2, '{}',
                '2026-07-28T00:00:00+00:00')
        """,
        (
            scope_id,
            job_id,
            application["application_id"],
            publication["id"],
            resource["environment_id"],
            resource["base_id"],
            scope_hash,
        ),
    )
    runtime.database.execute(
        """
        insert into agent_job_execution_binding
          (id, execution_scope_id, capability_code, handler_id,
           handler_version, resource_slot, resource_revision_id,
           constraints_json, binding_hash, created_at)
        values (?, ?, 'query_database', 'query_database', '1.0.0',
                'database', ?, '{}', ?,
                '2026-07-28T00:00:00+00:00')
        """,
        (
            f"reset_binding_{job_id}",
            scope_id,
            resource_revision_id,
            "b" * 64,
        ),
    )
    runtime.database.execute(
        """
        update agent_job
           set execution_scope_id = ?, execution_scope_hash = ?
         where id = ?
        """,
        (scope_id, scope_hash, job_id),
    )


def _count(runtime, table: str) -> int:
    allowed = {
        "resource_reset_operation",
        "platform_resource",
        "platform_resource_binding",
        "platform_resource_revision",
        "business_application_publication_resource",
        "tool_resource_runtime_state",
        "agent_job",
        "agent_job_execution_binding",
        "delivery_outbox",
        "platform_secret",
        "business_application",
        "runtime_snapshot_generation",
    }
    assert table in allowed
    row = runtime.database.execute_one(
        f"select count(*) as count from {table}"
    )
    return int(row["count"] if row else 0)
