from __future__ import annotations

from dataclasses import replace

import pytest

from app.modules.agent.infrastructure.claude_code_agent_client import (
    TOOL_DEFINITIONS,
)
from app.modules.internal_tools.domain import (
    HandlerRegistry,
    HandlerRegistryError,
    build_builtin_handler_registry,
)
from app.modules.platform_config.application.handler_governance import (
    HandlerGovernanceService,
)
from app.modules.platform_config.infrastructure.handler_governance_repository import (
    HandlerGovernanceRepository,
)
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import container


def test_builtin_handler_registry_is_stable_versioned_and_schema_complete() -> None:
    first = build_builtin_handler_registry()
    second = build_builtin_handler_registry()
    definitions = first.definitions()

    assert {item.handler_id for item in definitions} == set(
        TOOL_DEFINITIONS
    )
    assert all(item.handler_version == "1.0.0" for item in definitions)
    assert {
        (item.handler_id, item.implementation_digest)
        for item in definitions
    } == {
        (item.handler_id, item.implementation_digest)
        for item in second.definitions()
    }
    from app.modules.agent.infrastructure.mcp_tool_registry import (
        ToolRegistry,
    )

    assert {item.handler_id for item in definitions} == set(
        ToolRegistry.READONLY_TOOLS
    )
    for definition in definitions:
        assert definition.input_schema == TOOL_DEFINITIONS[
            definition.handler_id
        ]["schema"]
        assert definition.output_schema["type"] == "object"
        assert definition.risk_level in {"LOW", "MEDIUM", "HIGH"}
        assert definition.required_permissions
        assert len(definition.implementation_digest) == 64
        for slot in definition.resource_slots:
            assert slot.resource_kind in {"database", "redis", "loki"}

    query_database = first.require("query_database", "1.0.0")
    assert query_database.visibility == "internal_diagnostic"
    assert query_database not in first.application_catalog()
    assert {
        item.handler_id for item in first.application_catalog()
    } == set(TOOL_DEFINITIONS).difference({"query_database"})


@pytest.mark.parametrize(
    "payload",
    [
        {"python": "print('unsafe')"},
        {"metadata": {"script": "run.sh"}},
        {"sql_template": "select * from anything"},
        {"implementation": {"source": "dynamic"}},
        {"metadata": {"entry": "https://untrusted.invalid/handler"}},
    ],
)
def test_registry_rejects_database_dynamic_implementation_payload(
    payload: dict[str, object],
) -> None:
    with pytest.raises(HandlerRegistryError):
        HandlerRegistry.reject_dynamic_governance_payload(payload)


def test_handler_installation_publication_and_status_are_governed() -> None:
    runtime = container()
    service = runtime.platform_config_service.handlers
    try:
        summary = service.reconcile(actor_id="local-user")
        assert summary == {
            "installed": len(TOOL_DEFINITIONS),
            "drifted": 0,
            "missing": 0,
        }
        publication = service.publish_payload(
            {
                "handler_id": "query_loki",
                "handler_version": "1.0.0",
            },
            actor_id="local-user",
        )
        assert publication["status"] == "PUBLISHED"
        disabled = service.set_publication_status(
            str(publication["id"]),
            "disabled",
            actor_id="local-user",
        )
        assert disabled["status"] == "DISABLED"
        archived = service.set_publication_status(
            str(publication["id"]),
            "archived",
            actor_id="local-user",
        )
        assert archived["status"] == "ARCHIVED"
        with pytest.raises(
            NonRetryableExecutionError,
            match="cannot be re-enabled",
        ):
            service.set_publication_status(
                str(publication["id"]),
                "published",
                actor_id="local-user",
            )
        with pytest.raises(
            NonRetryableExecutionError,
            match="already governed",
        ):
            service.publish_payload(
                {
                    "handler_id": "query_loki",
                    "handler_version": "1.0.0",
                },
                actor_id="local-user",
            )
    finally:
        runtime.database.close()


def test_same_handler_version_digest_drift_blocks_publication() -> None:
    runtime = container()
    original = build_builtin_handler_registry()
    original_service = runtime.platform_config_service.handlers
    try:
        original_service.reconcile(actor_id="local-user")
        definition = original.require("query_redis_get", "1.0.0")
        drifted_registry = HandlerRegistry(
            (
                replace(
                    definition,
                    implementation_key=(
                        definition.implementation_key + ":changed"
                    ),
                ),
            )
        )
        drifted_service = HandlerGovernanceService(
            HandlerGovernanceRepository(runtime.database),
            runtime.platform_config_service.repository,
            runtime.platform_config_service.permission_service,
            registry=drifted_registry,
        )
        summary = drifted_service.reconcile(actor_id="local-user")
        assert summary["drifted"] == 1
        installation = (
            drifted_service.repository.get_installation(
                "query_redis_get",
                "1.0.0",
            )
        )
        assert installation["installation_status"] == "DRIFTED"
        with pytest.raises(
            NonRetryableExecutionError,
            match="digest drifted",
        ):
            drifted_service.publish_payload(
                {
                    "handler_id": "query_redis_get",
                    "handler_version": "1.0.0",
                },
                actor_id="local-user",
            )
    finally:
        runtime.database.close()


def test_handler_tables_store_manifest_metadata_not_dynamic_implementation() -> None:
    runtime = container()
    service = runtime.platform_config_service.handlers
    try:
        service.reconcile(actor_id="local-user")
        columns = {
            row["name"]
            for row in runtime.database.execute(
                "pragma table_info(handler_installation)"
            )
        }
        assert {
            "implementation_digest",
            "input_schema_json",
            "output_schema_json",
            "required_permissions_json",
            "resource_slots_json",
        }.issubset(columns)
        assert not columns.intersection(
            {
                "python",
                "script",
                "source",
                "sql",
                "sql_template",
                "url",
            }
        )
        with pytest.raises(
            NonRetryableExecutionError,
            match="Dynamic Handler",
        ):
            service.publish_payload(
                {
                    "handler_id": "query_loki",
                    "handler_version": "1.0.0",
                    "implementation": {
                        "url": "https://untrusted.invalid/handler"
                    },
                },
                actor_id="local-user",
            )
        persisted = str(service.repository.list_installations())
        assert "untrusted.invalid" not in persisted
    finally:
        runtime.database.close()
