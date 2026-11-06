from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from app.modules.webhook.application import TriggerValidator, WebhookMapper, WebhookTriggerService
from app.modules.webhook.infrastructure import WebhookTriggerRepository
from app.shared.exceptions import NonRetryableExecutionError, PermissionDenied
from backend.tests.helpers import container


ADMIN_ID = "user_local_admin"


def test_concurrent_repeated_publication_creates_one_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, service = _service(monkeypatch)
    created = service.create(
        actor_id=ADMIN_ID,
        code="publish-once",
        name="Synthetic concurrent publish",
        trigger_type="grafana",
        connector_id="connector-grafana-default",
        config=_config(),
    )

    def publish(_):
        return service.publish(
            actor_id=ADMIN_ID, code="publish-once", revision_id=created["draft"]["id"]
        )["id"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        publication_ids = list(pool.map(publish, range(4)))
    assert len(set(publication_ids)) == 1
    detail = service.get(actor_id=ADMIN_ID, code="publish-once")
    assert len(detail["publications"]) == 1
    assert detail["definition"]["revision"] == created["definition"]["revision"] + 1
    assert detail["definition"]["current_publication_id"] == publication_ids[0]
    assert (
        c.database.execute_one(
            "select count(*) as total from audit_event where event_type='webhook.trigger.published'"
        )["total"]
        == 1
    )


def test_stop_unavailable_webhook_preserves_revision_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    c, service = _service(monkeypatch)
    definition = service.create(
        actor_id=ADMIN_ID,
        code="stop-unavailable",
        name="Synthetic stop",
        trigger_type="grafana",
        connector_id="connector-grafana-default",
        config=_config(),
    )["definition"]
    c.database.execute(
        "update integration_connector set enabled=0 where id=?", (definition["connector_id"],)
    )
    with pytest.raises(PermissionDenied, match="is disabled") as disabled:
        c.connector_registry.require_ingress(definition["connector_id"])
    assert disabled.value.safe_message == "入口连接器已停用，请先启用连接器"
    stopped = service.update_definition(
        actor_id=ADMIN_ID,
        code=definition["code"],
        expected_revision=definition["revision"],
        name=definition["name"],
        connector_id=definition["connector_id"],
        status="disabled",
    )
    assert stopped["status"] == "disabled"
    with pytest.raises(NonRetryableExecutionError):
        service.update_definition(
            actor_id=ADMIN_ID,
            code=definition["code"],
            expected_revision=definition["revision"],
            name=definition["name"],
            connector_id=definition["connector_id"],
            status="disabled",
        )


def _service(monkeypatch: pytest.MonkeyPatch) -> tuple[object, WebhookTriggerService]:
    del monkeypatch
    c = container(configure_seed_secrets=False)
    c.platform_config_service.secret_provider.create_secret(
        code="grafana_webhook_token",
        value="managed-test-token-0123456789abcdefABCDEF",
        actor_id=ADMIN_ID,
    )
    c.platform_config_service.secret_provider.create_secret(
        code="grafana_orders_webhook_token",
        value="orders-webhook-token-0123456789abcdefABCDEF",
        actor_id=ADMIN_ID,
    )
    c.platform_config_service.secret_provider.create_secret(
        code="dingtalk_webhook_robot_secret",
        value="dingtalk-webhook-signing-secret",
        actor_id=ADMIN_ID,
    )
    c.platform_config_service.secret_provider.create_secret(
        code="dingtalk_webhook_robot_url",
        value=("https://oapi.dingtalk.com/robot/send?access_token=webhook-test-token"),
        actor_id=ADMIN_ID,
    )
    c.platform_config_service.secret_provider.create_secret(
        code="dingtalk_client_secret",
        value="dingtalk-enterprise-client-secret",
        actor_id=ADMIN_ID,
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
    role = c.authorization_center_service.create_role(
        actor_id=ADMIN_ID,
        code="webhook-synthetic",
        name="Synthetic business role",
        description="",
        purpose_tags=[],
    )
    c.database.execute(
        "update rbac_role set id='role_webhook_synthetic' where id=?", (role["role"]["id"],)
    )
    repository = WebhookTriggerRepository(c.database)
    validator = TriggerValidator(
        repository=repository,
        identity_repository=c.identity_repository,
        connector_registry=c.connector_registry,
        agent_config_service=c.agent_config_service,
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
        "schema_version": 3,
        "adapter": "grafana_alertmanager_v1",
        "authentication": {
            "type": "bearer_v1",
            "secret_ref": "secret://platform/grafana_orders_webhook_token",
        },
        "execution_user_id": ADMIN_ID,
    }


def test_trigger_lifecycle_binds_user_without_creating_account_or_changing_roles(
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
    assert "service_account" not in created
    assert c.agent_repository.count_rows("app_user") == before_users
    roles_before_publish = c.identity_repository.role_codes_for_user(ADMIN_ID)
    assert (
        c.database.execute_one(
            """
        select name from sqlite_master
         where type = 'table' and name = 'permission_policy'
        """
        )
        is None
    )

    validated = service.validate_revision(
        actor_id=ADMIN_ID,
        code="grafana-orders",
        revision_id=str(draft["id"]),
    )
    assert validated["validation"]["valid"] is True
    assert validated["validation"]["execution_user_id"] == ADMIN_ID

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
    assert preview["routing"] == {}
    assert "Order API" in preview["message"]
    assert c.agent_repository.count_rows("webhook_event") == before_events

    publication = service.publish(
        actor_id=ADMIN_ID,
        code="grafana-orders",
        revision_id=str(draft["id"]),
    )
    assert "agent" not in publication["snapshot"]
    assert "delivery" not in publication["snapshot"]
    assert c.identity_repository.role_codes_for_user(ADMIN_ID) == roles_before_publish
    assert publication["snapshot"]["execution_user_id"] == ADMIN_ID
    assert "secret_ref" in json.dumps(publication["snapshot"])
    assert "orders-webhook-token-0123456789abcdefABCDEF" not in json.dumps(publication["snapshot"])

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


def test_trigger_requires_unique_strong_bearer_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, service = _service(monkeypatch)
    first = service.create(
        actor_id=ADMIN_ID,
        code="grafana-unique-one",
        name="Grafana Unique One",
        trigger_type="grafana",
        connector_id="connector-grafana-default",
        config=_config(),
    )
    validated = service.validate_revision(
        actor_id=ADMIN_ID,
        code="grafana-unique-one",
        revision_id=str(first["draft"]["id"]),
    )
    assert validated["validation"]["valid"] is True
    service.publish(
        actor_id=ADMIN_ID,
        code="grafana-unique-one",
        revision_id=str(first["draft"]["id"]),
    )

    duplicate = service.create(
        actor_id=ADMIN_ID,
        code="grafana-unique-two",
        name="Grafana Unique Two",
        trigger_type="grafana",
        connector_id="connector-grafana-default",
        config=_config(),
    )
    duplicate_validation = service.validate_revision(
        actor_id=ADMIN_ID,
        code="grafana-unique-two",
        revision_id=str(duplicate["draft"]["id"]),
    )
    assert duplicate_validation["validation"]["valid"] is False
    assert {
        item["message"]
        for item in duplicate_validation["validation"]["errors"]
        if item["field"] == "authentication.secret_ref"
    } == {"每个 Webhook binding 必须使用唯一 Bearer Token"}

    c.platform_config_service.secret_provider.create_secret(
        code="weak_webhook_token",
        value="too-short",
        actor_id=ADMIN_ID,
    )
    weak_config = deepcopy(_config())
    weak_config["authentication"]["secret_ref"] = "secret://platform/weak_webhook_token"
    weak = service.create(
        actor_id=ADMIN_ID,
        code="grafana-weak-token",
        name="Grafana Weak Token",
        trigger_type="grafana",
        connector_id="connector-grafana-default",
        config=weak_config,
    )
    weak_validation = service.validate_revision(
        actor_id=ADMIN_ID,
        code="grafana-weak-token",
        revision_id=str(weak["draft"]["id"]),
    )
    assert weak_validation["validation"]["valid"] is False
    assert any(
        item["field"] == "authentication.secret_ref" and "至少包含 32" in item["message"]
        for item in weak_validation["validation"]["errors"]
    )

    unsupported_config = deepcopy(_config())
    unsupported_config["authentication"]["type"] = "hmac_sha256_v1"
    unsupported = service.create(
        actor_id=ADMIN_ID,
        code="grafana-hmac-rejected",
        name="Grafana HMAC Rejected",
        trigger_type="grafana",
        connector_id="connector-grafana-default",
        config=unsupported_config,
    )
    unsupported_validation = service.validate_revision(
        actor_id=ADMIN_ID,
        code="grafana-hmac-rejected",
        revision_id=str(unsupported["draft"]["id"]),
    )
    assert unsupported_validation["validation"]["valid"] is False
    assert any(
        item["field"] == "authentication.type"
        for item in unsupported_validation["validation"]["errors"]
    )


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

    for field in ("mapping", "routing", "delivery", "agent", "limits"):
        generic = {**_config(), field: {}}
        with pytest.raises(NonRetryableExecutionError):
            service.create(
                actor_id=ADMIN_ID,
                code="bad-mapping",
                name="Bad mapping",
                trigger_type="grafana",
                connector_id="connector-grafana-default",
                config=generic,
            )


def test_webhook_management_requires_independent_rbac_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, service = _service(monkeypatch)
    viewer = c.identity_repository.create_user(
        username="webhook-viewer", display_name="Webhook Viewer"
    )
    with pytest.raises(PermissionDenied):
        service.list(actor_id=str(viewer["id"]))


@pytest.mark.parametrize("kind,status", [("service", "enabled"), ("human", "disabled")])
def test_execution_user_must_be_enabled_human(monkeypatch, kind, status):
    c, service = _service(monkeypatch)
    user = c.identity_repository.create_user(
        username="invalid-executor", display_name="Synthetic", account_type=kind
    )
    c.database.execute("update app_user set status=? where id=?", (status, user["id"]))
    config = {**_config(), "execution_user_id": user["id"]}
    created = service.create(
        actor_id=ADMIN_ID,
        code="user-webhook",
        name="User test",
        trigger_type="grafana",
        connector_id="connector-grafana-default",
        config=config,
    )
    catalog = service.execution_user_catalog(actor_id=ADMIN_ID)
    assert user["id"] not in {item["id"] for item in catalog}
    with pytest.raises(NonRetryableExecutionError) as error:
        service.publish(actor_id=ADMIN_ID, code="user-webhook", revision_id=created["draft"]["id"])
    assert error.value.field_errors[0]["field"] == "execution_user_id"


def test_execution_user_changes_only_on_publish_and_rollback(monkeypatch):
    c, service = _service(monkeypatch)
    other = c.identity_repository.create_user(username="other-executor", display_name="Other")
    created = service.create(
        actor_id=ADMIN_ID,
        code="user-switch",
        name="Switch",
        trigger_type="grafana",
        connector_id="connector-grafana-default",
        config=_config(),
    )
    first = service.publish(
        actor_id=ADMIN_ID, code="user-switch", revision_id=created["draft"]["id"]
    )
    draft = service.save_draft(
        actor_id=ADMIN_ID,
        code="user-switch",
        expected_revision=1,
        config={**_config(), "execution_user_id": other["id"]},
    )
    assert service.repository.get_definition("user-switch")["execution_user_id"] == ADMIN_ID
    second = service.publish(actor_id=ADMIN_ID, code="user-switch", revision_id=draft["id"])
    assert second["snapshot"]["execution_user_id"] == other["id"]
    assert (
        service.repository.get_publication(first["id"])["snapshot"]["execution_user_id"] == ADMIN_ID
    )
    current = service.repository.get_definition("user-switch")
    service.rollback(
        actor_id=ADMIN_ID,
        code="user-switch",
        publication_id=first["id"],
        expected_revision=current["revision"],
    )
    assert service.repository.get_definition("user-switch")["execution_user_id"] == ADMIN_ID
    assert c.identity_repository.role_codes_for_user(other["id"]) == ()
    assert all(
        set(row) == {"id", "username", "display_name"}
        for row in service.execution_user_catalog(actor_id=ADMIN_ID)
    )
