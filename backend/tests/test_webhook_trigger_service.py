from __future__ import annotations

import json

import pytest

from app.modules.webhook.application import TriggerValidator, WebhookMapper, WebhookTriggerService
from app.modules.webhook.infrastructure import WebhookTriggerRepository
from app.shared.exceptions import NonRetryableExecutionError, PermissionDenied
from backend.tests.helpers import container


ADMIN_ID = "user_local_admin"


def _service(monkeypatch: pytest.MonkeyPatch) -> tuple[object, WebhookTriggerService]:
    monkeypatch.setenv("GRAFANA_WEBHOOK_TOKEN", "managed-test-token")
    c = container()
    for action in ("read", "edit", "publish", "rotate", "manage_service_account"):
        c.identity_repository.upsert_policy(
            policy_id=f"policy-admin-webhook-{action}",
            subject_type="role",
            subject_code="platform-admin",
            resource_type="webhook_trigger",
            resource_code="*",
            action=action,
            effect="allow",
        )
    c.database.execute(
        """
        insert into agent_channel_binding
          (id, publication_id, direction, connector_id, config_json, created_at)
        values ('binding-default-ingress-grafana-test',
                'agent_publication_default_v1', 'ingress',
                'connector-grafana-default', '{}', CURRENT_TIMESTAMP)
        on conflict(publication_id, direction, connector_id) do nothing
        """
    )
    repository = WebhookTriggerRepository(c.database)
    validator = TriggerValidator(
        repository=repository,
        identity_repository=c.identity_repository,
        connector_registry=c.connector_registry,
        agent_config_service=c.agent_config_service,
        authorization=c.authorization_evaluator,
    )
    service = WebhookTriggerService(
        repository=repository,
        identity_repository=c.identity_repository,
        authorization=c.authorization_evaluator,
        audit_service=c.audit_service,
        validator=validator,
        mapper=WebhookMapper(),
    )
    return c, service


def _config() -> dict[str, object]:
    return {
        "schema_version": 1,
        "adapter": "grafana_alertmanager_v1",
        "authentication": {
            "type": "bearer_v1",
            "secret_ref": "env:GRAFANA_WEBHOOK_TOKEN",
        },
        "mapping": {
            "variables": {"summary": "/commonAnnotations/summary"},
            "message_template": "Diagnose this firing alert: {summary}",
            "filters": [],
        },
        "routing": {
            "project_code": {"mode": "fixed", "value": "default"},
            "environment": {"mode": "fixed", "value": "prod"},
            "base": {"mode": "fixed", "value": "guanlan"},
            "workshop": {"mode": "fixed", "value": "assembly"},
            "service": {"mode": "fixed", "value": "order-service"},
        },
        "agent": {
            "code": "default-diagnostic-agent",
            "publication_id": "agent_publication_default_v1",
        },
        "delivery": {
            "type": "dingtalk_enterprise_robot",
            "connector_id": "connector-dingtalk-enterprise-default",
            "target": {"open_conversation_id": "test-alert-group"},
        },
        "idempotency": {"cooldown_seconds": 300},
        "limits": {"requests_per_minute": 60, "max_in_flight": 10, "max_alerts": 20},
    }


def _grant_runtime_permissions(c: object, service_account_id: str) -> None:
    repository = c.identity_repository
    for resource_type, resource_code in (
        ("agent", "default-diagnostic-agent"),
        ("project", "default"),
        ("tool", "*"),
    ):
        repository.upsert_policy(
            policy_id=f"policy-{service_account_id}-{resource_type}",
            subject_type="user",
            subject_code=service_account_id,
            resource_type=resource_type,
            resource_code=resource_code,
            action="use",
            effect="allow",
        )


def test_trigger_lifecycle_uses_dedicated_service_account_and_pinned_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, service = _service(monkeypatch)
    before_users = c.agent_repository.count_rows("app_user")
    created = service.create(
        actor_id=ADMIN_ID,
        code="grafana-orders",
        name="Grafana Orders",
        trigger_type="grafana",
        connector_id="connector-grafana-default",
        config=_config(),
    )
    definition = created["definition"]
    draft = created["draft"]
    service_account = created["service_account"]
    assert c.agent_repository.count_rows("app_user") == before_users + 1
    assert service_account["account_type"] == "service"
    assert service_account["username"] == "svc-webhook-grafana-orders"
    assert c.identity_repository.policies_for_principals(
        user_id=str(service_account["id"]),
        role_codes=(),
        resource_type="tool",
        resource_code="query_database",
        action="use",
    ) == []

    invalid = service.validate_revision(
        actor_id=ADMIN_ID,
        code="grafana-orders",
        revision_id=str(draft["id"]),
    )
    assert invalid["validation"]["valid"] is False
    assert {item["field"] for item in invalid["validation"]["errors"]} >= {
        "service_account",
        "routing.project_code",
    }

    _grant_runtime_permissions(c, str(service_account["id"]))
    validated = service.validate_revision(
        actor_id=ADMIN_ID,
        code="grafana-orders",
        revision_id=str(draft["id"]),
    )
    assert validated["validation"]["valid"] is True
    assert "query_database" in validated["validation"]["effective_read_only_tools"]

    before_events = c.agent_repository.count_rows("webhook_event")
    preview = service.preview(
        actor_id=ADMIN_ID,
        code="grafana-orders",
        revision_id=str(draft["id"]),
        sample_payload={
            "status": "firing",
            "groupKey": "orders-prod",
            "commonAnnotations": {"summary": "Order API is returning 500"},
            "alerts": [{"fingerprint": "abc", "status": "firing"}],
        },
    )
    assert preview["side_effects"] is False
    assert preview["dedup_key"] == "grafana:orders-prod:firing"
    assert preview["routing"]["base"] == "guanlan"
    assert "Order API" in preview["message"]
    assert c.agent_repository.count_rows("webhook_event") == before_events

    publication = service.publish(
        actor_id=ADMIN_ID,
        code="grafana-orders",
        revision_id=str(draft["id"]),
    )
    assert publication["agent_publication_id"] == "agent_publication_default_v1"
    assert publication["agent_config_hash"]
    assert publication["snapshot"]["service_account_id"] == service_account["id"]
    assert "secret_ref" in json.dumps(publication["snapshot"])
    assert "managed-test-token" not in json.dumps(publication["snapshot"])

    with pytest.raises(NonRetryableExecutionError):
        service.repository.save_draft(
            trigger_id=str(definition["id"]),
            expected_revision=0,
            config=draft["config"],
            config_hash=str(draft["config_hash"]),
            actor_id=ADMIN_ID,
        )

    current = service.get(actor_id=ADMIN_ID, code="grafana-orders")
    old_public_id = current["definition"]["public_id"]
    rotated = service.rotate_public_id(
        actor_id=ADMIN_ID,
        code="grafana-orders",
        expected_revision=int(current["definition"]["revision"]),
        confirm=True,
    )
    assert rotated["public_id"] != old_public_id
    assert service.repository.get_definition_by_public_id(old_public_id) is None


def test_trigger_rejects_secret_values_scripts_and_unbounded_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _c, service = _service(monkeypatch)
    bad = _config()
    bad["token"] = "plain-secret"
    with pytest.raises(NonRetryableExecutionError) as secret_error:
        service.create(
            actor_id=ADMIN_ID,
            code="bad-secret",
            name="Bad Secret",
            trigger_type="generic",
            connector_id="connector-grafana-default",
            config=bad,
        )
    assert secret_error.value.error_code == "validation_failed"

    generic = _config()
    generic["adapter"] = "generic_json_v1"
    generic["mapping"] = {
        "variables": {"message": "/message"},
        "message_template": "{message}",
        "event_id_pointer": "/event_id",
        "filters": [{"pointer": "/status", "operator": "javascript", "value": "open"}],
    }
    generic["routing"]["base"] = {
        "mode": "extract",
        "pointer": "/base",
        "allowed_values": [],
    }
    created = service.create(
        actor_id=ADMIN_ID,
        code="bad-mapping",
        name="Bad Mapping",
        trigger_type="generic",
        connector_id="connector-grafana-default",
        config=generic,
    )
    validated = service.validate_revision(
        actor_id=ADMIN_ID,
        code="bad-mapping",
        revision_id=str(created["draft"]["id"]),
    )
    fields = {error["field"] for error in validated["validation"]["errors"]}
    assert "mapping.filters.0.operator" in fields
    assert "routing.base.allowed_values" in fields


def test_webhook_management_requires_independent_rbac_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, service = _service(monkeypatch)
    viewer = c.identity_repository.create_user(
        username="webhook-viewer", display_name="Webhook Viewer"
    )
    with pytest.raises(PermissionDenied):
        service.list(actor_id=str(viewer["id"]))
