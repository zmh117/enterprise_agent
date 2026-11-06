from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from app.bootstrap import build_test_container
from app.shared.config import ConversationSettings, IdentitySettings
from app.shared.exceptions import PermissionDenied
from app.modules.webhook.domain.models import config_hash
from backend.tests.helpers import (
    activate_webhook_test_application,
    publish_pending_agent_jobs,
    test_settings as build_test_settings,
)


PUBLIC_ID = "wh_local_grafana_default_00000000000000000001"


def _container(*, webhook_result=False):
    settings = replace(
        build_test_settings(),
        conversation=ConversationSettings(enabled=True),
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            published_agent_runtime_enabled=True,
            cookie_secure=False,
        ),
    )
    runtime = build_test_container(
        settings,
        migrate=True,
        seed=True,
    )
    from backend.tests.support.webhooks import prepare_test_webhook

    prepare_test_webhook(runtime)
    trigger = runtime.database.execute_one(
        """
        select d.id, d.service_account_id
          from webhook_trigger_publication p
          join webhook_trigger_definition d on d.id = p.trigger_id
         where p.id = ?
        """,
        ("webhook_trigger_publication_grafana_v1",),
    )
    assert trigger is not None
    capabilities = tuple(
        sorted(
            runtime.agent_config_service.repository.publication_tools(
                "agent_publication_default_v1"
            )
        )
    )
    activate_webhook_test_application(
        runtime,
        code="grafana-strict-runtime",
        webhook_definition_id=str(trigger["id"]),
        service_account_user_id=str(trigger["service_account_id"]),
        ingress_connector_id="connector-grafana-default",
        delivery_connector_id=(
            "connector-dingtalk-stream-default"
            if webhook_result
            else "connector-dingtalk-enterprise-default"
        ),
        delivery_type="dingtalk_private" if webhook_result else "dingtalk_group",
        delivery_target_reference="" if webhook_result else "test-alert-group",
        capabilities=capabilities,
    )
    return runtime


def _firing(group_key: str = "orders-prod") -> dict[str, object]:
    return {
        "status": "firing",
        "groupKey": group_key,
        "commonLabels": {
            "ea_project_code": "default",
            "ea_environment": "prod",
            "ea_base": "guanlan",
            "ea_workshop": "GL001",
            "ea_service": "order-service",
            "delivery": "https://attacker.invalid/hook",
            "agent": "untrusted-agent",
            "tools": "run_shell",
        },
        "commonAnnotations": {"summary": "Order API is returning 500"},
        "alerts": [{"status": "firing", "fingerprint": "abc-123"}],
    }


def _receive(
    c,
    payload: dict[str, object],
    *,
    token: str = "test-grafana-token-0123456789abcdefABCDEF",
):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return c.webhook_ingress_service.receive(
        public_id=PUBLIC_ID,
        raw_body=raw,
        content_type="application/json",
        headers={"authorization": f"Bearer {token}"},
        correlation_id="correlation-webhook-test",
        remote_address="192.0.2.1",
    )


def test_webhook_snapshot_does_not_own_agent_or_delivery() -> None:
    c = _container()
    snapshot = c.webhook_trigger_repository.get_publication(
        "webhook_trigger_publication_grafana_v1"
    )["snapshot"]
    assert "agent" not in snapshot and "delivery" not in snapshot
    received = _receive(c, _firing())
    event = c.webhook_event_repository.get(received.event_id)
    assert event["agent_publication_id"] == "agent_publication_default_v1"
    assert event["application_publication_id"]


def test_firing_is_persisted_then_dispatches_one_pinned_agent_job() -> None:
    c = _container()
    acknowledgement = _receive(c, _firing())
    assert acknowledgement.accepted is True
    assert acknowledgement.status == "ACCEPTED"
    assert len(c.message_bus.webhook_events) == 0
    event = c.webhook_event_repository.get(acknowledgement.event_id)
    assert event["job_id"] is None
    assert event["normalized_event"]["delivery"] == {"type": "none"}
    assert "attacker.invalid" not in json.dumps(event["normalized_event"])
    assert "run_shell" not in json.dumps(event["normalized_event"])

    result = c.webhook_outbox_publisher.publish_pending()
    assert result.published == 1
    assert len(c.message_bus.webhook_events) == 1
    queued = c.message_bus.webhook_events[0]
    assert set(vars(queued)) == {"webhook_event_id", "correlation_id"}

    c.message_bus.consume_webhook_events(c.webhook_dispatcher.handle)
    dispatched = c.webhook_event_repository.get(acknowledgement.event_id)
    assert dispatched["status"] == "JOB_CREATED"
    job = c.agent_repository.get_job(str(dispatched["job_id"]))
    assert job.requester_id == "user_webhook_grafana_default"
    assert job.internal_user_id == "user_webhook_grafana_default"
    assert job.agent_publication_id == "agent_publication_default_v1"
    assert job.agent_revision == 1
    assert job.webhook_event_id == acknowledgement.event_id
    assert job.webhook_trigger_publication_id == "webhook_trigger_publication_grafana_v1"
    assert job.reply_route["target"] == {"open_conversation_id": "test-alert-group"}
    assert job.business_application_code == ("grafana-strict-runtime")
    publish_pending_agent_jobs(c)
    assert len(c.message_bus.jobs) == 1

    # RabbitMQ/outbox and dispatcher redelivery remain idempotent.
    c.webhook_dispatcher.handle(queued)
    duplicate = _receive(c, _firing())
    assert duplicate.duplicate is True
    assert duplicate.event_id == acknowledgement.event_id
    assert c.agent_repository.count_rows("agent_job") == 1
    assert c.agent_repository.count_rows("webhook_outbox") == 1


def test_dispatch_fails_closed_when_pinned_agent_hash_does_not_match() -> None:
    c = _container()
    acknowledgement = _receive(c, _firing("mismatched-agent-publication"))
    publication = c.webhook_trigger_repository.get_publication(
        "webhook_trigger_publication_grafana_v1"
    )
    snapshot = publication["snapshot"]
    snapshot["role_ids"] = ["tampered"]
    c.database.execute(
        "update webhook_trigger_publication set snapshot_json = ? where id = ?",
        (json.dumps(snapshot, sort_keys=True), publication["id"]),
    )

    assert c.webhook_outbox_publisher.publish_pending().published == 1
    c.message_bus.consume_webhook_events(c.webhook_dispatcher.handle)

    event = c.webhook_event_repository.get(acknowledgement.event_id)
    assert event["status"] == "DISPATCH_FAILED"
    assert event["error_summary"] == "Webhook 发布配置已失效"
    assert event["job_id"] is None
    assert c.agent_repository.count_rows("agent_job") == 0


def test_distinct_webhook_events_use_isolated_sessions_even_when_continuity_is_enabled() -> None:
    c = _container()
    first = _receive(c, _firing("webhook-session-one"))
    second_payload = _firing("webhook-session-two")
    second_payload["alerts"] = [{"status": "firing", "fingerprint": "webhook-session-two"}]
    second = _receive(c, second_payload)
    assert first.event_id != second.event_id

    assert c.webhook_outbox_publisher.publish_pending().published == 2
    c.message_bus.consume_webhook_events(c.webhook_dispatcher.handle)
    first_event = c.webhook_event_repository.get(first.event_id)
    second_event = c.webhook_event_repository.get(second.event_id)
    first_job = c.agent_repository.get_job(str(first_event["job_id"]))
    second_job = c.agent_repository.get_job(str(second_event["job_id"]))
    assert first_job.session_id != second_job.session_id


def test_resolved_is_recorded_as_ignored_without_outbox_or_job() -> None:
    c = _container()
    acknowledgement = _receive(c, {"status": "resolved", "groupKey": "orders-prod"})
    assert acknowledgement.accepted is False
    assert acknowledgement.ignored is True
    assert acknowledgement.reason == "not_firing"
    assert c.agent_repository.count_rows("webhook_outbox") == 0
    assert c.agent_repository.count_rows("agent_job") == 0


def test_auth_failure_records_only_hash_size_and_safe_remote_hash() -> None:
    c = _container()
    payload = _firing("secret-body")
    raw = json.dumps(payload, separators=(",", ":")).encode()
    with pytest.raises(PermissionDenied) as denied:
        _receive(c, payload, token="wrong-token")
    assert denied.value.error_code == "webhook_auth_failed"
    event = c.database.execute_one("select * from webhook_event where status = 'REJECTED_AUTH'")
    assert event
    stored = json.dumps(event, ensure_ascii=False)
    assert event["payload_hash"] == hashlib.sha256(raw).hexdigest()
    assert "Order API is returning 500" not in stored
    assert "wrong-token" not in stored
    assert "192.0.2.1" not in stored


def test_disabled_platform_secret_fails_closed_before_job_or_outbox() -> None:
    c = _container()
    c.platform_config_service.secret_provider.disable_secret(
        code="grafana_webhook_token",
        actor_id="test-fixture",
    )
    with pytest.raises(PermissionDenied) as denied:
        _receive(c, _firing("empty-binding-secret"))
    assert denied.value.error_code == "webhook_disabled"
    assert c.agent_repository.count_rows("agent_job") == 0
    assert c.agent_repository.count_rows("webhook_outbox") == 0
    assert c.agent_repository.count_rows("webhook_event") == 0


def test_non_bearer_authentication_is_rejected_without_nonce_state() -> None:
    c = _container()
    publication = c.webhook_trigger_repository.get_publication(
        "webhook_trigger_publication_grafana_v1"
    )
    snapshot = publication["snapshot"]
    snapshot["authentication"] = {
        **snapshot["authentication"],
        "type": "hmac_sha256_v1",
    }
    revision_config = {
        key: value
        for key, value in snapshot.items()
        if key not in {"service_account_id", "source_connector_id"}
    }
    c.database.execute(
        """
        update webhook_trigger_publication
        set snapshot_json = ?, config_hash = ? where id = ?
        """,
        (json.dumps(snapshot, sort_keys=True), config_hash(revision_config), publication["id"]),
    )
    raw = json.dumps(_firing("hmac-group"), separators=(",", ":")).encode()
    with pytest.raises(PermissionDenied) as denied:
        c.webhook_ingress_service.receive(
            public_id=PUBLIC_ID,
            raw_body=raw,
            content_type="application/json",
            headers={"authorization": ("Bearer test-grafana-token-0123456789abcdefABCDEF")},
        )
    assert denied.value.error_code == "webhook_auth_failed"
    assert c.agent_repository.count_rows("webhook_replay_nonce") == 0


def test_dispatch_rejects_application_version_changed_after_acceptance():
    from backend.tests.test_webhook_result_recipients import _publish_private, robot

    c = _container()
    accepted = _receive(c, _firing("pinned-before-change"))
    _publish_private(c, robot(c), [])
    c.webhook_outbox_publisher.publish_pending()
    c.message_bus.consume_webhook_events(c.webhook_dispatcher.handle)
    event = c.webhook_event_repository.get(accepted.event_id)
    assert event["status"] == "DISPATCH_FAILED"
    assert event["error_summary"] == "事件接收后应用发布版本已变更，请重新触发"
    assert c.agent_repository.count_rows("agent_job") == 0


def test_unbound_webhook_cannot_be_saved_by_forging_application_request():
    from app.shared.exceptions import NonRetryableExecutionError

    c = _container()
    c.database.execute(
        "delete from agent_channel_binding where direction='ingress' and connector_id='connector-grafana-default'"
    )
    service = c.business_application_service
    detail = service.detail(actor_id="user_local_admin", code="grafana-strict-runtime")
    payload = dict(detail["draft"])
    payload["mcp_tools"] = []
    payload["triggers"] = [
        {"trigger_type": "webhook", "connector_id": "connector-grafana-default", "enabled": True}
    ]
    payload["deliveries"] = []
    with pytest.raises(NonRetryableExecutionError) as failure:
        service.save_draft(
            actor_id="user_local_admin",
            code="grafana-strict-runtime",
            expected_revision=detail["revision"],
            payload=payload,
        )
    assert "入口 Connector" in failure.value.safe_message


def test_revoke_role_access_before_dispatch_creates_no_job():
    c = _container()
    accepted = _receive(c, _firing("roles-revoked"))
    c.database.execute(
        "update rbac_user_role set status='disabled' where user_id='user_webhook_grafana_default'"
    )
    c.webhook_outbox_publisher.publish_pending()
    c.message_bus.consume_webhook_events(c.webhook_dispatcher.handle)
    assert c.webhook_event_repository.get(accepted.event_id)["status"] == "DISPATCH_FAILED"
    assert c.agent_repository.count_rows("agent_job") == 0
