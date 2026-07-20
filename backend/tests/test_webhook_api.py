from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import create_app
from backend.tests.test_unified_identity_rbac import (
    csrf_headers,
    login,
    unified_container,
    unified_settings,
)


PUBLIC_ID = "wh_local_grafana_default_00000000000000000001"


def _payload() -> dict[str, object]:
    return {
        "status": "firing",
        "groupKey": "api-route-test",
        "commonLabels": {
            "ea_project_code": "default",
            "ea_environment": "prod",
            "ea_base": "guanlan",
            "ea_workshop": "GL001",
            "ea_service": "order-service",
            "delivery_url": "https://attacker.invalid",
        },
        "commonAnnotations": {"summary": "API route alert"},
    }


def test_public_webhook_returns_202_and_stable_safe_errors() -> None:
    c = unified_container()
    with TestClient(create_app(unified_settings(), container_factory=lambda _: c)) as client:
        accepted = client.post(
            f"/webhooks/v1/{PUBLIC_ID}",
            json=_payload(),
            headers={"authorization": "Bearer test-grafana-token"},
        )
        assert accepted.status_code == 202, accepted.text
        body = accepted.json()
        assert body["accepted"] is True
        assert body["status"] == "ACCEPTED"
        assert body["event_id"]
        assert c.agent_repository.count_rows("agent_job") == 0
        assert len(c.message_bus.webhook_events) == 1

        duplicate = client.post(
            f"/webhooks/v1/{PUBLIC_ID}",
            json=_payload(),
            headers={"authorization": "Bearer test-grafana-token"},
        )
        assert duplicate.status_code == 202
        assert duplicate.json()["duplicate"] is True
        assert duplicate.json()["event_id"] == body["event_id"]

        denied = client.post(
            f"/webhooks/v1/{PUBLIC_ID}",
            json=_payload(),
            headers={"authorization": "Bearer wrong-token"},
        )
        assert denied.status_code == 401
        assert denied.json() == {
            "error": {
                "code": "webhook_auth_failed",
                "message": "Webhook authentication failed",
                "field_errors": [],
            }
        }

        unknown = client.post(
            "/webhooks/v1/wh_00000000000000000000000000000000",
            json=_payload(),
            headers={"authorization": "Bearer test-grafana-token"},
        )
        assert unknown.status_code == 404
        assert unknown.json()["error"]["code"] == "webhook_not_found"


def test_webhook_admin_api_enforces_session_csrf_actions_and_redaction() -> None:
    c = unified_container()
    with TestClient(create_app(unified_settings(), container_factory=lambda _: c)) as client:
        csrf = login(client)
        values = client.get("/api/admin/webhook-triggers")
        assert values.status_code == 200, values.text
        assert values.json()["triggers"][0]["code"] == "grafana-default"

        detail = client.get("/api/admin/webhook-triggers/grafana-default")
        assert detail.status_code == 200, detail.text
        serialized = json.dumps(detail.json(), ensure_ascii=False)
        assert "test-grafana-token" not in serialized
        assert "secret://connector/connector-grafana-default" in serialized

        no_csrf = client.post(
            "/api/admin/webhook-triggers/grafana-default/rotate-public-id",
            json={"expected_revision": 1, "confirm": True},
        )
        assert no_csrf.status_code == 403

        rotated = client.post(
            "/api/admin/webhook-triggers/grafana-default/rotate-public-id",
            headers=csrf_headers(csrf),
            json={"expected_revision": 1, "confirm": True},
        )
        assert rotated.status_code == 200, rotated.text
        assert rotated.json()["ingress_path"].startswith("/webhooks/v1/wh_")
        assert PUBLIC_ID not in rotated.json()["ingress_path"]

        old = client.post(
            f"/webhooks/v1/{PUBLIC_ID}",
            json=_payload(),
            headers={"authorization": "Bearer test-grafana-token"},
        )
        assert old.status_code == 404
