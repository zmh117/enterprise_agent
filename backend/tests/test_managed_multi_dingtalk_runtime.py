from __future__ import annotations

import json
from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.modules.managed_channel import ChannelOutboxPublisher
from app.modules.managed_channel.api.controller import _RUNTIME_RATE_WINDOWS
from app.modules.managed_channel.domain import (
    ChannelIngressSubmission,
    DingTalkApplicationInput,
    RuntimeConnectorState,
)
from app.shared.config import ManagedChannelSettings, Settings


def _container():
    return build_test_container(
        Settings(
            database_dsn="sqlite:///:memory:",
            app_config_master_key="managed-channel-test-key",
        ),
        migrate=True,
    )


def _create(container, client_id: str):
    return container.managed_channel_service.create_dingtalk(
        DingTalkApplicationInput(
            name=f"机器人 {client_id}",
            client_id=client_id,
            client_secret=f"secret-{client_id}",
            tenant_code="default",
        ),
        actor_id="test-admin",
        enabled=True,
    )


def _submission(connector_id: str, event_id: str) -> ChannelIngressSubmission:
    return ChannelIngressSubmission(
        connector_id=connector_id,
        external_event_id=event_id,
        correlation_id=f"correlation-{connector_id}",
        normalized_event={
            "conversationId": "group-1",
            "conversationType": "2",
            "senderStaffId": "user-1",
            "msgId": event_id,
            "robotCode": connector_id,
            "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession?token=private",
            "text": {"content": "查询问题"},
        },
        safe_summary={"msgtype": "text"},
        payload_hash=f"hash-{connector_id}-{event_id}",
        request_bytes=256,
    )


def test_managed_channels_keep_secrets_out_of_admin_reads_and_runtime_states_are_independent():
    container = _container()
    first = _create(container, "ding-first")
    second = _create(container, "ding-second")
    assert "secret" not in str(first).lower().replace("secret_configured", "")
    assert first["secret_configured"] is True

    lease = container.runtime_control_service.acquire("runtime-one")
    assert lease is not None
    assert container.runtime_control_service.acquire("runtime-two") is None
    snapshot = container.runtime_control_service.desired_snapshot(
        "runtime-one", lease["lease_token"]
    )
    assert {item["client_id"] for item in snapshot["connectors"]} == {
        "ding-first",
        "ding-second",
    }

    container.runtime_control_service.report_states(
        "runtime-one",
        lease["lease_token"],
        [
            RuntimeConnectorState(
                connector_id=first["id"],
                revision=first["revision"],
                status="AUTH_FAILED",
                connected=False,
                registered=False,
                error_code="auth_failed",
                error_summary="credentials rejected",
            ),
            RuntimeConnectorState(
                connector_id=second["id"],
                revision=second["revision"],
                status="REGISTERED",
                connected=True,
                registered=True,
            ),
        ],
    )
    assert container.managed_channel_service.get_channel(first["id"])["runtime"][
        "status"
    ] == "AUTH_FAILED"
    assert container.managed_channel_service.get_channel(second["id"])["runtime"][
        "status"
    ] == "READY"


def test_channel_inbox_deduplicates_per_connector_and_encrypts_reply_credential():
    container = _container()
    first = _create(container, "ding-first")
    second = _create(container, "ding-second")
    lease = container.runtime_control_service.acquire("runtime-one")
    assert lease is not None

    first_event, first_created = container.runtime_control_service.receive(
        "runtime-one", lease["lease_token"], _submission(first["id"], "same-message")
    )
    duplicate, duplicate_created = container.runtime_control_service.receive(
        "runtime-one", lease["lease_token"], _submission(first["id"], "same-message")
    )
    second_event, second_created = container.runtime_control_service.receive(
        "runtime-one", lease["lease_token"], _submission(second["id"], "same-message")
    )

    assert first_created is True
    assert duplicate_created is False
    assert first_event["id"] == duplicate["id"]
    assert second_created is True
    assert second_event["id"] != first_event["id"]
    assert "sessionWebhook" not in first_event["normalized_event"]
    assert "private" not in str(first_event)
    assert first_event["reply_credential_ciphertext"]
    outbox_count = container.database.execute_one(
        "select count(*) as count from channel_ingress_outbox"
    )
    assert outbox_count and int(outbox_count["count"]) == 2


@dataclass
class FlakyPublisher:
    failures: int = 1
    published: list[tuple[str, str]] | None = None

    def __post_init__(self) -> None:
        self.published = []

    def publish_channel_event(self, event_id: str, correlation_id: str) -> None:
        if self.failures:
            self.failures -= 1
            raise RuntimeError("broker unavailable")
        assert self.published is not None
        self.published.append((event_id, correlation_id))


def test_outbox_recovers_after_broker_failure_without_secret_in_queue_payload():
    container = _container()
    channel = _create(container, "ding-first")
    lease = container.runtime_control_service.acquire("runtime-one")
    assert lease is not None
    event, _ = container.runtime_control_service.receive(
        "runtime-one", lease["lease_token"], _submission(channel["id"], "message-1")
    )
    publisher = FlakyPublisher()
    outbox = ChannelOutboxPublisher(
        repository=container.managed_channel_repository,
        publisher=publisher,  # type: ignore[arg-type]
        max_attempts=3,
        retry_base_seconds=0,
    )
    assert outbox.publish_pending() == {"published": 0, "failed": 1}
    container.database.execute(
        "update channel_ingress_outbox set next_attempt_at = '' where status = 'pending'"
    )
    assert outbox.publish_pending() == {"published": 1, "failed": 0}
    assert publisher.published == [(event["id"], event["correlation_id"])]


def test_restart_changes_only_selected_connector_revision():
    container = _container()
    first = _create(container, "ding-first")
    second = _create(container, "ding-second")
    restarted = container.managed_channel_service.restart(
        first["id"],
        expected_revision=first["revision"],
        actor_id="test-admin",
    )
    assert restarted["revision"] == first["revision"] + 1
    assert (
        container.managed_channel_service.get_channel(second["id"])["revision"]
        == second["revision"]
    )


def test_updating_bootstrap_connector_migrates_env_secret_to_managed_secret():
    container = _container()
    timestamp = "2026-07-26T00:00:00+00:00"
    container.database.execute(
        """
        insert into integration_connector
          (id, connector_type, name, base_url, enabled, metadata,
           allow_ingress, allow_delivery, secret_ref, endpoint_ref,
           host_allowlist, revision, created_at, updated_at, deleted)
        values (
          'connector-bootstrap-dingtalk', 'dingtalk_enterprise_stream',
          '旧启动配置机器人', '', 1,
          '{"client_id_ref":"env:DINGTALK_CLIENT_ID","tenant_code":"default"}',
          1, 0, 'env:DINGTALK_CLIENT_SECRET', '', '', 1, ?, ?, 0
        )
        """,
        (timestamp, timestamp),
    )

    updated = container.managed_channel_service.update_dingtalk(
        "connector-bootstrap-dingtalk",
        DingTalkApplicationInput(
            name="受管钉钉机器人",
            client_id="ding-managed",
            client_secret="replacement-secret",
            tenant_code="default",
        ),
        expected_revision=1,
        actor_id="test-admin",
        rotate_secret=True,
    )

    row = container.database.execute_one(
        "select secret_ref from integration_connector where id = ?",
        ("connector-bootstrap-dingtalk",),
    )
    assert row is not None
    secret_ref = str(row["secret_ref"])
    assert secret_ref.startswith("secret://platform/dingtalk-")
    assert (
        container.managed_channel_service.secret_provider.resolve(secret_ref)
        == "replacement-secret"
    )
    assert updated["client_id"] == "ding-managed"
    assert updated["revision"] == 2
    assert "replacement-secret" not in str(updated)


def test_internal_runtime_api_requires_service_auth_and_rate_limits_safe_errors():
    settings = Settings(
        database_dsn="sqlite:///:memory:",
        app_config_master_key="managed-channel-test-key",
        managed_channels=ManagedChannelSettings(
            runtime_auth_token="runtime-test-token",
            internal_requests_per_minute=1,
        ),
    )
    container = build_test_container(settings, migrate=True)
    _RUNTIME_RATE_WINDOWS.clear()
    with TestClient(
        create_app(settings, container_factory=lambda _: container)
    ) as client:
        unauthorized = client.post(
            "/api/internal/dingtalk-runtime/lease/acquire",
            json={"runtime_id": "runtime-one", "lease_token": ""},
        )
        assert unauthorized.status_code == 401
        assert unauthorized.json()["detail"]["code"] == "runtime_auth_failed"
        assert "runtime-test-token" not in unauthorized.text

        headers = {"Authorization": "Bearer runtime-test-token"}
        accepted = client.post(
            "/api/internal/dingtalk-runtime/lease/acquire",
            headers=headers,
            json={"runtime_id": "runtime-one", "lease_token": ""},
        )
        assert accepted.status_code == 200
        limited = client.post(
            "/api/internal/dingtalk-runtime/lease/renew",
            headers=headers,
            json={"runtime_id": "runtime-one", "lease_token": "invalid"},
        )
        assert limited.status_code == 429
        assert limited.json()["detail"] == {
            "code": "runtime_rate_limited",
            "message": "Runtime 请求过于频繁",
        }
        assert "runtime-test-token" not in limited.text


def test_internal_runtime_inbox_accepts_compact_utf8_json_byte_count():
    settings = Settings(
        database_dsn="sqlite:///:memory:",
        app_config_master_key="managed-channel-test-key",
        managed_channels=ManagedChannelSettings(
            runtime_auth_token="runtime-test-token",
            internal_requests_per_minute=100,
        ),
    )
    container = build_test_container(settings, migrate=True)
    channel = _create(container, "ding-compact-json")
    _RUNTIME_RATE_WINDOWS.clear()
    normalized_event = {
        "conversationId": "group-中文",
        "conversationType": "2",
        "senderStaffId": "user-1",
        "msgId": "message-compact-json",
        "text": {"content": "帮我查询嵌套消息"},
    }
    compact = json.dumps(
        normalized_event,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    serializer_drift_bytes = len(compact) - 1

    with TestClient(
        create_app(settings, container_factory=lambda _: container)
    ) as client:
        headers = {"Authorization": "Bearer runtime-test-token"}
        acquired = client.post(
            "/api/internal/dingtalk-runtime/lease/acquire",
            headers=headers,
            json={"runtime_id": "runtime-one", "lease_token": ""},
        )
        assert acquired.status_code == 200
        lease_token = acquired.json()["lease"]["lease_token"]
        accepted = client.post(
            "/api/internal/dingtalk-runtime/inbox",
            headers=headers,
            json={
                "runtime_id": "runtime-one",
                "lease_token": lease_token,
                "connector_id": channel["id"],
                "external_event_id": "message-compact-json",
                "correlation_id": "correlation-compact-json",
                "normalized_event": normalized_event,
                "safe_summary": {"msgtype": "text", "hasText": True},
                "payload_hash": "",
                "request_bytes": serializer_drift_bytes,
            },
        )
        assert accepted.status_code == 200
        assert accepted.json()["created"] is True
        stored = container.database.execute_one(
            """
            select request_bytes, status
            from channel_ingress_event
            where external_event_id = ?
            """,
            ("message-compact-json",),
        )
        assert stored is not None
        assert int(stored["request_bytes"]) == len(compact)
        assert stored["status"] == "ACCEPTED"


def test_managed_channel_audit_contains_no_client_secret():
    container = _container()
    _create(container, "ding-audit")
    events = container.database.execute(
        """
        select event_type, summary, payload_summary
        from audit_event
        where event_type = 'managed_channel.created'
        """
    )
    assert len(events) == 1
    serialized = str(events[0])
    assert "secret-ding-audit" not in serialized
    assert "client_secret" not in serialized


def test_webhook_connector_options_are_application_independent_and_ingress_only():
    container = _container()
    timestamp = "2026-07-26T00:00:00+00:00"
    rows = [
        (
            "connector-webhook-ingress",
            "grafana_alert",
            "Grafana 告警入口",
            1,
            1,
            0,
        ),
        (
            "connector-dingtalk-ingress",
            "dingtalk_enterprise_stream",
            "钉钉 Stream",
            1,
            1,
            0,
        ),
        (
            "connector-delivery-only",
            "dingtalk_webhook_robot",
            "钉钉投递",
            1,
            0,
            1,
        ),
        (
            "connector-disabled-ingress",
            "grafana_alert",
            "停用入口",
            0,
            1,
            0,
        ),
    ]
    for connector_id, connector_type, name, enabled, ingress, delivery in rows:
        container.database.execute(
            """
            insert into integration_connector
              (id, connector_type, name, base_url, enabled, metadata,
               allow_ingress, allow_delivery, secret_ref, endpoint_ref,
               host_allowlist, revision, created_at, updated_at, deleted)
            values (?, ?, ?, '', ?, '{}', ?, ?, '', '', '', 1, ?, ?, 0)
            """,
            (
                connector_id,
                connector_type,
                name,
                enabled,
                ingress,
                delivery,
                timestamp,
                timestamp,
            ),
        )

    assert container.managed_channel_service.webhook_connector_options() == [
        {
            "id": "connector-webhook-ingress",
            "name": "Grafana 告警入口",
            "connector_type": "grafana_alert",
            "revision": 1,
        }
    ]
