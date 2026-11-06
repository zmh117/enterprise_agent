from copy import deepcopy
from dataclasses import replace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.webhook.application.authentication import WebhookAuthenticator
from app.shared.exceptions import PermissionDenied
from backend.tests.test_unified_identity_rbac import csrf_headers, login, unified_settings
from backend.tests.test_webhook_ingress_dispatch import PUBLIC_ID, _container


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
def test_optional_bearer_api_publication_switch_preserves_routing_and_deduplication(
    authentication,
) -> None:
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
        denied = client.post(public_path, json=payload)
        assert denied.status_code == 401
        assert denied.json()["error"]["code"] == "webhook_auth_failed"
