from __future__ import annotations

import pytest

from app.bootstrap import build_test_container
from app.modules.internal_tools.application.legacy_removal_gate import (
    BuiltinToolLegacyRemovalGate,
)
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_business_application_control_plane import (
    control_plane_settings,
)
from backend.tests.test_job_builtin_tool_snapshot import (
    _command,
    _published_application,
)


def _successful_exact_runtime_tool_delivery_chain(
    runtime: object,
) -> tuple[str, str, str]:
    application, publication, facts = _published_application(
        runtime,
        placements=("cloud",),
    )
    job = runtime.create_agent_job_service.execute(
        _command(
            runtime,
            application,
            publication,
            facts,
            idempotency_key="legacy-removal-acceptance",
        )
    )
    claimed = runtime.agent_repository.claim_job(job.id, "acceptance-worker")
    assert claimed is not None
    runtime.agent_repository.transition_job(
        job_id=job.id,
        target=type(claimed.status).SUCCEEDED,
        result="acceptance passed",
    )
    frozen = runtime.builtin_tool_snapshot_service.verify(job.id)
    binding = runtime.database.execute_one(
        """
        select * from agent_job_builtin_tool_binding
         where snapshot_id = ?
        """,
        (frozen["id"],),
    )
    assert binding is not None
    tool_call_id = runtime.agent_repository.add_tool_call(
        job_id=job.id,
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
                'allowed', 'legacy-removal-acceptance', CURRENT_TIMESTAMP)
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
        job_id=job.id,
        route_type="webhook",
        connector_id="connector-webhook-default",
        target_summary={},
        status="SUCCEEDED",
    )
    runtime.database.execute(
        "update agent_publication set status = 'inactive' where id = ?",
        (job.agent_publication_id,),
    )
    return job.id, tool_call_id, delivery_attempt_id


def test_removal_gate_requires_two_zero_reports_and_real_chain_evidence() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    job_id, tool_call_id, delivery_attempt_id = (
        _successful_exact_runtime_tool_delivery_chain(runtime)
    )
    gate = BuiltinToolLegacyRemovalGate(
        runtime.database,
        snapshot_service=runtime.builtin_tool_snapshot_service,
    )

    first = gate.observe(
        actor_id="user_local_admin",
        correlation_id="legacy-removal-zero-1",
    )
    assert first["decision"] == "BLOCKED"
    assert first["zero_references"] is True
    assert first["consecutive_zero_count"] == 1
    assert first["blocking_dimensions"] == [
        "consecutive_zero_reports",
        "runtime_tool_delivery_acceptance",
    ]

    second = gate.observe(
        actor_id="user_local_admin",
        correlation_id="legacy-removal-zero-2",
        job_id=job_id,
        tool_call_id=tool_call_id,
        delivery_attempt_id=delivery_attempt_id,
    )
    assert second["decision"] == "READY"
    assert second["blocking_dimensions"] == []
    assert second["consecutive_zero_count"] == 2
    assert second["acceptance_id"]
    assert gate.require_ready()["gate_id"] == second["gate_id"]
    assert runtime.database.execute_one(
        "select count(*) as count from builtin_tool_legacy_removal_acceptance"
    ) == {"count": 1}
    runtime.database.close()


def test_nonzero_observation_resets_removal_gate_sequence() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    job_id, tool_call_id, delivery_attempt_id = (
        _successful_exact_runtime_tool_delivery_chain(runtime)
    )
    gate = BuiltinToolLegacyRemovalGate(
        runtime.database,
        snapshot_service=runtime.builtin_tool_snapshot_service,
    )
    gate.observe(
        actor_id="user_local_admin",
        correlation_id="legacy-removal-reset-zero-1",
    )
    ready = gate.observe(
        actor_id="user_local_admin",
        correlation_id="legacy-removal-reset-zero-2",
        job_id=job_id,
        tool_call_id=tool_call_id,
        delivery_attempt_id=delivery_attempt_id,
    )
    assert ready["decision"] == "READY"
    runtime.database.execute(
        "update agent_publication set status = 'active' where id = ?",
        ("agent_publication_default_v1",),
    )

    reset = gate.observe(
        actor_id="user_local_admin",
        correlation_id="legacy-removal-reset-nonzero",
    )

    assert reset["decision"] == "BLOCKED"
    assert reset["zero_references"] is False
    assert reset["consecutive_zero_count"] == 0
    assert "active_legacy_references" in reset["blocking_dimensions"]
    with pytest.raises(NonRetryableExecutionError) as blocked:
        gate.require_ready()
    assert blocked.value.error_code == "builtin_tool_legacy_removal_gate_failed"
    runtime.database.close()
