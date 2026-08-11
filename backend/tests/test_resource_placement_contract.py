from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.bootstrap import build_test_container
from app.modules.authorization_center.api.controller import (
    ApplicationScopeRequest,
)
from app.modules.platform_config.application.validation import (
    PlatformConfigValidationError,
    validate_resource_placement,
)
from app.modules.platform_config.domain import ResourcePlacement
from app.shared.config import IdentitySettings, Settings


def _settings() -> Settings:
    return Settings(
        database_dsn="sqlite:///:memory:",
        app_config_master_key="test-only-master-key",
        environment="test",
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            published_agent_runtime_enabled=True,
            test_identity_headers_enabled=True,
            cookie_secure=False,
        ),
    )


def test_resource_placement_is_optional_and_has_only_cloud_or_edge() -> None:
    assert validate_resource_placement(None) is None
    assert validate_resource_placement("") is None
    assert validate_resource_placement("cloud") is ResourcePlacement.CLOUD
    assert validate_resource_placement("edge") is ResourcePlacement.EDGE

    for invalid in ("none", "default", "standalone", "Cloud", "cloud,edge"):
        with pytest.raises(PlatformConfigValidationError) as raised:
            validate_resource_placement(invalid)
        assert raised.value.error_code == "resource_placement_invalid"


def test_placement_cannot_be_submitted_as_role_data_scope() -> None:
    with pytest.raises(ValidationError):
        ApplicationScopeRequest.model_validate(
            {
                "environment_id": "environment-id",
                "base_id": "base-id",
                "workshop_id": "workshop-id",
                "placement": "edge",
            }
        )


def test_placement_is_persisted_on_resource_identity_not_role_scope() -> None:
    runtime = build_test_container(_settings(), migrate=True, seed=False)
    try:
        resource_columns = {
            row["name"] for row in runtime.database.execute("pragma table_info(platform_resource)")
        }
        access_scope_columns = {
            row["name"]
            for row in runtime.database.execute("pragma table_info(rbac_role_application_scope)")
        }
        topology_columns = {
            row["name"]
            for table in (
                "platform_environment",
                "platform_base",
                "platform_workshop",
            )
            for row in runtime.database.execute(f"pragma table_info({table})")
        }

        assert "placement" in resource_columns
        assert "placement" not in access_scope_columns
        assert "placement" not in topology_columns
        assert (
            runtime.database.execute_one(
                """
            select name from sqlite_master
             where type = 'table'
               and name = 'business_application_publication_builtin_tool_resource'
            """
            )
            is None
        )
    finally:
        runtime.database.close()
