from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.cli.audit_feature_configuration import build_report
from app.main import create_app
from app.shared.config import IdentitySettings
from app.shared.feature_configuration import (
    FeatureConfigurationError,
    apply_runtime_feature_policies,
    resolve_feature_configuration,
)
from app.shared.runtime_config_loader import apply_runtime_config_overlay
from backend.tests.helpers import test_settings
from backend.tests.test_unified_identity_rbac import csrf_headers, login


def test_four_top_level_features_have_safe_independent_defaults() -> None:
    features = resolve_feature_configuration("production", {})

    assert features.web_admin_enabled is False
    assert features.published_agent_runtime_enabled is False
    assert features.real_claude_enabled is False
    assert features.real_internal_tools_enabled is False
    assert features.unified_identity_enabled is False
    assert features.business_application_control_plane_enabled is False


def test_web_admin_atomically_enables_management_without_data_plane() -> None:
    features = resolve_feature_configuration(
        "production",
        {"FEATURE_WEB_ADMIN": "true"},
    )

    assert features.web_admin_enabled is True
    assert features.unified_identity_enabled is True
    assert features.business_application_control_plane_enabled is True
    assert features.published_agent_runtime_enabled is False
    assert features.real_claude_enabled is False
    assert features.real_internal_tools_enabled is False


@pytest.mark.parametrize(
    ("enabled_key", "enabled_property"),
    [
        ("FEATURE_WEB_ADMIN", "web_admin_enabled"),
        ("FEATURE_PUBLISHED_AGENT_RUNTIME", "published_agent_runtime_enabled"),
        ("FEATURE_REAL_CLAUDE", "real_claude_enabled"),
        ("FEATURE_REAL_INTERNAL_TOOLS", "real_internal_tools_enabled"),
    ],
)
def test_each_top_level_feature_can_be_enabled_independently(
    enabled_key: str,
    enabled_property: str,
) -> None:
    features = resolve_feature_configuration(
        "production",
        {key: str(key == enabled_key).lower() for key in (
            "FEATURE_WEB_ADMIN",
            "FEATURE_PUBLISHED_AGENT_RUNTIME",
            "FEATURE_REAL_CLAUDE",
            "FEATURE_REAL_INTERNAL_TOOLS",
        )},
    )

    assert getattr(features, enabled_property) is True
    for key, property_name in (
        ("FEATURE_WEB_ADMIN", "web_admin_enabled"),
        ("FEATURE_PUBLISHED_AGENT_RUNTIME", "published_agent_runtime_enabled"),
        ("FEATURE_REAL_CLAUDE", "real_claude_enabled"),
        ("FEATURE_REAL_INTERNAL_TOOLS", "real_internal_tools_enabled"),
    ):
        if key != enabled_key:
            assert getattr(features, property_name) is False


def test_conflicting_legacy_management_flags_fail_instead_of_guessing() -> None:
    with pytest.raises(FeatureConfigurationError, match="feature_configuration_conflict"):
        resolve_feature_configuration(
            "production",
            {
                "FEATURE_WEB_ADMIN": "true",
                "FEATURE_UNIFIED_IDENTITY": "false",
            },
        )


def test_test_identity_headers_fail_closed_outside_test() -> None:
    with pytest.raises(
        FeatureConfigurationError,
        match="test_only_feature_in_production",
    ):
        resolve_feature_configuration(
            "production",
            {"FEATURE_TEST_IDENTITY_HEADERS": "true"},
        )

    features = resolve_feature_configuration(
        "test",
        {"FEATURE_TEST_IDENTITY_HEADERS": "true"},
    )
    assert features.test_identity_headers_enabled is True
    assert features.item("TEST_IDENTITY_HEADERS").classification == "test-only"


def test_runtime_database_cannot_enable_a_closed_deployment_gate() -> None:
    features = resolve_feature_configuration(
        "production",
        {"FEATURE_REAL_INTERNAL_TOOLS": "false"},
    )
    effective = apply_runtime_feature_policies(
        features,
        {"FEATURE_REAL_INTERNAL_TOOLS": True},
    )

    assert effective.real_internal_tools_enabled is False
    item = effective.item("FEATURE_REAL_INTERNAL_TOOLS")
    assert item is not None
    assert item.requested_value is True
    assert item.blocked_by == "FEATURE_REAL_INTERNAL_TOOLS"
    assert any(
        diagnostic.code == "deployment_gate_blocked_runtime_value"
        for diagnostic in effective.diagnostics
    )


def test_permission_shadow_mode_is_audited_runtime_policy() -> None:
    settings = replace(
        test_settings(),
        identity=IdentitySettings(permission_shadow_mode=True),
    )
    container = build_test_container(settings, migrate=True, seed=True)
    container.platform_config_service.upsert_runtime_config_value(
        {
            "key": "PERMISSION_SHADOW_MODE",
            "value": False,
            "service_name": "api-server",
        },
        actor_id="local-user",
    )

    overlaid = apply_runtime_config_overlay(
        settings,
        container.database,
        service_name="api-server",
    )

    assert overlaid.identity.permission_shadow_mode is False
    assert (
        overlaid.feature_configuration.item("PERMISSION_SHADOW_MODE").source
        == "db:runtime-policy"
    )


def test_migration_audit_is_read_only_and_builds_unpublished_policy_draft() -> None:
    report = build_report(
        {
            "APP_ENV": "test",
            "FEATURE_CONTINUOUS_CONVERSATION": "true",
            "FEATURE_MESSAGE_ATTACHMENTS": "false",
            "FEATURE_PERMISSION_SHADOW_MODE": "true",
        }
    )

    assert report["write_performed"] is False
    assert report["publication_performed"] is False
    assert report["policy_draft"] == {
        "continuous_conversation_enabled": True,
        "attachments_enabled": False,
        "permission_shadow_mode": True,
    }


def test_management_routes_are_absent_when_web_admin_is_disabled() -> None:
    settings = test_settings()
    container = build_test_container(settings, migrate=True, seed=True)

    with TestClient(
        create_app(settings, container_factory=lambda _: container)
    ) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/admin/users").status_code == 404
        assert client.post(
            "/api/auth/login",
            json={"username": "local-user", "password": "anything-long-enough"},
        ).status_code == 404


def test_authorized_admin_can_read_masked_effective_feature_snapshot() -> None:
    base = test_settings()
    settings = replace(
        base,
        environment="test",
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            published_agent_runtime_enabled=False,
            permission_shadow_mode=False,
            cookie_secure=False,
            allowed_origins=("http://admin.test",),
        ),
    )
    container = build_test_container(settings, migrate=True, seed=True)

    with TestClient(
        create_app(settings, container_factory=lambda _: container)
    ) as client:
        assert client.get("/api/platform/runtime-config/features").status_code == 401
        csrf = login(client)
        response = client.get(
            "/api/platform/runtime-config/features",
            headers=csrf_headers(csrf),
        )

    assert response.status_code == 200
    payload = response.json()["features"]
    values = {item["key"]: item for item in payload["values"]}
    assert values["FEATURE_WEB_ADMIN"]["effective_value"] is True
    assert values["FEATURE_PUBLISHED_AGENT_RUNTIME"]["effective_value"] is False
    assert "password" not in str(payload).lower()
    assert "api_key" not in str(payload).lower()


def test_operator_templates_expose_only_four_top_level_feature_flags() -> None:
    expected = {
        "FEATURE_WEB_ADMIN",
        "FEATURE_PUBLISHED_AGENT_RUNTIME",
        "FEATURE_REAL_CLAUDE",
        "FEATURE_REAL_INTERNAL_TOOLS",
    }
    env_keys = {
        line.split("=", 1)[0]
        for line in Path(".env.example").read_text().splitlines()
        if line.startswith("FEATURE_") and "=" in line
    }
    compose_text = Path("docker-compose.yml").read_text()
    compose_keys = {
        key
        for key in expected
        if f"{key}:" in compose_text
    }

    assert env_keys == expected
    assert compose_keys == expected
    for legacy in (
        "FEATURE_UNIFIED_IDENTITY",
        "FEATURE_BUSINESS_APPLICATION_CONTROL_PLANE",
        "FEATURE_WEBHOOK_TRIGGERS",
        "FEATURE_CONTINUOUS_CONVERSATION",
        "FEATURE_MESSAGE_ATTACHMENTS",
        "FEATURE_TEST_IDENTITY_HEADERS",
        "FEATURE_PERMISSION_SHADOW_MODE",
    ):
        assert f"{legacy}:" not in compose_text
