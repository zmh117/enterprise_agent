from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.bootstrap import build_test_container
from app.modules.agent_config.api.controller import AgentDraftRequest
from app.modules.business_application.api.controller import PublishRequest
from app.modules.internal_tools.application.legacy_migration import (
    BuiltinToolLegacyWriteGuard,
)
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_business_application_control_plane import (
    control_plane_settings,
    draft_payload,
)
from backend.tests.test_agent_publication_runtime import publishable_config


def test_agent_legacy_name_write_is_rejected_and_exact_empty_envelope_can_publish() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    service = runtime.agent_config_service
    current = service.get()
    config = publishable_config(runtime, builtin_tool_release_ids=[])
    config["tools"] = ["get_er_context"]

    with pytest.raises(NonRetryableExecutionError) as rejected:
        service.save_draft(
            actor_id="user_local_admin",
            agent_code="default-diagnostic-agent",
            expected_revision=int(current["draft"]["revision"]),
            config=config,
            correlation_id="legacy-agent-rejected",
        )
    assert rejected.value.error_code == "builtin_tool_legacy_write_forbidden"
    assert runtime.database.execute_one(
        """
        select write_boundary, decision, reason_code, correlation_id
          from builtin_tool_legacy_write_audit
         where correlation_id = 'legacy-agent-rejected'
        """
    ) == {
        "write_boundary": "AGENT_PUBLICATION",
        "decision": "REJECTED",
        "reason_code": "builtin_tool_legacy_write_forbidden",
        "correlation_id": "legacy-agent-rejected",
    }

    config["tools"] = []
    config["builtin_tool_release_ids"] = []
    revision = service.save_draft(
        actor_id="user_local_admin",
        agent_code="default-diagnostic-agent",
        expected_revision=int(current["draft"]["revision"]),
        config=config,
    )
    validated = service.validate_revision(
        actor_id="user_local_admin",
        agent_code="default-diagnostic-agent",
        revision_id=str(revision["id"]),
    )
    assert validated["validation"] == {"valid": True, "errors": []}
    publication = service.publish(
        actor_id="user_local_admin",
        agent_code="default-diagnostic-agent",
        revision_id=str(revision["id"]),
    )
    assert publication["snapshot"]["builtin_tool_envelope"] == []
    assert runtime.database.execute_one(
        """
        select count(*) as count
          from agent_tool_binding
         where publication_id = ?
        """,
        (publication["id"],),
    ) == {"count": 0}
    assert runtime.database.execute_one(
        """
        select count(*) as count
          from agent_tool_binding
         where publication_id = 'agent_publication_default_v1'
        """
    )["count"] > 0
    runtime.database.close()


def test_agent_write_request_no_longer_accepts_legacy_tools_field() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    config = publishable_config(runtime, builtin_tool_release_ids=[])
    config["tools"] = []
    with pytest.raises(ValidationError) as rejected:
        AgentDraftRequest.model_validate(
            {"expected_revision": 1, "config": config}
        )
    assert any(
        error["loc"] == ("config", "tools")
        and error["type"] == "extra_forbidden"
        for error in rejected.value.errors()
    )
    runtime.database.close()


def test_application_legacy_handler_write_is_rejected_but_exact_empty_allowlist_publishes() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    service = runtime.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="legacy-application-cutover",
        name="Legacy Application Cutover",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    revision = service.save_draft(
        actor_id="user_local_admin",
        code="legacy-application-cutover",
        expected_revision=int(application["revision"]),
        payload=draft_payload(),
    )

    with pytest.raises(ValidationError) as api_rejected:
        PublishRequest.model_validate(
            {
                "revision_id": revision["id"],
                "handler_bindings": [{"legacy": "name-bound-handler"}],
            }
        )
    assert any(
        error["loc"] == ("handler_bindings",)
        and error["type"] == "extra_forbidden"
        for error in api_rejected.value.errors()
    )
    with pytest.raises(TypeError, match="handler_bindings"):
        service.publish(
            actor_id="user_local_admin",
            code="legacy-application-cutover",
            revision_id=str(revision["id"]),
            handler_bindings=[{"legacy": "name-bound-handler"}],
            correlation_id="legacy-application-rejected",
        )

    publication = service.publish(
        actor_id="user_local_admin",
        code="legacy-application-cutover",
        revision_id=str(revision["id"]),
    )
    assert runtime.database.execute_one(
        """
        select resolution_count
          from business_application_publication_builtin_tool_resolution_set
         where application_publication_id = ?
        """,
        (publication["id"],),
    ) == {"resolution_count": 0}
    runtime.database.execute(
        """
        delete from business_application_publication_builtin_tool_resolution_set
         where application_publication_id = ?
        """,
        (publication["id"],),
    )
    with pytest.raises(NonRetryableExecutionError) as activation:
        service.activate(
            actor_id="user_local_admin",
            code="legacy-application-cutover",
            environment="local",
            publication_id=str(publication["id"]),
            expected_revision=0,
        )
    assert (
        activation.value.error_code
        == "builtin_tool_legacy_reactivation_forbidden"
    )
    assert service.repository.get_publication(str(publication["id"]))[
        "config_hash"
    ] == publication["config_hash"]
    runtime.database.close()


def test_job_legacy_binding_is_rejected_without_exact_application_marker() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    guard = BuiltinToolLegacyWriteGuard(runtime.database)

    with pytest.raises(NonRetryableExecutionError) as rejected:
        guard.reject_legacy_job_snapshot(
            agent_publication_id="agent_publication_default_v1",
            application_publication_id="",
            source_id="job-intent-safe-hash",
            correlation_id="legacy-job-rejected",
        )
    assert rejected.value.error_code == "builtin_tool_legacy_write_forbidden"
    assert runtime.database.execute_one(
        """
        select write_boundary, source_id, decision, correlation_id
          from builtin_tool_legacy_write_audit
         where correlation_id = 'legacy-job-rejected'
        """
    ) == {
        "write_boundary": "JOB_SNAPSHOT",
        "source_id": "job-intent-safe-hash",
        "decision": "REJECTED",
        "correlation_id": "legacy-job-rejected",
    }
    runtime.database.close()


def test_legacy_agent_publication_cannot_be_rolled_back_but_history_remains() -> None:
    runtime = build_test_container(control_plane_settings(), migrate=True, seed=True)
    service = runtime.agent_config_service
    current = service.get()
    revision = service.save_draft(
        actor_id="user_local_admin",
        agent_code="default-diagnostic-agent",
        expected_revision=int(current["draft"]["revision"]),
        config=publishable_config(runtime, builtin_tool_release_ids=[]),
    )
    exact = service.publish(
        actor_id="user_local_admin",
        agent_code="default-diagnostic-agent",
        revision_id=str(revision["id"]),
    )

    with pytest.raises(NonRetryableExecutionError) as rollback:
        service.rollback(
            actor_id="user_local_admin",
            agent_code="default-diagnostic-agent",
            publication_id="agent_publication_default_v1",
        )
    assert (
        rollback.value.error_code
        == "builtin_tool_legacy_reactivation_forbidden"
    )
    assert service.current_publication("default-diagnostic-agent")["id"] == exact["id"]
    assert runtime.database.execute_one(
        """
        select count(*) as count
          from agent_tool_binding
         where publication_id = 'agent_publication_default_v1'
        """
    )["count"] > 0
    assert service.publication("agent_publication_default_v1")["id"] == (
        "agent_publication_default_v1"
    )
    runtime.database.close()
