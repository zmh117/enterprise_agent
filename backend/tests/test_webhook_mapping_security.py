from __future__ import annotations

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.webhook.application.mapping import WebhookMapper, json_pointer
from app.shared.config import WebhookSettings
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_unified_identity_rbac import unified_container, unified_settings


PUBLIC_ID = "wh_local_grafana_default_00000000000000000001"


def _generic_config() -> dict[str, object]:
    fixed = {"mode": "fixed", "value": ""}
    return {
        "adapter": "generic_json_v1",
        "authentication": {"type": "bearer_v1", "secret_ref": "env:UNUSED"},
        "mapping": {
            "variables": {"message": "/payload/a~1b/~0key", "url": "/callback_url"},
            "message_template": "Investigate {message} {url}",
            "event_id_pointer": "/items/0/id",
            "filters": [
                {"pointer": "/status", "operator": "in", "value": ["open", "firing"]},
                {"pointer": "/muted", "operator": "not_equals", "value": True},
            ],
        },
        "routing": {
            "project_code": {"mode": "fixed", "value": "default"},
            "environment": {
                "mode": "extract",
                "pointer": "/environment",
                "allowed_values": ["prod"],
            },
            "base": {"mode": "fixed", "value": "guanlan"},
            "workshop": fixed,
            "service": {"mode": "fixed", "value": "order-service"},
        },
        "agent": {"code": "default-diagnostic-agent", "publication_id": "agent-publication"},
        "delivery": {"type": "none", "connector_id": "", "target": {}},
        "idempotency": {"cooldown_seconds": 0},
        "limits": {"requests_per_minute": 60, "max_in_flight": 10, "max_alerts": 2},
    }


def test_json_pointer_template_filters_routing_and_redaction_are_bounded() -> None:
    mapper = WebhookMapper(max_message_chars=48, max_summary_chars=500)
    payload = {
        "items": [{"id": "event-1"}],
        "payload": {"a/b": {"~key": "database timeout"}},
        "callback_url": "https://attacker.invalid/override",
        "status": "open",
        "muted": False,
        "environment": "prod",
        "authorization": "Bearer should-never-be-returned",
    }
    assert json_pointer(payload, "/payload/a~1b/~0key") == "database timeout"

    mapped = mapper.map(config=_generic_config(), payload=payload)
    assert mapped.ignored is False
    assert mapped.external_event_id == "event-1"
    assert mapped.routing["environment"] == "prod"
    assert len(mapped.message) <= 48
    normalized = mapped.normalized_event(delivery={"type": "none"})
    assert normalized["variables"]["url"] == "***"
    serialized = json.dumps(mapped.safe_summary)
    assert "Bearer should-never-be-returned" not in serialized
    assert "attacker.invalid" not in serialized

    blocked = {**payload, "environment": "dev"}
    with pytest.raises(NonRetryableExecutionError) as denied:
        mapper.map(config=_generic_config(), payload=blocked)
    assert denied.value.error_code == "webhook_scope_denied"


def test_public_api_rejects_deep_and_oversized_json_without_persisting_body() -> None:
    settings = replace(
        unified_settings(),
        webhooks=WebhookSettings(max_body_bytes=256, max_json_depth=4, max_collection_items=20),
    )
    c = unified_container()
    c.webhook_ingress_service.settings = settings.webhooks
    with TestClient(create_app(settings, container_factory=lambda _: c)) as client:
        deep = {"status": "firing", "groupKey": "deep", "value": {"a": {"b": {"c": {}}}}}
        response = client.post(
            f"/webhooks/v1/{PUBLIC_ID}",
            json=deep,
            headers={"authorization": "Bearer test-grafana-token"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "webhook_payload_invalid"

        oversized_secret = "SENSITIVE-MARKER-" + "x" * 400
        oversized = client.post(
            f"/webhooks/v1/{PUBLIC_ID}",
            content=json.dumps({"status": "firing", "value": oversized_secret}),
            headers={
                "authorization": "Bearer test-grafana-token",
                "content-type": "application/json",
            },
        )
        assert oversized.status_code == 413
        assert oversized.json()["error"]["code"] == "webhook_payload_too_large"

        stored = json.dumps(c.database.execute("select * from webhook_event"), ensure_ascii=False)
        assert "SENSITIVE-MARKER" not in stored
