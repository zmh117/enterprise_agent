from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil

import pytest

from app.bootstrap import build_test_container
from app.modules.internal_tools.application.legacy_migration import (
    BuiltinToolLegacyWriteGuard,
)
from app.modules.internal_tools.application.legacy_removal_gate import (
    BuiltinToolLegacyRemovalGate,
)
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_application_builtin_tool_resource_mapping import (
    _publish_next_database_resource_revision,
)
from backend.tests.test_business_application_control_plane import (
    control_plane_settings,
    draft_payload,
)
from backend.tests.test_job_builtin_tool_snapshot import (
    _command,
    _published_application,
)


def _publish_newer_application_version(
    runtime: object,
    *,
    application: dict[str, object],
    facts: dict[str, object],
) -> tuple[dict[str, object], str]:
    next_cloud_revision = _publish_next_database_resource_revision(
        runtime,
        previous_revision_id=str(facts["resource_revision_by_placement"]["cloud"]),
    )
    current = runtime.business_application_repository.get_by_id(str(application["id"]))
    payload = draft_payload(
        capabilities=[
            {
                "capability_code": "query_database",
                "version_constraint": "",
                "enabled": True,
            }
        ]
    )
    payload["target_paths"] = [
        {
            "target_scope_type": "workshop",
            "environment_code": "job-snapshot",
            "base_code": "guanlan",
            "workshop_code": "GL001",
        }
    ]
    payload["builtin_tools"] = [
        {
            "tool_release_id": facts["release"]["id"],
            "resources": [
                {
                    "resource_slot": "database",
                    "target_scope_type": "workshop",
                    "environment_code": "job-snapshot",
                    "base_code": "guanlan",
                    "workshop_code": "GL001",
                    "placement": "cloud",
                    "resource_revision_id": next_cloud_revision,
                    "workshop_partition_policy_revision_id": facts["policy_revision_id"],
                    "loki_scope_policy_revision_id": "",
                },
                {
                    "resource_slot": "database",
                    "target_scope_type": "workshop",
                    "environment_code": "job-snapshot",
                    "base_code": "guanlan",
                    "workshop_code": "GL001",
                    "placement": "edge",
                    "resource_revision_id": facts["resource_revision_by_placement"]["edge"],
                    "workshop_partition_policy_revision_id": facts["policy_revision_id"],
                    "loki_scope_policy_revision_id": "",
                },
            ],
        }
    ]
    revision = runtime.business_application_service.save_draft(
        actor_id="user_local_admin",
        code="job-builtin-snapshot",
        expected_revision=int(current["revision"]),
        payload=payload,
    )
    publication = runtime.business_application_service.publish(
        actor_id="user_local_admin",
        code="job-builtin-snapshot",
        revision_id=str(revision["id"]),
    )
    runtime.business_application_service.activate(
        actor_id="user_local_admin",
        code="job-builtin-snapshot",
        environment="local",
        publication_id=str(publication["id"]),
        expected_revision=1,
    )
    return publication, next_cloud_revision


def _complete_exact_acceptance(
    runtime: object,
    *,
    job_id: str,
) -> tuple[str, str]:
    claimed = runtime.agent_repository.claim_job(job_id, "removal-backup-worker")
    assert claimed is not None
    runtime.agent_repository.transition_job(
        job_id=job_id,
        target=type(claimed.status).SUCCEEDED,
        result="backup rollback acceptance passed",
    )
    frozen = runtime.builtin_tool_snapshot_service.verify(job_id)
    binding = runtime.database.execute_one(
        "select * from agent_job_builtin_tool_binding where snapshot_id = ?",
        (frozen["id"],),
    )
    assert binding is not None
    tool_call_id = runtime.agent_repository.add_tool_call(
        job_id=job_id,
        tool_name="query_database",
        request_payload={},
        response_summary={"row_count": 1},
        status="SUCCEEDED",
        duration_ms=1,
        risk_level="low",
    )
    candidate = frozen["snapshot"]["bindings"][0]["candidates"][0]
    runtime.database.execute(
        """
        insert into agent_tool_call_builtin_tool_fact
          (tool_call_id, snapshot_id, tool_execution_binding_id,
           tool_release_id, handler_version, implementation_digest,
           actual_placement, resource_revision_id,
           workshop_partition_policy_revision_id,
           loki_scope_policy_revision_id, effective_scope_hash,
           effective_selector_hash, authorization_decision,
           decision_reason_code, correlation_id, created_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ALLOWED',
                'exact_job_snapshot_allowed', 'removal-backup-acceptance',
                CURRENT_TIMESTAMP)
        """,
        (
            tool_call_id,
            frozen["id"],
            binding["id"],
            binding["tool_release_id"],
            binding["handler_version"],
            binding["implementation_digest"],
            candidate["placement"],
            candidate["resource_revision_id"],
            candidate["workshop_partition_policy_revision_id"],
            candidate["loki_scope_policy_revision_id"],
            frozen["snapshot"]["target"]["target_hash"],
            "e" * 64,
        ),
    )
    delivery_attempt_id = runtime.agent_repository.add_delivery_attempt(
        job_id=job_id,
        route_type="webhook",
        connector_id="connector-webhook-default",
        target_summary={},
        status="SUCCEEDED",
    )
    return tool_call_id, delivery_attempt_id


def _verify_restored_database(
    *,
    database_path: Path,
    original_job_id: str,
    application_id: str,
    original_publication_id: str,
    original_snapshot_hash: str,
    original_resource_ids: set[str],
    newer_publication_id: str,
    newer_resource_id: str,
    expected_gate_decision: str,
) -> None:
    settings = replace(
        control_plane_settings(),
        database_dsn=f"sqlite:///{database_path}",
    )
    restored = build_test_container(settings, migrate=True, seed=False)
    try:
        frozen = restored.builtin_tool_snapshot_service.verify(original_job_id)
        assert frozen["snapshot_hash"] == original_snapshot_hash
        assert frozen["snapshot"]["application_publication"]["id"] == (
            original_publication_id
        )
        restored_resource_ids = {
            str(candidate["resource_revision_id"])
            for binding in frozen["snapshot"]["bindings"]
            for candidate in binding["candidates"]
        }
        assert restored_resource_ids == original_resource_ids
        assert newer_resource_id not in restored_resource_ids
        assert restored.database.execute_one(
            "select id from business_application_publication where id = ?",
            (newer_publication_id,),
        ) == {"id": newer_publication_id}
        assert restored.database.execute_one(
            """
            select publication_id from business_application_deployment
             where application_id = ? and environment = 'local' and active = 1
            """,
            (application_id,),
        ) == {"publication_id": newer_publication_id}

        legacy_bindings_before = restored.database.execute_one(
            "select count(*) as count from agent_tool_binding"
        )
        with pytest.raises(NonRetryableExecutionError) as legacy_write:
            BuiltinToolLegacyWriteGuard(restored.database).reject_legacy_job_snapshot(
                agent_publication_id="agent_publication_default_v1",
                application_publication_id="",
                source_id=f"restored-{expected_gate_decision.lower()}-legacy-write",
                correlation_id=f"restored-{expected_gate_decision.lower()}-legacy-write",
            )
        assert legacy_write.value.error_code == "builtin_tool_legacy_write_forbidden"
        assert restored.database.execute_one(
            "select count(*) as count from agent_tool_binding"
        ) == legacy_bindings_before

        gate = BuiltinToolLegacyRemovalGate(
            restored.database,
            snapshot_service=restored.builtin_tool_snapshot_service,
        )
        if expected_gate_decision == "READY":
            assert gate.require_ready()["decision"] == "READY"
        else:
            with pytest.raises(NonRetryableExecutionError):
                gate.require_ready()
    finally:
        restored.database.close()


def test_pre_and_post_removal_backups_restore_without_legacy_writes_or_job_floating(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "runtime.db"
    settings = replace(
        control_plane_settings(),
        database_dsn=f"sqlite:///{database_path}",
    )
    runtime = build_test_container(settings, migrate=True, seed=True)
    application, original_publication, facts = _published_application(runtime)
    job = runtime.create_agent_job_service.execute(
        _command(
            runtime,
            application,
            original_publication,
            facts,
            idempotency_key="removal-backup-original-job",
        )
    )
    original_frozen = runtime.builtin_tool_snapshot_service.verify(job.id)
    original_resource_ids = {
        str(candidate["resource_revision_id"])
        for binding in original_frozen["snapshot"]["bindings"]
        for candidate in binding["candidates"]
    }
    newer_publication, newer_resource_id = _publish_newer_application_version(
        runtime,
        application=application,
        facts=facts,
    )
    tool_call_id, delivery_attempt_id = _complete_exact_acceptance(
        runtime,
        job_id=job.id,
    )
    runtime.database.execute(
        "update agent_publication set status = 'inactive' where id = ?",
        (job.agent_publication_id,),
    )
    gate = BuiltinToolLegacyRemovalGate(
        runtime.database,
        snapshot_service=runtime.builtin_tool_snapshot_service,
    )
    before_ready = gate.observe(
        actor_id="user_local_admin",
        correlation_id="removal-backup-before-ready",
    )
    assert before_ready["decision"] == "BLOCKED"
    assert before_ready["consecutive_zero_count"] == 1
    runtime.database.close()

    pre_removal_backup = tmp_path / "pre-removal.backup.db"
    shutil.copy2(database_path, pre_removal_backup)

    runtime = build_test_container(settings, migrate=True, seed=False)
    gate = BuiltinToolLegacyRemovalGate(
        runtime.database,
        snapshot_service=runtime.builtin_tool_snapshot_service,
    )
    after_ready = gate.observe(
        actor_id="user_local_admin",
        correlation_id="removal-backup-after-ready",
        job_id=job.id,
        tool_call_id=tool_call_id,
        delivery_attempt_id=delivery_attempt_id,
    )
    assert after_ready["decision"] == "READY"
    assert after_ready["consecutive_zero_count"] == 2
    runtime.database.close()

    post_removal_backup = tmp_path / "post-removal.backup.db"
    shutil.copy2(database_path, post_removal_backup)

    restored_pre = tmp_path / "restored-pre-removal.db"
    shutil.copy2(pre_removal_backup, restored_pre)
    _verify_restored_database(
        database_path=restored_pre,
        original_job_id=job.id,
        application_id=str(application["id"]),
        original_publication_id=str(original_publication["id"]),
        original_snapshot_hash=str(original_frozen["snapshot_hash"]),
        original_resource_ids=original_resource_ids,
        newer_publication_id=str(newer_publication["id"]),
        newer_resource_id=newer_resource_id,
        expected_gate_decision="BLOCKED",
    )

    restored_post = tmp_path / "restored-post-removal.db"
    shutil.copy2(post_removal_backup, restored_post)
    _verify_restored_database(
        database_path=restored_post,
        original_job_id=job.id,
        application_id=str(application["id"]),
        original_publication_id=str(original_publication["id"]),
        original_snapshot_hash=str(original_frozen["snapshot_hash"]),
        original_resource_ids=original_resource_ids,
        newer_publication_id=str(newer_publication["id"]),
        newer_resource_id=newer_resource_id,
        expected_gate_decision="READY",
    )
