from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from backend.tests.test_unified_identity_rbac import (
    csrf_headers,
    login,
    unified_container,
    unified_settings,
)


PUBLIC_ID = "wh_local_grafana_default_00000000000000000001"


@pytest.mark.parametrize("unavailable", ["disabled", "revoked", "unpublished", "old_schema"])
def test_agent_catalog_uses_webhook_name_and_current_publication(unavailable) -> None:
    from backend.tests.support.webhooks import prepare_test_webhook

    c = unified_container()
    prepare_test_webhook(c)
    c.database.execute(
        "update webhook_trigger_definition set name='合成诊断告警入口' where code='grafana-default'"
    )
    with TestClient(create_app(unified_settings(), container_factory=lambda _: c)) as client:
        login(client)

        def connectors():
            result = client.get("/api/admin/agents/default-diagnostic-agent")
            assert result.status_code == 200
            return {item["id"]: item for item in result.json()["agent"]["catalog"]["connectors"]}

        entry = connectors()["connector-grafana-default"]
        assert entry["name"] == "合成诊断告警入口"
        assert entry["allow_ingress"]
        if unavailable == "disabled":
            c.database.execute("update webhook_trigger_definition set status='disabled'")
        elif unavailable == "revoked":
            c.database.execute("update webhook_trigger_publication set status='revoked'")
        elif unavailable == "unpublished":
            c.database.execute("update webhook_trigger_definition set current_publication_id=null")
        else:
            c.database.execute("update webhook_trigger_publication set schema_version=2")
        assert "connector-grafana-default" not in connectors()


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
    from backend.tests.test_webhook_ingress_dispatch import _container

    c = _container()
    with TestClient(create_app(unified_settings(), container_factory=lambda _: c)) as client:
        accepted = client.post(
            f"/webhooks/v1/{PUBLIC_ID}",
            json=_payload(),
            headers={"authorization": "Bearer test-grafana-token-0123456789abcdefABCDEF"},
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
            headers={"authorization": "Bearer test-grafana-token-0123456789abcdefABCDEF"},
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
                "message": "Webhook 身份验证失败",
                "field_errors": [],
            }
        }
        legacy_header_only = client.post(
            f"/webhooks/v1/{PUBLIC_ID}",
            json=_payload(),
            headers={"x-grafana-token": ("test-grafana-token-0123456789abcdefABCDEF")},
        )
        assert legacy_header_only.status_code == 401
        assert legacy_header_only.json()["error"]["code"] == "webhook_auth_failed"

        unknown = client.post(
            "/webhooks/v1/wh_00000000000000000000000000000000",
            json=_payload(),
            headers={"authorization": "Bearer test-grafana-token-0123456789abcdefABCDEF"},
        )
        assert unknown.status_code == 404
        assert unknown.json()["error"]["code"] == "webhook_not_found"


def test_webhook_admin_api_enforces_session_csrf_actions_and_redaction() -> None:
    c = unified_container()
    from backend.tests.support.webhooks import prepare_test_webhook

    prepare_test_webhook(c)
    with TestClient(create_app(unified_settings(), container_factory=lambda _: c)) as client:
        csrf = login(client)
        values = client.get("/api/admin/webhook-triggers")
        assert values.status_code == 200, values.text
        assert values.json()["triggers"][0]["code"] == "grafana-default"

        detail = client.get("/api/admin/webhook-triggers/grafana-default")
        assert detail.status_code == 200, detail.text
        serialized = json.dumps(detail.json(), ensure_ascii=False)
        assert "test-grafana-token-0123456789abcdefABCDEF" not in serialized
        assert "secret://platform/grafana_webhook_token" in serialized

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
            headers={"authorization": "Bearer test-grafana-token-0123456789abcdefABCDEF"},
        )
        assert old.status_code == 404


def test_first_webhook_creates_independent_ingress_and_completes_configuration() -> None:  # noqa: PLR0915
    # Keep the authenticated first-use lifecycle in one end-to-end regression.
    from backend.tests.test_webhook_trigger_service import _config

    c = unified_container()
    c.database.execute("update integration_connector set enabled = 0")
    assert c.managed_channel_service.webhook_connector_options() == []
    c.platform_config_service.secret_provider.create_secret(
        code="synthetic-first-webhook",
        value="synthetic-webhook-bearer-0123456789ABCDEFG",
        actor_id="user_local_admin",
    )
    with TestClient(create_app(unified_settings(), container_factory=lambda _: c)) as client:
        csrf = login(client)
        body = {"code": "first-webhook", "name": "合成首次入口", "trigger_type": "generic"}
        denied = client.post("/api/admin/managed-channels/webhooks", json=body)
        assert denied.status_code == 403
        created = client.post(
            "/api/admin/managed-channels/webhooks", json=body, headers=csrf_headers(csrf)
        )
        assert created.status_code == 200, created.text
        definition = created.json()["webhook"]["definition"]
        source_id = definition["connector_id"]
        connector = c.connector_registry.get(source_id)
        assert connector.connector_type == "managed_webhook"
        assert connector.allow_ingress and not connector.allow_delivery
        assert connector.secret_ref == "" and connector.base_url == ""
        assert definition["status"] == "disabled"
        agent_path = "/api/admin/agents/default-diagnostic-agent"
        assert source_id not in {
            item["id"] for item in client.get(agent_path).json()["agent"]["catalog"]["connectors"]
        }
        counts = {
            table: c.agent_repository.count_rows(table)
            for table in ("integration_connector", "app_user", "webhook_trigger_definition")
        }
        duplicate = client.post(
            "/api/admin/managed-channels/webhooks", json=body, headers=csrf_headers(csrf)
        )
        assert duplicate.status_code == 400, duplicate.text
        for table, count in counts.items():
            assert c.agent_repository.count_rows(table) == count
        path = "/api/admin/webhook-triggers/first-webhook"
        premature = client.patch(
            path,
            headers=csrf_headers(csrf),
            json={
                "expected_revision": 1,
                "name": definition["name"],
                "connector_id": source_id,
                "status": "enabled",
            },
        )
        assert premature.status_code == 400
        assert premature.json()["detail"]["code"] == "webhook_not_published"
        catalog = client.get("/api/admin/webhook-triggers/catalog")
        assert catalog.status_code == 200
        assert "agents" not in catalog.json()
        config = _config()
        config["adapter"] = "generic_json_v1"
        config["authentication"]["secret_ref"] = "secret://platform/synthetic-first-webhook"
        config["execution_user_id"] = "user_local_admin"
        saved = client.post(
            path + "/revisions",
            headers=csrf_headers(csrf),
            json={"expected_revision": 0, "config": config},
        )
        assert saved.status_code == 200, saved.text
        revision = saved.json()["revision"]
        assert revision["config"]["schema_version"] == 3
        revision_path = path + "/revisions/" + revision["id"]
        # Publishing an ingress no longer depends on any Agent or delivery.
        valid = client.post(revision_path + "/validate", headers=csrf_headers(csrf), json={})
        assert valid.json()["revision"]["validation"]["valid"] is True, valid.text
        before_jobs = c.agent_repository.count_rows("agent_job")
        before_events = c.agent_repository.count_rows("webhook_event")
        sample = {"id": "synthetic-001", "message": "合成 Webhook 消息"}
        preview = client.post(
            revision_path + "/preview", headers=csrf_headers(csrf), json={"sample_payload": sample}
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["preview"]["side_effects"] is False
        assert c.agent_repository.count_rows("agent_job") == before_jobs
        assert c.agent_repository.count_rows("webhook_event") == before_events
        published = client.post(revision_path + "/publish", headers=csrf_headers(csrf), json={})
        assert published.status_code == 200, published.text
        current = client.get(path).json()["trigger"]
        enabled = client.patch(
            path,
            headers=csrf_headers(csrf),
            json={
                "expected_revision": current["definition"]["revision"],
                "name": definition["name"],
                "connector_id": source_id,
                "status": "enabled",
            },
        )
        assert enabled.status_code == 200, enabled.text
        agent_catalog = client.get(agent_path).json()["agent"]["catalog"]["connectors"]
        assert (
            next(item for item in agent_catalog if item["id"] == source_id)["name"] == body["name"]
        )
        public_path = "/webhooks/v1/" + definition["public_id"]
        assert client.post(public_path, json=sample).status_code == 401
        from backend.tests.support.applications import activate_webhook_test_application

        c.database.execute(
            """insert into agent_channel_binding
            (id,publication_id,direction,connector_id,config_json,created_at)
            values ('first-webhook-binding','agent_publication_default_v1','ingress',?,'{}',CURRENT_TIMESTAMP)""",
            (source_id,),
        )
        activate_webhook_test_application(
            c,
            code="first-webhook-app",
            webhook_definition_id=definition["id"],
            execution_user_id=current["definition"]["execution_user_id"],
            ingress_connector_id=source_id,
            delivery_connector_id="",
            delivery_target_reference="",
            delivery_type="",
        )
        accepted = client.post(
            public_path,
            json=sample,
            headers={"Authorization": "Bearer synthetic-webhook-bearer-0123456789ABCDEFG"},
        )
        assert accepted.status_code == 202, accepted.text
        assert "synthetic-webhook-bearer-0123456789ABCDEFG" not in client.get(path).text
        assert c.agent_repository.count_rows("agent_job") == before_jobs
        c.database.execute(
            "update integration_connector set allow_delivery = 1 where id = ?", (source_id,)
        )
        from app.shared.exceptions import NonRetryableExecutionError
        import pytest

        with pytest.raises(NonRetryableExecutionError):
            c.connector_registry.require_delivery(source_id)


def test_managed_webhook_creation_failure_rolls_back_connector_and_identity(monkeypatch) -> None:
    import pytest

    c = unified_container()
    before = {
        table: c.agent_repository.count_rows(table)
        for table in ("integration_connector", "app_user", "webhook_trigger_definition")
    }

    def fail_definition(**_kwargs):
        raise RuntimeError("synthetic persistence failure")

    monkeypatch.setattr(c.webhook_trigger_repository, "create_definition", fail_definition)
    with pytest.raises(RuntimeError, match="synthetic persistence failure"):
        c.managed_channel_service.create_webhook(
            actor_id="user_local_admin",
            code="rollback-first",
            name="合成回滚",
            trigger_type="generic",
        )
    for table, count in before.items():
        assert c.agent_repository.count_rows(table) == count


def test_webhook_catalog_does_not_require_a_default_agent() -> None:
    c = unified_container()
    c.database.execute("update agent_definition set status = 'disabled'")
    with TestClient(create_app(unified_settings(), container_factory=lambda _: c)) as client:
        login(client)
        result = client.get("/api/admin/webhook-triggers/catalog")
        assert result.status_code == 200, result.text
        assert result.json() == {
            "users": [
                {
                    "id": "user_local_admin",
                    "username": "admin",
                    "display_name": "Administrator",
                }
            ]
        }
