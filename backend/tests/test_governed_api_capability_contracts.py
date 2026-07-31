from __future__ import annotations

from dataclasses import replace

import pytest

from app.modules.admin.domain import ADMIN_CAPABILITIES
from app.modules.api_capability.domain import (
    CapabilityIdentifier,
    CapabilityReleaseStatus,
    ChallengeStatus,
    CompiledMappingPlanContract,
    ConnectionDraftStatus,
    ContractValidationError,
    CredentialStatus,
    DataClassification,
    MappingAstContract,
    MappingScalarType,
    MappingValueSource,
    OperationSemantics,
    PublicSchemaContract,
    PublishedRevisionStatus,
    ReleaseSnapshotContract,
    RuntimeErrorContract,
    read_agent_capability_envelope,
    read_application_capability_allowlist,
)
from app.modules.internal_tools.domain import (
    HandlerDefinition,
    HandlerRegistry,
    HandlerRegistryError,
)


def test_capability_identifier_uses_the_reserved_stable_namespace() -> None:
    identifier = CapabilityIdentifier("cap__ones__work_item__search")
    assert str(identifier) == "cap__ones__work_item__search"


@pytest.mark.parametrize(
    "value",
    [
        "ones.work_item.search",
        "cap_ones_work_item_search",
        "cap__ONES__work_item__search",
        "cap__ones__work__item__search",
        "cap__ones__work-item__search",
        "cap__ones__work_item__search_",
        "cap__ones__work_item__" + ("a" * 110),
    ],
)
def test_capability_identifier_rejects_other_namespaces(value: str) -> None:
    with pytest.raises(ValueError):
        CapabilityIdentifier(value)


def test_v1_domain_enums_are_closed() -> None:
    assert tuple(OperationSemantics) == (OperationSemantics.QUERY,)
    assert tuple(DataClassification) == (DataClassification.INTERNAL,)
    assert set(ConnectionDraftStatus) == {
        ConnectionDraftStatus.DRAFT,
        ConnectionDraftStatus.VERIFIED,
    }
    assert set(PublishedRevisionStatus) == {
        PublishedRevisionStatus.PUBLISHED,
        PublishedRevisionStatus.DISABLED,
        PublishedRevisionStatus.ARCHIVED,
    }
    assert set(CapabilityReleaseStatus) == {
        CapabilityReleaseStatus.ACTIVE,
        CapabilityReleaseStatus.DEPRECATED,
        CapabilityReleaseStatus.DISABLED,
        CapabilityReleaseStatus.ARCHIVED,
    }
    assert set(CredentialStatus) == {
        CredentialStatus.ACTIVE,
        CredentialStatus.INVALID,
        CredentialStatus.DISABLED,
    }
    assert set(ChallengeStatus) == {
        ChallengeStatus.PENDING,
        ChallengeStatus.CONSUMED,
        ChallengeStatus.EXPIRED,
    }
    assert set(MappingValueSource) == {
        MappingValueSource.AGENT_INPUT,
        MappingValueSource.SYSTEM_CONTEXT,
        MappingValueSource.CONSTANT,
        MappingValueSource.RESPONSE,
    }
    assert set(MappingScalarType) == {
        MappingScalarType.STRING,
        MappingScalarType.INTEGER,
        MappingScalarType.NUMBER,
        MappingScalarType.BOOLEAN,
    }


@pytest.mark.parametrize(
    ("contract", "payload"),
    [
        (
            PublicSchemaContract,
            {
                "schema_version": 1,
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            },
        ),
        (
            MappingAstContract,
            {
                "schema_version": 1,
                "request": {"type": "object"},
                "response": {"type": "object"},
            },
        ),
        (
            CompiledMappingPlanContract,
            {
                "schema_version": 1,
                "ast_hash": "a" * 64,
                "request_plan": {"type": "object"},
                "response_plan": {"type": "object"},
            },
        ),
        (
            ReleaseSnapshotContract,
            {
                "schema_version": 1,
                "capability": {},
                "handler": {},
                "connection": {},
                "authentication_profile": {},
                "mapping_plan": {},
            },
        ),
        (
            RuntimeErrorContract,
            {
                "schema_version": 1,
                "error_code": "capability_unavailable",
                "safe_message": "当前 API 能力不可用",
                "retryable": False,
                "diagnostics": {},
            },
        ),
    ],
)
def test_versioned_contracts_round_trip(
    contract: type[object],
    payload: dict[str, object],
) -> None:
    parsed = contract.parse(payload)  # type: ignore[attr-defined]
    assert parsed.to_dict() == payload  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("contract", "payload"),
    [
        (
            PublicSchemaContract,
            {
                "schema_version": 2,
                "input_schema": {},
                "output_schema": {},
            },
        ),
        (
            MappingAstContract,
            {"schema_version": 2, "request": {}, "response": {}},
        ),
        (
            CompiledMappingPlanContract,
            {
                "schema_version": 2,
                "ast_hash": "a" * 64,
                "request_plan": {},
                "response_plan": {},
            },
        ),
        (
            ReleaseSnapshotContract,
            {
                "schema_version": 2,
                "capability": {},
                "handler": {},
                "connection": {},
                "authentication_profile": {},
                "mapping_plan": {},
            },
        ),
        (
            RuntimeErrorContract,
            {
                "schema_version": 2,
                "error_code": "x",
                "safe_message": "错误",
                "retryable": False,
                "diagnostics": {},
            },
        ),
    ],
)
def test_unknown_contract_versions_fail_closed(
    contract: type[object],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ContractValidationError, match="Unsupported"):
        contract.parse(payload)  # type: ignore[attr-defined]


def test_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ContractValidationError, match="unknown fields"):
        PublicSchemaContract.parse(
            {
                "schema_version": 1,
                "input_schema": {},
                "output_schema": {},
                "script": "unsafe",
            }
        )


def test_legacy_publication_snapshots_get_empty_capability_sets() -> None:
    assert read_agent_capability_envelope({"schema_version": 1}) == ()
    assert (
        read_application_capability_allowlist(
            {
                "schema_version": 1,
                "capabilities": [
                    {
                        "capability_code": "query_database",
                        "enabled": True,
                    }
                ],
            }
        )
        == ()
    )


def test_new_publication_snapshots_parse_exact_release_entries() -> None:
    envelope = read_agent_capability_envelope(
        {
            "capability_envelope": [
                {
                    "identifier": "cap__ones__work_item__search",
                    "release_id": "release-1",
                    "release_revision": 1,
                    "capability_revision_id": "cap-revision-1",
                    "handler_revision_id": "handler-revision-1",
                    "schema_hash": "a" * 64,
                    "description": "查询 ONES 工作项",
                }
            ]
        }
    )
    allowlist = read_application_capability_allowlist(
        {
            "capability_allowlist": [
                {
                    "identifier": "cap__ones__work_item__search",
                    "release_id": "release-1",
                }
            ]
        }
    )
    assert envelope[0].release_id == allowlist[0].release_id


def test_admin_permission_matrix_has_no_capability_use_grant() -> None:
    by_code = {item.code: item for item in ADMIN_CAPABILITIES}
    expected = {
        "api_connections.read",
        "api_connections.manage",
        "api_connections.verify",
        "api_connections.publish",
        "api_capabilities.read",
        "api_capabilities.manage",
        "api_capabilities.test",
        "api_capabilities.verify",
        "api_capabilities.publish",
        "external_credentials.self_manage",
        "external_credentials.read",
        "external_credentials.disable",
        "external_credentials.unbind",
    }
    assert expected.issubset(by_code)
    assert by_code["external_credentials.self_manage"].assignable is False
    assert not {
        item.code
        for item in ADMIN_CAPABILITIES
        if item.resource_type == "api_capability" and item.action == "use"
    }


def test_internal_handler_registry_rejects_capability_namespace() -> None:
    definition = HandlerDefinition(
        handler_id="query_database",
        handler_version="1.0.0",
        display_name="Query",
        description="Query",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        risk_level="LOW",
        required_permissions=("tool.query",),
        implementation_key="query",
    )
    with pytest.raises(HandlerRegistryError, match="reserved"):
        HandlerRegistry(
            (
                replace(
                    definition,
                    handler_id="cap__ones__work_item__search",
                ),
            )
        )
