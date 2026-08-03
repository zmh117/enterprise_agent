from __future__ import annotations

import json

import pytest

from app.bootstrap import Container, build_test_container
from app.modules.admin.infrastructure.read_repository import AdminReadRepository
from app.modules.managed_channel.application.dingtalk_test_data_rebuild import (
    CONFIRMATION_TEXT,
    DingTalkTestDataRebuildService,
)
from app.modules.managed_channel.domain import DingTalkApplicationInput
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import test_settings as make_test_settings


NOW = "2026-08-03T00:00:00+00:00"


def _count(runtime: Container, table: str) -> int:
    row = runtime.database.execute_one(f"select count(*) as count from {table}")
    assert row is not None
    return int(row["count"])


def _runtime_with_targets() -> tuple[Container, dict[str, str]]:
    runtime = build_test_container(
        make_test_settings(),
        migrate=True,
        seed=True,
    )
    enterprise = runtime.managed_channel_service.create_dingtalk_enterprise(
        name="重建测试企业",
        actor_id="user_local_admin",
    )
    runtime.database.execute(
        """
        update dingtalk_enterprise
           set corp_id = 'corp-rebuild-test', status = 'ACTIVE',
               verified_at = ?, verification_event_id = 'verify-rebuild-test'
         where id = ?
        """,
        (NOW, enterprise["id"]),
    )
    connector = runtime.managed_channel_service.create_dingtalk(
        DingTalkApplicationInput(
            name="重建测试机器人",
            client_id="rebuild-test-client",
            client_secret="REBUILD-TEST-CLIENT-SECRET",
            dingtalk_enterprise_id=str(enterprise["id"]),
        ),
        actor_id="user_local_admin",
        enabled=True,
    )
    application = runtime.business_application_service.create(
        actor_id="user_local_admin",
        code="dingtalk-rebuild-test-app",
        name="钉钉重建测试应用",
        description="测试重建保留不可变发布",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    revision = runtime.business_application_service.save_draft(
        actor_id="user_local_admin",
        code=str(application["code"]),
        expected_revision=int(application["revision"]),
        payload={
            "agent_publication_id": "agent_publication_default_v1",
            "workflow_publication_id": "",
            "session_policy": {
                "conversation_mode": "channel",
                "recent_message_limit": 20,
                "retention_days": 30,
                "continuous_conversation_enabled": True,
                "attachments_enabled": False,
            },
            "execution_policy": {
                "max_turns": 12,
                "timeout_seconds": 300,
                "max_tool_calls": 30,
            },
            "triggers": [
                {
                    "trigger_type": "dingtalk_private",
                    "connector_id": connector["id"],
                    "routing_key": "bot:rebuild-test-client",
                    "actor_policy": "CURRENT_SENDER",
                    "service_account_user_id": "",
                    "enabled": True,
                    "config": {
                        "conversation_type": "private",
                        "require_mention": False,
                        "webhook_definition_id": "",
                    },
                }
            ],
            "deliveries": [
                {
                    "delivery_type": "reply_original",
                    "connector_id": connector["id"],
                    "enabled": True,
                    "config": {
                        "target_reference": "",
                        "reply_mode": "original",
                    },
                }
            ],
            "capabilities": [],
        },
    )
    publication = runtime.business_application_service.publish(
        actor_id="user_local_admin",
        code=str(application["code"]),
        revision_id=str(revision["id"]),
    )
    deployment = runtime.business_application_service.activate(
        actor_id="user_local_admin",
        code=str(application["code"]),
        environment="local",
        publication_id=str(publication["id"]),
        expected_revision=0,
    )

    for event_id, status in (
        ("rebuild-event-1", "JOB_CREATED"),
        ("rebuild-event-2", "JOB_CREATED"),
    ):
        runtime.database.execute(
            """
            insert into channel_ingress_event
              (id, source_type, connector_id, external_event_id,
               correlation_id, payload_hash, safe_summary_json,
               normalized_event_json, reply_credential_ciphertext,
               status, error_code, error_summary, request_bytes,
               received_at, completed_at)
            values (?, 'dingtalk_stream', ?, ?, ?, ?, '{}', '{}', '',
                    ?, '', '', 10, ?, ?)
            """,
            (
                event_id,
                connector["id"],
                event_id,
                f"correlation-{event_id}",
                event_id.ljust(64, "0")[:64],
                status,
                NOW,
                NOW,
            ),
        )
    runtime.database.execute(
        """
        insert into channel_ingress_outbox
          (id, channel_event_id, correlation_id, status, attempt_count,
           next_attempt_at, created_at, published_at, updated_at)
        values ('rebuild-outbox', 'rebuild-event-1',
                'correlation-rebuild-event-1', 'published', 1,
                ?, ?, ?, ?)
        """,
        (NOW, NOW, NOW, NOW),
    )
    runtime.database.execute(
        """
        insert into dingtalk_identity_candidate
          (id, tenant_code, external_subject_id, display_name,
           first_seen_at, last_seen_at, observation_count, revision,
           created_at, updated_at, dingtalk_enterprise_id)
        values ('rebuild-candidate', ?, 'staff-rebuild', '重建候选',
                ?, ?, 1, 1, ?, ?, ?)
        """,
        (enterprise["id"], NOW, NOW, NOW, NOW, enterprise["id"]),
    )
    runtime.database.execute(
        """
        insert into dingtalk_identity_candidate_message
          (id, candidate_id, source_ingress_event_id, connector_id,
           robot_code, conversation_type, conversation_id, message_kind,
           safe_text, text_truncated, attachment_type, attachment_name,
           occurred_at, received_at, created_at)
        values ('rebuild-candidate-message', 'rebuild-candidate',
                'rebuild-event-1', ?, 'rebuild-robot', 'direct',
                'conversation-rebuild', 'text', '', 0, '', '', ?, ?, ?)
        """,
        (connector["id"], NOW, NOW, NOW),
    )
    identity = runtime.identity_repository.bind_dingtalk_identity(
        user_id="user_local_admin",
        dingtalk_enterprise_id=str(enterprise["id"]),
        external_subject_id="staff-rebuild",
        display_name="重建用户",
        source_connector_id=str(connector["id"]),
        source_ingress_event_id="rebuild-event-1",
        observed_at=NOW,
        replace_current=False,
    )
    runtime.identity_repository.record_dingtalk_message_facts(
        identity_id=str(identity["id"]),
        connector_id=str(connector["id"]),
        source_ingress_event_id="rebuild-event-2",
        nickname="重建用户新昵称",
        occurred_at="2026-08-03T00:01:00+00:00",
        received_at="2026-08-03T00:01:00+00:00",
    )
    runtime.identity_repository.bind_external_identity(
        user_id="user_local_admin",
        provider="ones",
        tenant_code="ones-rebuild-preserved",
        external_subject_id="ones-user-rebuild-preserved",
        connector_id="",
        display_name="ONES 保留用户",
        metadata={"team_uuids": ["ones-team-preserved"]},
    )
    runtime.database.execute(
        """
        insert into channel_connector_runtime
          (connector_id, runtime_id, runtime_status, loaded_revision,
           connected, registered, connected_at, last_heartbeat_at, updated_at)
        values (?, 'runtime-rebuild', 'CONNECTED', ?, 1, 1, ?, ?, ?)
        """,
        (connector["id"], connector["revision"], NOW, NOW, NOW),
    )
    runtime.database.execute(
        """
        insert into channel_runtime_lease
          (lease_name, runtime_id, lease_token, expires_at, updated_at)
        values ('dingtalk-stream-runtime-singleton', 'runtime-rebuild',
                'expired-test-token', '2020-01-01T00:00:00+00:00', ?)
        """,
        (NOW,),
    )
    session = runtime.agent_repository.create_session(
        dingding_conversation_id="conversation-rebuild-history",
        dingding_user_id="staff-rebuild",
        source="dingtalk_stream",
        project_code="default",
        source_channel="dingtalk",
        source_connector_id=str(connector["id"]),
        external_identity_id=str(identity["id"]),
        business_application_id=str(application["id"]),
        business_application_code=str(application["code"]),
        application_publication_id=str(publication["id"]),
        execution_scope_hash="rebuild-test-scope",
        session_key="rebuild-history-session",
        conversation_mode="channel",
    )
    job = runtime.agent_repository.create_job(
        session_id=session.id,
        idempotency_key="rebuild-history-job",
        user_id="staff-rebuild",
        project_code="default",
        source="dingtalk_stream",
        user_message="历史消息必须保留",
        max_retry_count=1,
        source_channel="dingtalk",
        source_connector_id=str(connector["id"]),
        external_event_id="rebuild-event-1",
        internal_user_id="user_local_admin",
        external_identity_id=str(identity["id"]),
        agent_definition_id="agent_default",
        agent_publication_id="agent_publication_default_v1",
        agent_revision=1,
        business_application_id=str(application["id"]),
        business_application_code=str(application["code"]),
        business_application_publication_id=str(publication["id"]),
        business_application_deployment_id=str(deployment["id"]),
        business_application_config_hash=str(publication["config_hash"]),
        execution_policy={
            "schema_version": 1,
            "requested": {
                "max_turns": 12,
                "timeout_seconds": 300,
                "max_tool_calls": 30,
            },
            "effective": {
                "max_turns": 12,
                "timeout_seconds": 300,
                "max_tool_calls": 30,
            },
            "sources": {"source_kind": "runtime_default"},
        },
    )
    runtime.agent_repository.add_tool_call(
        job_id=job.id,
        tool_name="query_database",
        request_payload={"query": "safe"},
        response_summary={"rows": 1},
        status="SUCCEEDED",
        duration_ms=1,
        risk_level="low",
    )
    runtime.agent_repository.add_delivery_attempt(
        job_id=job.id,
        route_type="dingtalk_stream_session_webhook",
        connector_id=str(connector["id"]),
        target_summary={"conversation": "historical"},
        status="SUCCEEDED",
    )
    connector_storage = runtime.database.execute_one(
        "select secret_ref from integration_connector where id = ?",
        (connector["id"],),
    )
    assert connector_storage is not None
    return runtime, {
        "enterprise_id": str(enterprise["id"]),
        "connector_id": str(connector["id"]),
        "secret_ref": str(connector_storage["secret_ref"]),
        "identity_id": str(identity["id"]),
        "publication_id": str(publication["id"]),
        "deployment_id": str(deployment["id"]),
        "job_id": job.id,
    }


def test_preview_is_stable_read_only_and_secret_safe() -> None:
    runtime, ids = _runtime_with_targets()
    try:
        before = {
            table: _count(runtime, table)
            for table in (
                "integration_connector",
                "dingtalk_enterprise",
                "user_external_identity",
                "channel_ingress_event",
                "audit_event",
                "platform_secret",
            )
        }
        service = DingTalkTestDataRebuildService(
            runtime.database,
            environment="test",
        )
        first = service.report()
        second = service.report()

        assert first["mode"] == "PREVIEW"
        assert first["plan_hash"] == second["plan_hash"]
        assert len(first["plan_hash"]) == 64
        assert first["database_fingerprint"] == second["database_fingerprint"]
        assert first["counts"]["connectors"] >= 1
        assert first["counts"]["dedicated_secrets"] == 1
        assert first["counts"]["application_observations"] == 1
        assert first["counts"]["nickname_audits"] == 1
        assert first["historical_references"]["application_revision_triggers"]
        serialized = json.dumps(first, ensure_ascii=False)
        assert "REBUILD-TEST-CLIENT-SECRET" not in serialized
        assert "expired-test-token" not in serialized
        assert ids["connector_id"] in serialized
        assert {table: _count(runtime, table) for table in before} == before
    finally:
        runtime.database.close()


def test_production_and_active_writers_are_hard_rejected() -> None:
    runtime, _ = _runtime_with_targets()
    try:
        with pytest.raises(NonRetryableExecutionError) as forbidden:
            DingTalkTestDataRebuildService(
                runtime.database,
                environment="production",
            ).report()
        assert forbidden.value.error_code == ("dingtalk_rebuild_production_forbidden")
        runtime.database.execute(
            """
            update channel_runtime_lease
               set expires_at = '2099-01-01T00:00:00+00:00'
             where lease_name = 'dingtalk-stream-runtime-singleton'
            """
        )
        service = DingTalkTestDataRebuildService(
            runtime.database,
            environment="test",
        )
        preview = service.report()
        assert preview["write_stop_evidence"]["safe_to_apply"] is False
        with pytest.raises(
            NonRetryableExecutionError,
            match="writers are still active",
        ):
            service.apply(
                expected_plan_hash=preview["plan_hash"],
                confirmation=CONFIRMATION_TEXT,
                backup_reference="backup://dingtalk/rebuild-test",
                writes_stopped=True,
                actor_id="user_local_admin",
            )
    finally:
        runtime.database.close()


def test_plan_drift_is_rejected_without_writes() -> None:
    runtime, ids = _runtime_with_targets()
    try:
        service = DingTalkTestDataRebuildService(
            runtime.database,
            environment="test",
        )
        preview = service.report()
        runtime.database.execute(
            """
            update integration_connector
               set revision = revision + 1
             where id = ?
            """,
            (ids["connector_id"],),
        )
        before_events = _count(runtime, "channel_ingress_event")
        with pytest.raises(
            NonRetryableExecutionError,
            match="inventory changed",
        ):
            service.apply(
                expected_plan_hash=preview["plan_hash"],
                confirmation=CONFIRMATION_TEXT,
                backup_reference="backup://dingtalk/rebuild-test",
                writes_stopped=True,
                actor_id="user_local_admin",
            )
        assert _count(runtime, "channel_ingress_event") == before_events
        connector = runtime.database.execute_one(
            "select deleted from integration_connector where id = ?",
            (ids["connector_id"],),
        )
        assert connector == {"deleted": 0}
    finally:
        runtime.database.close()


def test_mid_apply_failure_rolls_back_every_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, ids = _runtime_with_targets()
    try:
        service = DingTalkTestDataRebuildService(
            runtime.database,
            environment="test",
        )
        preview = service.report()
        before = {
            table: _count(runtime, table)
            for table in (
                "dingtalk_identity_nickname_audit",
                "dingtalk_identity_application_observation",
                "channel_ingress_event",
                "user_external_identity",
            )
        }

        def fail_before_connectors(step: str) -> None:
            if step == "connectors":
                raise RuntimeError("injected DingTalk rebuild failure")

        monkeypatch.setattr(service, "_before_step", fail_before_connectors)
        with pytest.raises(
            RuntimeError,
            match="injected DingTalk rebuild failure",
        ):
            service.apply(
                expected_plan_hash=preview["plan_hash"],
                confirmation=CONFIRMATION_TEXT,
                backup_reference="backup://dingtalk/rebuild-test",
                writes_stopped=True,
                actor_id="user_local_admin",
            )
        assert {table: _count(runtime, table) for table in before} == before
        connector = runtime.database.execute_one(
            "select deleted from integration_connector where id = ?",
            (ids["connector_id"],),
        )
        assert connector == {"deleted": 0}
    finally:
        runtime.database.close()


def test_apply_preserves_history_and_repeat_empty_plan_is_noop() -> None:
    runtime, ids = _runtime_with_targets()
    try:
        service = DingTalkTestDataRebuildService(
            runtime.database,
            environment="test",
        )
        preview = service.report()
        protected_before = dict(preview["protected_counts"])
        historical_before = preview["historical_references"]
        target_connector_ids = {str(item["id"]) for item in preview["targets"]["connectors"]}
        applied = service.apply(
            expected_plan_hash=preview["plan_hash"],
            confirmation=CONFIRMATION_TEXT,
            backup_reference="backup://dingtalk/rebuild-test",
            writes_stopped=True,
            actor_id="user_local_admin",
        )

        assert applied["status"] == "APPLIED"
        assert all(value == 0 for value in applied["remaining_counts"].values())
        assert applied["protected_counts"] == protected_before
        connector = runtime.database.execute_one(
            """
            select enabled, deleted, allow_ingress, secret_ref,
                   dingtalk_enterprise_id, metadata
              from integration_connector where id = ?
            """,
            (ids["connector_id"],),
        )
        assert connector is not None
        assert connector["enabled"] == 0
        assert connector["deleted"] == 1
        assert connector["allow_ingress"] == 0
        assert connector["secret_ref"] == ""
        assert connector["dingtalk_enterprise_id"] is None
        assert json.loads(connector["metadata"])["historical_source_status"] == "UNAVAILABLE"
        job_detail = runtime.agent_repository.get_job_detail(ids["job_id"])
        assert job_detail["source_connector_name"] == "重建测试机器人"
        assert job_detail["source_connector_availability"] == "UNAVAILABLE_HISTORICAL"
        admin_evidence = AdminReadRepository(runtime.database).job_evidence(ids["job_id"])
        assert admin_evidence is not None
        assert admin_evidence["job"]["source_connector_availability"] == "UNAVAILABLE_HISTORICAL"
        assert (
            runtime.database.execute_one(
                "select id from dingtalk_enterprise where id = ?",
                (ids["enterprise_id"],),
            )
            is None
        )
        assert (
            runtime.database.execute_one(
                "select id from user_external_identity where id = ?",
                (ids["identity_id"],),
            )
            is None
        )
        assert runtime.database.execute_one(
            "select status from platform_secret where ref = ?",
            (ids["secret_ref"],),
        ) == {"status": "disabled"}
        assert runtime.database.execute_one(
            "select active from business_application_deployment where id = ?",
            (ids["deployment_id"],),
        ) == {"active": 0}
        assert runtime.database.execute_one(
            "select id from agent_job where id = ?",
            (ids["job_id"],),
        ) == {"id": ids["job_id"]}
        assert _count(runtime, "agent_tool_call") == protected_before["agent_tool_calls"]
        assert _count(runtime, "delivery_attempt") == protected_before["delivery_attempts"]
        assert (
            service._historical_references(  # noqa: SLF001
                target_connector_ids
            )
            == historical_before
        )
        assert (
            runtime.database.execute_one(
                """
            select id from audit_event
             where event_type = 'dingtalk_test_data_rebuild.applied'
            """
            )
            is not None
        )

        empty_preview = service.report()
        assert empty_preview["empty"] is True
        noop = service.apply(
            expected_plan_hash=empty_preview["plan_hash"],
            confirmation=CONFIRMATION_TEXT,
            backup_reference="backup://dingtalk/rebuild-test-repeat",
            writes_stopped=True,
            actor_id="user_local_admin",
        )
        assert noop["status"] == "NOOP"
    finally:
        runtime.database.close()
