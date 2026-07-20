from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import replace

import pytest

from app.bootstrap import build_test_container
from app.shared.config import IdentitySettings
from app.shared.exceptions import PermissionDenied
from app.modules.webhook.domain.models import config_hash
from backend.tests.helpers import test_settings as build_test_settings


PUBLIC_ID = "wh_local_grafana_default_00000000000000000001"


def _container():
    settings = replace(
        build_test_settings(),
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            published_agent_runtime_enabled=True,
            permission_shadow_mode=False,
            cookie_secure=False,
        ),
    )
    return build_test_container(settings, migrate=True, seed=True)


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


def _receive(c, payload: dict[str, object], *, token: str = "test-grafana-token"):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return c.webhook_ingress_service.receive(
        public_id=PUBLIC_ID,
        raw_body=raw,
        content_type="application/json",
        headers={"authorization": f"Bearer {token}"},
        correlation_id="correlation-webhook-test",
        remote_address="192.0.2.1",
    )


def test_firing_is_persisted_then_dispatches_one_pinned_agent_job() -> None:
    c = _container()
    acknowledgement = _receive(c, _firing())
    assert acknowledgement.accepted is True
    assert acknowledgement.status == "ACCEPTED"
    assert len(c.message_bus.webhook_events) == 0
    event = c.webhook_event_repository.get(acknowledgement.event_id)
    assert event["job_id"] is None
    assert event["normalized_event"]["delivery"] == {
        "connector_id": "connector-dingtalk-webhook-default",
        "options": {},
        "target": {"webhook_id": "grafana-alert"},
        "type": "dingtalk_webhook_robot",
    }
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
    assert job.reply_route["target"] == {"webhook_id": "grafana-alert"}
    assert len(c.message_bus.jobs) == 1

    # RabbitMQ/outbox and dispatcher redelivery remain idempotent.
    c.webhook_dispatcher.handle(queued)
    duplicate = _receive(c, _firing())
    assert duplicate.duplicate is True
    assert duplicate.event_id == acknowledgement.event_id
    assert c.agent_repository.count_rows("agent_job") == 1
    assert c.agent_repository.count_rows("webhook_outbox") == 1


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
    event = c.database.execute_one(
        "select * from webhook_event where status = 'REJECTED_AUTH'"
    )
    assert event
    stored = json.dumps(event, ensure_ascii=False)
    assert event["payload_hash"] == hashlib.sha256(raw).hexdigest()
    assert "Order API is returning 500" not in stored
    assert "wrong-token" not in stored
    assert "192.0.2.1" not in stored


def test_hmac_authentication_rejects_replay() -> None:
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
    revision_config["agent"] = {
        "code": snapshot["agent"]["code"],
        "publication_id": snapshot["agent"]["publication_id"],
    }
    c.database.execute(
        """
        update webhook_trigger_publication
        set snapshot_json = ?, config_hash = ? where id = ?
        """,
        (json.dumps(snapshot, sort_keys=True), config_hash(revision_config), publication["id"]),
    )
    raw = json.dumps(_firing("hmac-group"), separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        b"test-grafana-token", timestamp.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    headers = {
        "x-webhook-timestamp": timestamp,
        "x-webhook-nonce": "nonce-1",
        "x-webhook-signature": signature,
    }
    first = c.webhook_ingress_service.receive(
        public_id=PUBLIC_ID,
        raw_body=raw,
        content_type="application/json",
        headers=headers,
    )
    assert first.accepted is True
    with pytest.raises(PermissionDenied) as replay:
        c.webhook_ingress_service.receive(
            public_id=PUBLIC_ID,
            raw_body=raw,
            content_type="application/json",
            headers=headers,
        )
    assert replay.value.error_code == "webhook_replay_detected"
