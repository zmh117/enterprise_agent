from __future__ import annotations

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.webhook.application.mapping import WebhookMapper
from app.shared.config import WebhookSettings
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_unified_identity_rbac import unified_container, unified_settings


PUBLIC_ID = "wh_local_grafana_default_00000000000000000001"


def _generic_config() -> dict[str, object]:
    return {"schema_version": 2, "adapter": "generic_json_v1"}


def test_fixed_generic_json_is_bounded_and_has_no_configuration_overrides() -> None:
    mapper = WebhookMapper(max_message_chars=48)
    mapped = mapper.map(
        config=_generic_config(), payload={"id": "event-1", "message": "database timeout"}
    )
    assert mapped.external_event_id == "event-1"
    assert mapped.routing == {} and mapped.variables == {}
    assert "database timeout" not in json.dumps(mapped.safe_summary)
    for payload in (
        {"id": "1", "message": "x", "delivery": {}},
        {"id": "1", "message": "x" * 49},
        {"id": "", "message": "x"},
        {"id": 1, "message": "x"},
    ):
        with pytest.raises(NonRetryableExecutionError):
            mapper.map(config=_generic_config(), payload=payload)


def test_public_api_rejects_deep_and_oversized_json_without_persisting_body() -> None:
    settings = replace(
        unified_settings(),
        webhooks=WebhookSettings(max_body_bytes=256, max_json_depth=4, max_collection_items=20),
    )
    c = unified_container()
    from backend.tests.support.webhooks import prepare_test_webhook

    prepare_test_webhook(c)
    c.platform_config_service.secret_provider.rotate_secret(
        code="grafana_webhook_token",
        value="test-grafana-token-0123456789abcdefABCDEF",
        actor_id="user_local_admin",
    )
    c.webhook_ingress_service.settings = settings.webhooks
    with TestClient(create_app(settings, container_factory=lambda _: c)) as client:
        deep = {"status": "firing", "groupKey": "deep", "value": {"a": {"b": {"c": {}}}}}
        response = client.post(
            f"/webhooks/v1/{PUBLIC_ID}",
            json=deep,
            headers={"authorization": "Bearer test-grafana-token-0123456789abcdefABCDEF"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "webhook_payload_invalid"

        oversized_secret = "SENSITIVE-MARKER-" + "x" * 400
        oversized = client.post(
            f"/webhooks/v1/{PUBLIC_ID}",
            content=json.dumps({"status": "firing", "value": oversized_secret}),
            headers={
                "authorization": ("Bearer test-grafana-token-0123456789abcdefABCDEF"),
                "content-type": "application/json",
            },
        )
        assert oversized.status_code == 413
        assert oversized.json()["error"]["code"] == "webhook_payload_too_large"

        stored = json.dumps(c.database.execute("select * from webhook_event"), ensure_ascii=False)
        assert "SENSITIVE-MARKER" not in stored
