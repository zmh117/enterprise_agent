from copy import deepcopy
from dataclasses import replace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.managed_channel.infrastructure.webhook_provider import (
    ManagedWebhookProviderAdapter,
)
from app.modules.webhook.application.authentication import WebhookAuthenticator
from app.shared.exceptions import PermissionDenied
from backend.tests.test_unified_identity_rbac import csrf_headers, login, unified_settings
from backend.tests.test_webhook_ingress_dispatch import PUBLIC_ID, _container


@pytest.mark.parametrize(
    ("authentication", "secret", "expected_status"),
    [
        ({"type": "none", "secret_ref": ""}, None, "READY"),
        ({"type": "none", "secret_ref": "secret://platform/synthetic"}, None, "MISCONFIGURED"),
        ({"type": "unknown", "secret_ref": ""}, None, "MISCONFIGURED"),
        (
            {"type": "bearer_v1", "secret_ref": "secret://platform/synthetic"},
            "synthetic-bearer-0123456789ABCDEF012345",
            "READY",
        ),
        (
            {"type": "bearer_v1", "secret_ref": "secret://platform/synthetic"},
            "weak",
            "MISCONFIGURED",
        ),
        (
            {"type": "bearer_v1", "secret_ref": "secret://platform/synthetic"},
            RuntimeError("unavailable"),
            "MISCONFIGURED",
        ),
    ],
)
def test_channel_readiness_uses_the_published_authentication_mode(
    authentication, secret, expected_status
) -> None:
    repository = Mock()
    repository.list_definitions.return_value = [
        {
            "id": "synthetic-hook",
            "connector_id": "synthetic-source",
            "status": "enabled",
            "execution_user_type": "human",
            "execution_user_status": "enabled",
        }
    ]
    repository.current_publication.return_value = {"snapshot": {"authentication": authentication}}
    registry = Mock()
    if isinstance(secret, Exception):
        registry.resolve_reference.side_effect = secret
    else:
        registry.resolve_reference.return_value = secret
    adapter = ManagedWebhookProviderAdapter(
        repository=repository, service=Mock(), connector_registry=registry
    )
    channel = adapter.list_channels()[0]
    assert channel["runtime_status"] == expected_status
    assert bool(channel["last_error_summary"]) == (expected_status != "READY")
    if authentication["type"] == "none":
        registry.resolve_reference.assert_not_called()


@pytest.mark.parametrize("unavailable", ["service_account", "connector"])
def test_channel_readiness_does_not_mislabel_disabled_dependencies_as_credentials(
    unavailable,
) -> None:
    repository = Mock()
    repository.list_definitions.return_value = [
        {
            "id": "synthetic-hook",
            "connector_id": "synthetic-source",
            "status": "enabled",
            "execution_user_type": "human",
            "execution_user_status": "disabled" if unavailable == "service_account" else "enabled",
        }
    ]
    registry = Mock()
    if unavailable == "connector":
        registry.require_ingress.side_effect = PermissionDenied(
            "disabled", safe_message="入口连接器已停用，请先启用连接器"
        )
    adapter = ManagedWebhookProviderAdapter(
        repository=repository, service=Mock(), connector_registry=registry
    )
    channel = adapter.list_channels()[0]
    assert channel["runtime_status"] == "MISCONFIGURED"
    assert "已停用" in channel["last_error_summary"]
    assert "凭据" not in channel["last_error_summary"]
    registry.resolve_reference.assert_not_called()


@pytest.mark.parametrize(
    "authentication",
    [
        {},
        {"type": "unknown", "secret_ref": ""},
        {"type": "none", "secret_ref": "secret://platform/synthetic"},
        {"type": "bearer_v1", "secret_ref": ""},
    ],
)
def test_only_explicit_published_none_skips_bearer(authentication) -> None:
    registry = Mock()
    registry.resolve_reference.return_value = ""
    authenticator = WebhookAuthenticator(connector_registry=registry)
    with pytest.raises(PermissionDenied):
        authenticator.authenticate(config={"authentication": authentication}, headers={})
    registry.reset_mock()
    assert (
        authenticator.authenticate(
            config={"authentication": {"type": "none", "secret_ref": ""}}, headers={}
        )
        == "none"
    )
    registry.resolve_reference.assert_not_called()


@pytest.mark.parametrize("secret", ["", "weak", RuntimeError("unavailable")])
def test_configured_bearer_does_not_fall_back_when_secret_is_unavailable(secret) -> None:
    registry = Mock()
    if isinstance(secret, Exception):
        registry.resolve_reference.side_effect = secret
    else:
        registry.resolve_reference.return_value = secret
    authenticator = WebhookAuthenticator(connector_registry=registry)
    with pytest.raises(PermissionDenied):
        authenticator.authenticate(
            config={
                "authentication": {
                    "type": "bearer_v1",
                    "secret_ref": "secret://platform/synthetic",
                }
            },
            headers={},
        )


@pytest.mark.parametrize(
    "authentication",
    [{"type": "none"}, {"type": "bearer_v1", "secret_ref": "  "}],
)
def test_optional_auth_publication_lifecycle(authentication) -> None:  # noqa: PLR0915
    c = _container()
    c.settings = replace(c.settings, identity=unified_settings().identity)
    path = "/api/admin/webhook-triggers/grafana-default"
    public_path = f"/webhooks/v1/{PUBLIC_ID}"
    with TestClient(create_app(unified_settings(), container_factory=lambda _: c)) as client:
        headers = csrf_headers(login(client))
        detail = client.get(path).json()["trigger"]
        protected = deepcopy(detail["draft"]["config"])
        contradictory = deepcopy(protected)
        contradictory["authentication"]["type"] = "none"
        rejected = client.post(
            path + "/revisions",
            headers=headers,
            json={"expected_revision": detail["draft"]["revision"], "config": contradictory},
        )
        assert rejected.status_code == 400
        config = deepcopy(protected)
        config["authentication"] = authentication
        # Keep the existing Grafana fixture and route, using its standard payload.
        payload = {"status": "firing", "groupKey": "optional-auth-001"}
        saved = client.post(
            path + "/revisions",
            headers=headers,
            json={"expected_revision": detail["draft"]["revision"], "config": config},
        )
        assert saved.status_code == 200, saved.text
        revision = saved.json()["revision"]
        assert revision["config"]["authentication"] == {"type": "none", "secret_ref": ""}
        assert client.post(public_path, json=payload).status_code == 401
        revision_path = path + "/revisions/" + revision["id"]
        valid = client.post(revision_path + "/validate", headers=headers, json={})
        assert valid.json()["revision"]["validation"]["valid"] is True, valid.text
        published = client.post(revision_path + "/publish", headers=headers, json={})
        assert published.status_code == 200, published.text
        definition_revision = client.get(path).json()["trigger"]["definition"]["revision"]
        repeated = client.post(revision_path + "/publish", headers=headers, json={})
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["publication"]["id"] == published.json()["publication"]["id"]
        unchanged = client.get(path).json()["trigger"]
        assert unchanged["definition"]["revision"] == definition_revision
        assert len(unchanged["publications"]) == 2
        channel = next(
            item
            for item in client.get("/api/admin/managed-channels").json()["items"]
            if item.get("code") == "grafana-default"
        )
        assert channel["runtime"]["status"] == "READY", channel["runtime"]
        assert channel["runtime"]["last_error"] == ""
        assert channel["id"] in {
            item["id"] for item in c.managed_channel_service.eligible("webhook")
        }
        accepted = client.post(public_path, json=payload)
        assert accepted.status_code == 202, accepted.text
        assert accepted.json()["accepted"] is True
        duplicate = client.post(public_path, json=payload)
        assert duplicate.json()["duplicate"] is True
        assert duplicate.json()["event_id"] == accepted.json()["event_id"]

        # An unauthenticated publication still requires an active application route.
        c.database.execute("delete from business_application_active_route")
        no_route = client.post(public_path, json={**payload, "groupKey": "no-route"})
        assert no_route.status_code == 400
        assert no_route.json()["error"]["code"] == "route_not_matched"

        restored = client.post(
            path + "/revisions",
            headers=headers,
            json={"expected_revision": revision["revision"], "config": protected},
        )
        assert restored.status_code == 200, restored.text
        restored_revision = restored.json()["revision"]
        published = client.post(
            path + "/revisions/" + restored_revision["id"] + "/publish",
            headers=headers,
            json={},
        )
        assert published.status_code == 200, published.text
        old_revision = client.post(revision_path + "/publish", headers=headers, json={})
        assert old_revision.status_code == 409, old_revision.text
        assert old_revision.json()["detail"]["code"] == "revision_already_published"
        denied = client.post(public_path, json=payload)
        assert denied.status_code == 401
        assert denied.json()["error"]["code"] == "webhook_auth_failed"
