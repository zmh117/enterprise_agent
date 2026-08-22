from __future__ import annotations

import json

import pytest

from app.modules.identity.domain import ExternalIdentityDescriptor
from app.modules.managed_channel.domain import DingTalkApplicationInput
from app.shared.exceptions import NonRetryableExecutionError, PermissionDenied
from backend.tests.support.channels import ensure_active_dingtalk_test_enterprise
from backend.tests.test_unified_identity_rbac import ADMIN_ID, unified_container


def test_dingtalk_enterprise_identity_isolation_conflict_and_unknown_fail_closed() -> None:
    container = unified_container()
    default_enterprise = ensure_active_dingtalk_test_enterprise(
        container,
        corp_id="corp-test-enterprise",
    )
    first = container.identity_repository.create_user(
        username="tenant-user-a", display_name="Tenant User A"
    )
    second = container.identity_repository.create_user(
        username="tenant-user-b", display_name="Tenant User B"
    )

    bound = container.identity_repository.bind_dingtalk_identity(
        user_id=str(first["id"]),
        dingtalk_enterprise_id=str(default_enterprise["id"]),
        external_subject_id="staff-shared",
        display_name="共享 Staff A",
        source_connector_id="connector-dingtalk-stream-default",
        source_ingress_event_id="",
        observed_at="2026-08-03T00:00:00+00:00",
        replace_current=False,
    )
    assert bound["user_id"] == first["id"]

    with pytest.raises(NonRetryableExecutionError) as conflict:
        container.identity_repository.bind_dingtalk_identity(
            user_id=str(second["id"]),
            dingtalk_enterprise_id=str(default_enterprise["id"]),
            external_subject_id="staff-shared",
            display_name="冲突 Staff",
            source_connector_id="connector-dingtalk-stream-default",
            source_ingress_event_id="",
            observed_at="2026-08-03T00:00:00+00:00",
            replace_current=False,
        )
    assert conflict.value.error_code == "identity_restore_required"

    other_enterprise = container.managed_channel_service.create_dingtalk_enterprise(
        name="隔离企业 B",
        actor_id=ADMIN_ID,
    )
    container.database.execute(
        """
        update dingtalk_enterprise
           set corp_id = 'corp-test-enterprise-b', status = 'ACTIVE',
               verified_at = '2026-08-03T00:00:00+00:00',
               verification_event_id = 'test-enterprise-b-verification'
         where id = ?
        """,
        (other_enterprise["id"],),
    )
    other_connector = container.managed_channel_service.create_dingtalk(
        DingTalkApplicationInput(
            name="隔离企业 B 应用",
            client_id="tenant-b-client",
            client_secret="tenant-b-client-secret",
            dingtalk_enterprise_id=str(other_enterprise["id"]),
        ),
        actor_id=ADMIN_ID,
        enabled=True,
    )
    isolated = container.identity_repository.bind_dingtalk_identity(
        user_id=str(second["id"]),
        dingtalk_enterprise_id=str(other_enterprise["id"]),
        external_subject_id="staff-shared",
        display_name="共享 Staff B",
        source_connector_id=str(other_connector["id"]),
        source_ingress_event_id="",
        observed_at="2026-08-03T00:00:00+00:00",
        replace_current=False,
    )
    assert isolated["user_id"] == second["id"]
    assert (
        container.identity_service.resolve_external(
            ExternalIdentityDescriptor(
                provider="dingtalk",
                tenant_code=str(default_enterprise["id"]),
                dingtalk_enterprise_id=str(default_enterprise["id"]),
                external_subject_id="staff-shared",
                connector_id="connector-dingtalk-stream-default",
            )
        ).user_id
        == first["id"]
    )
    assert (
        container.identity_service.resolve_external(
            ExternalIdentityDescriptor(
                provider="dingtalk",
                tenant_code=str(other_enterprise["id"]),
                dingtalk_enterprise_id=str(other_enterprise["id"]),
                external_subject_id="staff-shared",
                connector_id=str(other_connector["id"]),
            )
        ).user_id
        == second["id"]
    )
    with pytest.raises(PermissionDenied):
        container.identity_service.resolve_external(
            ExternalIdentityDescriptor(
                provider="dingtalk",
                tenant_code="unknown-enterprise",
                dingtalk_enterprise_id="unknown-enterprise",
                external_subject_id="staff-shared",
            )
        )

    before_jobs = container.agent_repository.count_rows("agent_job")
    before_queue = len(container.message_bus.jobs) if container.message_bus else 0
    denied = container.dingtalk_stream_message_service.handle_callback(
        payload={
            "conversationId": "conversation-unknown",
            "senderStaffId": "unknown-staff",
            "senderCorpId": "corp-test-enterprise",
            "chatbotCorpId": "corp-test-enterprise",
            "msgId": "message-unknown",
            "text": {"content": "check status"},
        },
        correlation_id="correlation-unknown",
    )
    assert denied.accepted is False
    assert denied.ack_status == "OK"
    assert container.agent_repository.count_rows("agent_job") == before_jobs
    assert (len(container.message_bus.jobs) if container.message_bus else 0) == before_queue

    secret_marker = "https://secret.example/session-webhook"
    container.dingtalk_stream_message_service.handle_callback(
        payload={
            "conversationId": "conversation-sensitive",
            "senderStaffId": "unknown-staff",
            "senderCorpId": "corp-test-enterprise",
            "chatbotCorpId": "corp-test-enterprise",
            "msgId": "message-sensitive",
            "sessionWebhook": secret_marker,
            "accessToken": "super-sensitive-token",
            "text": {"content": "check status"},
        },
        correlation_id="correlation-sensitive",
    )
    audit_text = json.dumps(
        container.database.execute("select payload_summary from audit_event"),
        ensure_ascii=False,
    )
    assert secret_marker not in audit_text
    assert "super-sensitive-token" not in audit_text
