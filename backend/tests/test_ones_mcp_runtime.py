from __future__ import annotations

import io
import json
from dataclasses import dataclass, replace
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
import pytest

from app.modules.identity.application.ones_identity import (
    VerifiedOnesIdentity,
    VerifiedOnesTeam,
)
from app.modules.identity.application.principal_jwt import (
    PrincipalJwks,
    PrincipalSigningKey,
    PrincipalTokenIssuer,
    PrincipalTokenVerifier,
)
from app.modules.identity.infrastructure.external_identity_credentials import (
    CredentialSecretBundle,
)
from app.main import create_app as create_control_plane_app
from app.modules.job.infrastructure.repositories import now_iso
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.mcp_server_policy import ONES_MCP_SERVER_CODE
from app.modules.mcp_audit import McpAuditCoordinator
from app.shared.exceptions import AppError, NonRetryableExecutionError
from backend.tests.helpers import container, prepare_debug_application_access
from ones_mock.mock_ones_api import MockOnesSettings, create_app as create_mock_app
from services.ones_mcp_server.app import create_app as create_mcp_app
from services.ones_mcp_server.auth.principal import OnesPrincipalResolver
from services.ones_mcp_server.condition_dictionary import QueryConditionDictionary
from services.ones_mcp_server.contracts import (
    PROJECT_ROLE_MEMBERS_OUTPUT_SCHEMA,
    PROJECT_ROLE_MEMBERS_TOOL_IDENTIFIER,
    validate_provider_target,
)
from services.ones_mcp_server.credentials.refresh import OnesCredentialRefreshService
from services.ones_mcp_server.errors import OnesMcpError
from services.ones_mcp_server.provider.graphql.client import OnesGraphqlClient
from services.ones_mcp_server.provider.graphql.operation import GraphqlOperationRegistry
from services.ones_mcp_server.provider.graphql.operations.business_queries import (
    BUSINESS_GRAPHQL_OPERATIONS,
)
from services.ones_mcp_server.provider.graphql.operations.work_item_search import (
    WORK_ITEM_SEARCH_OPERATION,
)
from services.ones_mcp_server.provider.http_client import OnesProviderHttpClient
from services.ones_mcp_server.tools.project_role_members import (
    OnesProjectRoleMemberService,
)
from services.ones_mcp_server.tools.query_services import (
    OnesCustomOptionWorkItemQueryService,
    OnesProjectSearchService,
    OnesQueryConditionResolverService,
    OnesUsersByUuidService,
    OnesWorkItemQueryService,
)
from services.ones_mcp_server.tools.registry import OnesToolRegistry
from services.ones_mcp_server.tools.work_item_search import OnesWorkItemSearchService


@dataclass
class _ProviderResponse:
    status: int
    content: bytes

    def __enter__(self) -> _ProviderResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.content[:limit]


class _MockProviderTransport:
    def __init__(self) -> None:
        self.client = TestClient(create_mock_app(), follow_redirects=False)

    def __call__(self, request: Any, _timeout: float) -> _ProviderResponse:
        target = urlsplit(request.full_url)
        headers = {key: value for key, value in request.header_items()}
        response = self.client.request(
            request.get_method(),
            target.path + (f"?{target.query}" if target.query else ""),
            content=bytes(request.data or b""),
            headers=headers,
        )
        if response.status_code >= 400:
            raise HTTPError(
                request.full_url,
                response.status_code,
                "mock provider error",
                response.headers,
                io.BytesIO(response.content),
            )
        return _ProviderResponse(response.status_code, response.content)


class _MockLoginVerifier:
    available = True

    def __init__(self) -> None:
        self.settings = MockOnesSettings()
        self.calls = 0

    def verify(self, *, email: str, password: str) -> VerifiedOnesIdentity:
        self.calls += 1
        assert email == self.settings.email
        assert password == self.settings.password
        return VerifiedOnesIdentity.create(
            user_uuid=self.settings.user_uuid,
            display_name=self.settings.user_name,
            teams=(
                VerifiedOnesTeam(
                    id=self.settings.team_uuid,
                    name=self.settings.team_name,
                ),
            ),
            token=self.settings.token,
        )


def _signing_key() -> PrincipalSigningKey:
    private = Ed25519PrivateKey.generate()
    return PrincipalSigningKey.from_pem(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


def _mock_dictionary(settings: MockOnesSettings) -> QueryConditionDictionary:
    return QueryConditionDictionary(
        source_team_uuid=settings.team_uuid,
        captured_at="2026-08-27",
        dictionary_version="2026-08-27-synthetic",
        statuses=(
            {
                "uuid": str(settings.config.statuses["done"]["uuid"]),
                "name": str(settings.config.statuses["done"]["name"]),
                "category": "done",
            },
        ),
        fields=(
            {
                "uuid": "MOCK-CUSTOM-FIELD-SEVERITY",
                "name": "严重程度",
                "type": "single_select",
                "filter_key": "_MOCK-CUSTOM-FIELD-SEVERITY_in",
                "options": (
                    {"uuid": "MOCK-CUSTOM-OPTION-HIGH", "name": "严重"},
                    {"uuid": "MOCK-CUSTOM-OPTION-LOW", "name": "一般"},
                    {"uuid": "MOCK-CUSTOM-OPTION-MEDIUM", "name": "中等"},
                ),
            },
        ),
    )


def _fixture(
    *,
    initial_token: str | None = None,
    capabilities: tuple[str, ...] = (
        "ones_work_item_search",
        PROJECT_ROLE_MEMBERS_TOOL_IDENTIFIER,
    ),
) -> dict[str, Any]:
    runtime = container()
    next_order = runtime.database.execute_one(
        "select coalesce(max(selection_order), -1) + 1 as value "
        "from agent_publication_mcp_tool where agent_publication_id = ?",
        ("agent_publication_default_v1",),
    )
    assert next_order is not None
    for offset, tool_identifier in enumerate(capabilities):
        definition = MCP_TOOL_MANIFEST[tool_identifier]
        runtime.database.execute(
            """
            insert into agent_publication_mcp_tool
              (agent_publication_id, server_code, tool_identifier, schema_hash,
               model_description, selection_order, created_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "agent_publication_default_v1",
                definition.server_code,
                definition.identifier,
                definition.schema_hash,
                definition.description,
                int(next_order["value"]) + offset,
                now_iso(),
            ),
        )
    selection = prepare_debug_application_access(
        runtime,
        application_code="ones-mcp-runtime-test",
        role_code="ones-mcp-runtime-reader",
        capabilities=capabilities,
    )
    job, _ = runtime.debug_job_access_service.create_job(
        user_id="user_local_admin",
        display_name="Administrator",
        message="search ONES work items",
        application_id=selection["application_id"],
        execution_scope_id=selection["execution_scope_id"],
        idempotency_key="ones-mcp-runtime-job",
        correlation_id="ones-mcp-runtime-correlation",
        environment="local",
    )
    claimed = runtime.agent_repository.claim_job(job.id, "agent-worker-test")
    assert claimed is not None
    mock = MockOnesSettings()
    identity = runtime.identity_repository.bind_external_identity(
        user_id="user_local_admin",
        provider="ones",
        tenant_code="default",
        external_subject_id=mock.user_uuid,
        connector_id="",
        display_name=mock.user_name,
        metadata={
            "team_uuids": [mock.team_uuid],
            "teams": [{"id": mock.team_uuid, "name": mock.team_name}],
            "default_team_id": mock.team_uuid,
        },
    )
    credentials = runtime.external_identity_credential_repository
    assert credentials is not None
    credentials.upsert_active(
        external_identity_id=str(identity["id"]),
        provider="ones",
        secrets=CredentialSecretBundle(
            email=mock.email,
            password=mock.password,
            token=initial_token or mock.token,
        ),
        verified_at=now_iso(),
    )
    signing_key = _signing_key()
    issuer = PrincipalTokenIssuer(
        runtime.database,
        runtime.mcp_tool_snapshot_service,
        runtime.business_authorization_service,
        signing_key,
        runtime.audit_service,
    )
    token = issuer.issue_business_mcp_for_job(
        job_id=claimed.id,
        server_code=ONES_MCP_SERVER_CODE,
    )
    verifier = PrincipalTokenVerifier(
        PrincipalJwks.from_dict(signing_key.public_jwks()),
        expected_audience=ONES_MCP_SERVER_CODE,
        audit_service=runtime.audit_service,
    )
    audit = McpAuditCoordinator(
        runtime.database,
        max_payload_bytes=256 * 1024,
        audit_service=runtime.audit_service,
    )
    login = _MockLoginVerifier()
    provider_http = OnesProviderHttpClient(
        validate_provider_target(
            "http://ones-mock:8001",
            allowed_hosts=("ones-mock",),
            app_env="test",
            allow_insecure_local=True,
        ),
        timeout_seconds=5,
        max_response_bytes=256 * 1024,
        open_response=_MockProviderTransport(),
    )
    graphql = OnesGraphqlClient(
        provider_http,
        GraphqlOperationRegistry((WORK_ITEM_SEARCH_OPERATION, *BUSINESS_GRAPHQL_OPERATIONS)),
    )
    resolver = OnesPrincipalResolver(
        runtime.database,
        verifier,
        runtime.mcp_tool_snapshot_service,
        runtime.business_authorization_service,
        credentials,
    )
    refresh = OnesCredentialRefreshService(
        resolver,
        login,
        credentials,
        audit,
    )
    service = OnesWorkItemSearchService(
        resolver,
        graphql,
        credentials,
        audit,
        refresh,
    )
    role_service = OnesProjectRoleMemberService(
        resolver,
        provider_http,
        credentials,
        audit,
        refresh,
    )
    project_search_service = OnesProjectSearchService(
        resolver,
        credentials,
        audit,
        refresh,
        graphql=graphql,
    )
    dictionary = _mock_dictionary(mock)
    work_item_query_service = OnesWorkItemQueryService(
        resolver,
        credentials,
        audit,
        refresh,
        graphql=graphql,
    )
    custom_work_item_query_service = OnesCustomOptionWorkItemQueryService(
        resolver,
        credentials,
        audit,
        refresh,
        graphql=graphql,
        dictionary=dictionary,
    )
    users_by_uuid_service = OnesUsersByUuidService(
        resolver,
        credentials,
        audit,
        refresh,
        http=provider_http,
    )
    condition_resolver_service = OnesQueryConditionResolverService(
        resolver,
        credentials,
        audit,
        refresh,
        dictionary=dictionary,
    )
    registry = OnesToolRegistry(
        authenticate=service.authenticate,
        tools=(
            service,
            role_service,
            project_search_service,
            work_item_query_service,
            custom_work_item_query_service,
            users_by_uuid_service,
            condition_resolver_service,
        ),
        audit=audit,
    )
    return {
        "runtime": runtime,
        "job": claimed,
        "identity": identity,
        "token": token,
        "claims": registry.authenticate(token, tool_identifier=capabilities[0]),
        "service": service,
        "role_service": role_service,
        "project_search_service": project_search_service,
        "work_item_query_service": work_item_query_service,
        "custom_work_item_query_service": custom_work_item_query_service,
        "users_by_uuid_service": users_by_uuid_service,
        "condition_resolver_service": condition_resolver_service,
        "registry": registry,
        "provider_http": provider_http,
        "login": login,
        "mock": mock,
        "selection": selection,
    }


def _list_project_role_members(
    fixture: dict[str, Any],
    *,
    project_uuid: str,
    correlation_id: str,
) -> dict[str, Any]:
    service = fixture["role_service"]
    return service.invoke(
        claims=service.authenticate(fixture["token"]),
        arguments={"project_uuid": project_uuid},
        correlation_id=correlation_id,
        invocation_id=f"{fixture['job'].id}.attempt-{fixture['job'].retry_count}",
    )


def test_ones_mcp_mock_query_persists_complete_unmasked_business_audit() -> None:
    fixture = _fixture()
    service = fixture["service"]
    result = service.search(
        claims=fixture["claims"],
        arguments={"keyword": "traceability", "issue_type": "demand", "limit": 10},
        correlation_id="ones-query-1",
    )

    assert result == {
        "items": [
            {
                "number": 900101,
                "name": "Mock requirement: add production order traceability",
                "type": "demand",
            }
        ],
        "total": 1,
        "truncated": False,
        "untrusted_data": True,
    }
    rows = fixture["runtime"].database.execute(
        "select * from mcp_operation_audit where correlation_id = ? order by created_at, id",
        ("ones-query-1",),
    )
    assert len(rows) == 3
    provider = next(row for row in rows if row["event_kind"] == "PROVIDER")
    tool = next(row for row in rows if row["event_kind"] == "TOOL")
    authorization = next(row for row in rows if row["event_kind"] == "AUTHORIZATION")
    assert json.loads(provider["business_request_json"])["variables"] == {
        "keyword": "traceability",
        "issue_type": "demand",
        "limit": 10,
        "team_id": fixture["mock"].team_uuid,
        "user_id": fixture["mock"].user_uuid,
    }
    assert (
        json.loads(provider["business_response_json"])["provider_response"]["data"]["workItems"][
            "items"
        ][0]["name"]
        == result["items"][0]["name"]
    )
    assert json.loads(tool["tool_request_json"])["keyword"] == "traceability"
    assert json.loads(tool["tool_response_json"]) == result
    assert provider["provider_email"] == fixture["mock"].email
    assert authorization["authorization_decision"] == "ALLOW"
    evidence = json.dumps(rows, ensure_ascii=False)
    assert fixture["mock"].password not in evidence
    assert fixture["mock"].token not in evidence
    assert fixture["token"] not in evidence
    tool_calls = fixture["runtime"].database.execute(
        "select * from agent_tool_call where job_id = ?",
        (fixture["job"].id,),
    )
    assert len(tool_calls) == 1
    tool_call_id = tool_calls[0]["id"]
    assert tool_calls[0]["persisted_by"] == "mcp_server"
    linked = fixture["runtime"].database.execute(
        "select agent_tool_call_id, audit_event_id from mcp_operation_audit "
        "where correlation_id = ?",
        ("ones-query-1",),
    )
    assert {row["agent_tool_call_id"] for row in linked} == {tool_call_id}
    assert {row["mcp_call_id"] for row in rows} == {result.audit_handle.mcp_call_id}
    assert tool["audit_event_id"]


def test_ones_mcp_refreshes_stale_token_once_and_retries_mock_query() -> None:
    fixture = _fixture(initial_token="stale-test-token")
    result = fixture["service"].search(
        claims=fixture["claims"],
        arguments={"keyword": "#900103", "issue_type": "defect", "limit": 5},
        correlation_id="ones-query-refresh",
    )

    assert result["items"][0]["number"] == 900103
    assert fixture["login"].calls == 1
    credential = fixture["runtime"].external_identity_credential_repository.get_by_identity(
        str(fixture["identity"]["id"])
    )
    assert credential is not None
    assert credential["revision"] == 2
    rows = fixture["runtime"].database.execute(
        "select event_kind, attempt, status, error_code from mcp_operation_audit "
        "where correlation_id = ? order by created_at, id",
        ("ones-query-refresh",),
    )
    assert {(row["event_kind"], row["attempt"], row["status"]) for row in rows} == {
        ("PROVIDER", 0, "FAILED"),
        ("CREDENTIAL", 0, "SUCCEEDED"),
        ("PROVIDER", 1, "SUCCEEDED"),
        ("TOOL", 0, "SUCCEEDED"),
        ("AUTHORIZATION", 0, "SUCCEEDED"),
    }


def test_new_project_query_uses_job_scope_refresh_and_safe_provider_audit() -> None:
    fixture = _fixture(
        initial_token="stale-test-token",
        capabilities=("ones_work_item_search", "ones_search_projects"),
    )
    service = fixture["project_search_service"]

    result = service.invoke(
        claims=service.authenticate(fixture["token"]),
        arguments={"keyword": "Manufacturing", "limit": 10},
        correlation_id="ones-project-search-refresh",
        invocation_id=f"{fixture['job'].id}.attempt-{fixture['job'].retry_count}",
    )

    assert result["projects"][0]["uuid"] == fixture["mock"].config.project_uuid
    assert fixture["login"].calls == 1
    rows = fixture["runtime"].database.execute(
        "select * from mcp_operation_audit where correlation_id = ? order by created_at, id",
        ("ones-project-search-refresh",),
    )
    provider_rows = [row for row in rows if row["event_kind"] == "PROVIDER"]
    assert [(row["attempt"], row["status"]) for row in provider_rows] == [
        (0, "FAILED"),
        (1, "SUCCEEDED"),
    ]
    request = json.loads(provider_rows[1]["business_request_json"])
    response = json.loads(provider_rows[1]["business_response_json"])
    assert request["operation"] == "project_search"
    assert request["query_type"] == "projects-group-list-for-project-view"
    assert "query" not in request
    assert response == {
        "result_keys": [
            "projects",
            "returned",
            "total",
            "truncated",
            "untrusted_data",
        ],
        "returned": 1,
        "total": 1,
        "truncated": False,
    }
    evidence = json.dumps(rows, ensure_ascii=False)
    assert fixture["mock"].token not in evidence
    assert fixture["mock"].password not in evidence


def test_custom_option_query_is_dictionary_validated_before_fixed_graphql() -> None:
    fixture = _fixture(capabilities=("ones_query_work_items_with_custom_options",))
    service = fixture["custom_work_item_query_service"]
    invocation_id = f"{fixture['job'].id}.attempt-{fixture['job'].retry_count}"
    result = service.invoke(
        claims=service.authenticate(fixture["token"]),
        arguments={
            "custom_option_filters": [
                {
                    "field_uuid": "MOCK-CUSTOM-FIELD-SEVERITY",
                    "option_uuids": ["MOCK-CUSTOM-OPTION-HIGH"],
                }
            ],
            "limit": 10,
        },
        correlation_id="ones-custom-filter",
        invocation_id=invocation_id,
    )
    assert [item["number"] for item in result["items"]] == [900103]
    provider = fixture["runtime"].database.execute_one(
        "select business_request_json from mcp_operation_audit "
        "where correlation_id = ? and event_kind = 'PROVIDER'",
        ("ones-custom-filter",),
    )
    assert provider is not None
    request = json.loads(provider["business_request_json"])
    assert request["variables"]["filterGroup"] == [
        {"_MOCK-CUSTOM-FIELD-SEVERITY_in": ["MOCK-CUSTOM-OPTION-HIGH"]}
    ]
    assert "query" not in request

    with pytest.raises(AppError) as unknown:
        service.invoke(
            claims=service.authenticate(fixture["token"]),
            arguments={
                "custom_option_filters": [
                    {
                        "field_uuid": "MOCK-CUSTOM-FIELD-SEVERITY",
                        "option_uuids": ["MOCK-CUSTOM-OPTION-UNKNOWN"],
                    }
                ],
                "limit": 10,
            },
            correlation_id="ones-custom-filter-unknown",
            invocation_id=invocation_id,
        )
    assert unknown.value.error_code == "ones_query_condition_invalid"
    assert (
        fixture["runtime"].database.execute_one(
            "select id from mcp_operation_audit "
            "where correlation_id = ? and event_kind = 'PROVIDER'",
            ("ones-custom-filter-unknown",),
        )
        is None
    )


def test_condition_resolution_uses_scoped_resource_without_provider_or_refresh() -> None:
    fixture = _fixture(capabilities=("ones_resolve_query_conditions",))
    service = fixture["condition_resolver_service"]
    result = service.invoke(
        claims=service.authenticate(fixture["token"]),
        arguments={
            "condition_type": "custom_option",
            "field_keyword": "严重程度",
            "keyword": "严重",
            "limit": 10,
        },
        correlation_id="ones-condition-resolve",
        invocation_id=f"{fixture['job'].id}.attempt-{fixture['job'].retry_count}",
    )
    assert result["matches"][0]["option_uuid"] == "MOCK-CUSTOM-OPTION-HIGH"
    assert fixture["login"].calls == 0
    rows = fixture["runtime"].database.execute(
        "select event_kind, status from mcp_operation_audit where correlation_id = ?",
        ("ones-condition-resolve",),
    )
    assert {(row["event_kind"], row["status"]) for row in rows} == {
        ("AUTHORIZATION", "SUCCEEDED"),
        ("RESOURCE", "SUCCEEDED"),
        ("TOOL", "SUCCEEDED"),
    }


def test_user_uuid_lookup_refreshes_once_and_never_projects_personal_details() -> None:
    fixture = _fixture(
        initial_token="stale-test-token",
        capabilities=("ones_get_users_by_uuids",),
    )
    service = fixture["users_by_uuid_service"]
    result = service.invoke(
        claims=service.authenticate(fixture["token"]),
        arguments={"user_uuids": [fixture["mock"].user_uuid]},
        correlation_id="ones-users-by-uuid-refresh",
        invocation_id=f"{fixture['job'].id}.attempt-{fixture['job'].retry_count}",
    )
    assert result["users"] == [
        {"uuid": fixture["mock"].user_uuid, "name": fixture["mock"].user_name}
    ]
    assert fixture["login"].calls == 1
    serialized = json.dumps(result, ensure_ascii=False).casefold()
    assert all(
        forbidden not in serialized
        for forbidden in ("email", "phone", "department", "avatar", "mfa", "company")
    )
    rows = fixture["runtime"].database.execute(
        "select event_kind, attempt, status from mcp_operation_audit where correlation_id = ?",
        ("ones-users-by-uuid-refresh",),
    )
    assert {(row["event_kind"], row["attempt"], row["status"]) for row in rows} >= {
        ("PROVIDER", 0, "FAILED"),
        ("CREDENTIAL", 0, "SUCCEEDED"),
        ("PROVIDER", 1, "SUCCEEDED"),
    }


def test_user_uuid_lookup_maps_provider_forbidden() -> None:
    fixture = _fixture(capabilities=("ones_get_users_by_uuids",))
    service = fixture["users_by_uuid_service"]
    with pytest.raises(OnesMcpError) as raised:
        service.invoke(
            claims=service.authenticate(fixture["token"]),
            arguments={"user_uuids": ["__403__"]},
            correlation_id="ones-users-by-uuid-forbidden",
            invocation_id=f"{fixture['job'].id}.attempt-{fixture['job'].retry_count}",
        )
    assert raised.value.error_code == "ones_provider_forbidden"


def test_project_role_members_joins_fixed_rest_calls_and_audits_only_safe_summaries() -> None:
    fixture = _fixture()
    result = _list_project_role_members(
        fixture,
        project_uuid=fixture["mock"].config.project_uuid,
        correlation_id="ones-project-role-members",
    )

    assert result == {
        "roles": [
            {
                "role_uuid": "MOCK-ONES-ROLE-MEMBERS",
                "role_name": "项目成员",
                "members": [
                    {"uuid": "MOCK-ONES-USER-001", "name": "Mock ONES User"},
                    {"uuid": "MOCK-ONES-USER-002", "name": "Mock ONES Owner"},
                ],
            },
            {
                "role_uuid": "MOCK-ONES-ROLE-TESTERS",
                "role_name": "Testers",
                "members": [
                    {"uuid": "MOCK-ONES-USER-002", "name": "Mock ONES Owner"},
                ],
            },
        ],
        "untrusted_data": True,
    }
    rows = fixture["runtime"].database.execute(
        "select * from mcp_operation_audit where correlation_id = ? order by created_at, id",
        ("ones-project-role-members",),
    )
    provider_rows = [row for row in rows if row["event_kind"] == "PROVIDER"]
    assert {row["tool_identifier"] for row in rows} == {PROJECT_ROLE_MEMBERS_TOOL_IDENTIFIER}
    assert [json.loads(row["business_request_json"])["operation"] for row in provider_rows] == [
        "project_role_members",
        "team_users",
    ]
    assert json.loads(provider_rows[0]["business_response_json"])["role_count"] == 2
    assert json.loads(provider_rows[1]["business_response_json"])["returned_user_count"] == 2
    evidence = json.dumps(rows, ensure_ascii=False)
    assert "mock.owner@example.test" not in evidence
    assert '"phone"' not in evidence
    assert '"avatar"' not in evidence
    assert fixture["mock"].password not in evidence
    assert fixture["mock"].token not in evidence


def test_project_role_members_empty_project_skips_team_users_call() -> None:
    fixture = _fixture()
    result = _list_project_role_members(
        fixture,
        project_uuid="MOCK-ONES-PROJECT-EMPTY",
        correlation_id="ones-project-role-members-empty",
    )

    assert result == {"roles": [], "untrusted_data": True}
    provider_rows = fixture["runtime"].database.execute(
        "select business_request_json from mcp_operation_audit "
        "where correlation_id = ? and event_kind = 'PROVIDER'",
        ("ones-project-role-members-empty",),
    )
    assert [json.loads(row["business_request_json"])["operation"] for row in provider_rows] == [
        "project_role_members"
    ]


def test_project_role_members_fails_closed_when_user_lookup_is_incomplete() -> None:
    fixture = _fixture()

    with pytest.raises(AppError) as raised:
        _list_project_role_members(
            fixture,
            project_uuid="MOCK-ONES-PROJECT-MISSING-USER",
            correlation_id="ones-project-role-members-missing-user",
        )

    assert raised.value.error_code == "ones_provider_schema_invalid"
    tool_row = fixture["runtime"].database.execute_one(
        "select status, tool_response_json from mcp_operation_audit "
        "where correlation_id = ? and event_kind = 'TOOL'",
        ("ones-project-role-members-missing-user",),
    )
    assert tool_row is not None
    assert tool_row["status"] == "FAILED"
    assert "roles" not in json.loads(tool_row["tool_response_json"])


def test_project_role_members_rejects_extra_identity_fields_before_audit() -> None:
    fixture = _fixture()
    service = fixture["role_service"]

    with pytest.raises(AppError) as raised:
        service.invoke(
            claims=service.authenticate(fixture["token"]),
            arguments={
                "project_uuid": fixture["mock"].config.project_uuid,
                "team_uuid": "forged-team",
            },
            correlation_id="ones-project-role-members-forged-identity",
            invocation_id=f"{fixture['job'].id}.attempt-{fixture['job'].retry_count}",
        )

    assert raised.value.error_code == "ones_tool_input_invalid"
    assert (
        fixture["runtime"].database.execute(
            "select * from mcp_operation_audit where correlation_id = ?",
            ("ones-project-role-members-forged-identity",),
        )
        == []
    )


def test_project_role_members_refreshes_stale_token_once() -> None:
    fixture = _fixture(initial_token="stale-test-token")
    result = _list_project_role_members(
        fixture,
        project_uuid=fixture["mock"].config.project_uuid,
        correlation_id="ones-project-role-members-refresh",
    )

    assert len(result["roles"]) == 2
    assert fixture["login"].calls == 1
    credential = fixture["runtime"].external_identity_credential_repository.get_by_identity(
        str(fixture["identity"]["id"])
    )
    assert credential is not None
    assert credential["revision"] == 2


def test_project_role_members_maps_provider_forbidden() -> None:
    fixture = _fixture()

    with pytest.raises(AppError) as raised:
        _list_project_role_members(
            fixture,
            project_uuid="MOCK-ONES-PROJECT-FORBIDDEN",
            correlation_id="ones-project-role-members-forbidden",
        )

    assert raised.value.error_code == "ones_provider_forbidden"


@pytest.mark.parametrize(
    ("missing_fact", "error_code"),
    [
        ("credential", "ones_credential_reverification_required"),
        ("default_team", "ones_default_team_invalid"),
    ],
)
def test_project_role_members_requires_current_credential_and_default_team(
    missing_fact: str,
    error_code: str,
) -> None:
    fixture = _fixture()
    if missing_fact == "credential":
        fixture["runtime"].database.execute(
            "delete from external_identity_credential where external_identity_id = ?",
            (fixture["identity"]["id"],),
        )
    else:
        fixture["runtime"].database.execute(
            "update user_external_identity set metadata_json = ? where id = ?",
            (
                json.dumps({"team_uuids": [fixture["mock"].team_uuid]}),
                fixture["identity"]["id"],
            ),
        )

    with pytest.raises(AppError) as raised:
        _list_project_role_members(
            fixture,
            project_uuid=fixture["mock"].config.project_uuid,
            correlation_id=f"ones-project-role-members-no-{missing_fact}",
        )

    assert raised.value.error_code == error_code


def test_existing_job_snapshot_does_not_gain_the_new_project_role_tool() -> None:
    fixture = _fixture(capabilities=("ones_work_item_search",))

    with pytest.raises(AppError):
        fixture["role_service"].authenticate(fixture["token"])


def test_ones_mcp_v2_stateless_http_requires_bearer_and_supports_both_protocol_eras() -> None:
    fixture = _fixture()
    app = create_mcp_app(
        fixture["registry"],
        database=fixture["runtime"].database,
        max_request_bytes=32 * 1024,
        audit_retention_days=30,
        allowed_hosts=("testserver",),
    )
    base_headers = {
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
    }
    auth_headers = {
        **base_headers,
        "authorization": f"Bearer {fixture['token']}",
        "x-invocation-id": f"{fixture['job'].id}.attempt-{fixture['job'].retry_count}",
    }
    modern_meta = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientInfo": {"name": "runtime-test", "version": "2"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }

    with TestClient(app) as client:
        missing = client.post(
            "/mcp",
            headers=base_headers,
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        duplicate = client.post(
            "/mcp",
            headers=[
                *base_headers.items(),
                ("authorization", f"Bearer {fixture['token']}"),
                ("authorization", f"Bearer {fixture['token']}"),
            ],
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        origin = client.post(
            "/mcp",
            headers={**auth_headers, "origin": "https://untrusted.example"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        wrong_host = client.post(
            "/mcp",
            headers={**auth_headers, "host": "untrusted.example"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        oversized = client.post(
            "/mcp",
            headers=auth_headers,
            content=b"x" * (32 * 1024 + 1),
        )
        initialized = client.post(
            "/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "runtime-test", "version": "1"},
                },
            },
        )
        listed = client.post(
            "/mcp",
            headers={**auth_headers, "mcp-protocol-version": "2025-06-18"},
            json={"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
        )
        discovered_v2 = client.post(
            "/mcp",
            headers={
                **auth_headers,
                "mcp-protocol-version": "2026-07-28",
                "mcp-method": "server/discover",
            },
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "server/discover",
                "params": {"_meta": modern_meta},
            },
        )
        listed_v2 = client.post(
            "/mcp",
            headers={
                **auth_headers,
                "mcp-protocol-version": "2026-07-28",
                "mcp-method": "tools/list",
            },
            json={
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/list",
                "params": {"_meta": modern_meta},
            },
        )
        called_v2 = client.post(
            "/mcp",
            headers={
                **auth_headers,
                "mcp-protocol-version": "2026-07-28",
                "mcp-method": "tools/call",
                "mcp-name": "ones_work_item_search",
                "x-correlation-id": "ones-query-mcp-v2",
            },
            json={
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "_meta": modern_meta,
                    "name": "ones_work_item_search",
                    "arguments": {
                        "keyword": "traceability",
                        "issue_type": "demand",
                        "limit": 10,
                    },
                },
            },
        )
        called_role_members = client.post(
            "/mcp",
            headers={
                **auth_headers,
                "mcp-protocol-version": "2026-07-28",
                "mcp-method": "tools/call",
                "mcp-name": PROJECT_ROLE_MEMBERS_TOOL_IDENTIFIER,
                "x-correlation-id": "ones-role-members-mcp-v2",
            },
            json={
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "_meta": modern_meta,
                    "name": PROJECT_ROLE_MEMBERS_TOOL_IDENTIFIER,
                    "arguments": {"project_uuid": fixture["mock"].config.project_uuid},
                },
            },
        )

    assert missing.status_code == 401
    assert duplicate.status_code == 401
    assert origin.status_code == 403
    assert wrong_host.status_code == 421
    assert oversized.status_code == 413
    assert initialized.status_code == 200
    assert initialized.json()["result"]["serverInfo"]["name"] == "Enterprise ONES MCP"
    assert "mcp-session-id" not in initialized.headers
    assert [item["name"] for item in listed.json()["result"]["tools"]] == [
        PROJECT_ROLE_MEMBERS_TOOL_IDENTIFIER,
        "ones_work_item_search",
    ]
    role_tool = next(
        item
        for item in listed.json()["result"]["tools"]
        if item["name"] == PROJECT_ROLE_MEMBERS_TOOL_IDENTIFIER
    )
    assert role_tool["outputSchema"] == PROJECT_ROLE_MEMBERS_OUTPUT_SCHEMA
    assert discovered_v2.status_code == 200
    assert discovered_v2.json()["result"]["supportedVersions"] == ["2026-07-28"]
    assert discovered_v2.json()["result"]["capabilities"]["tools"] == {"listChanged": False}
    assert "mcp-session-id" not in discovered_v2.headers
    assert [item["name"] for item in listed_v2.json()["result"]["tools"]] == [
        PROJECT_ROLE_MEMBERS_TOOL_IDENTIFIER,
        "ones_work_item_search",
    ]
    assert called_v2.status_code == 200, called_v2.text
    assert called_v2.json()["result"]["isError"] is False
    assert called_v2.json()["result"]["structuredContent"]["items"][0]["number"] == 900101
    assert called_role_members.status_code == 200, called_role_members.text
    assert called_role_members.json()["result"]["isError"] is False
    assert len(called_role_members.json()["result"]["structuredContent"]["roles"]) == 2
    assert "mcp-session-id" not in called_v2.headers


@pytest.mark.parametrize(
    ("keyword", "error_code"),
    [
        ("__403__", "ones_provider_forbidden"),
        ("__429__", "ones_provider_rate_limited"),
        ("__500__", "ones_provider_unavailable"),
        ("__redirect__", "ones_provider_redirect_rejected"),
        ("__bad_json__", "ones_provider_response_invalid"),
        ("__oversize__", "ones_provider_response_too_large"),
        ("__missing_field__", "ones_provider_schema_invalid"),
    ],
)
def test_ones_mcp_classifies_provider_failures_without_persisting_error_bodies(
    keyword: str,
    error_code: str,
) -> None:
    fixture = _fixture()

    with pytest.raises(AppError) as raised:
        fixture["service"].search(
            claims=fixture["claims"],
            arguments={"keyword": keyword, "issue_type": "defect", "limit": 5},
            correlation_id="ones-query-provider-failure",
        )

    assert raised.value.error_code == error_code
    rows = fixture["runtime"].database.execute(
        "select * from mcp_operation_audit where correlation_id = ?",
        ("ones-query-provider-failure",),
    )
    provider = next(row for row in rows if row["event_kind"] == "PROVIDER")
    assert provider["status"] == "FAILED"
    assert provider["error_code"] == error_code
    assert json.loads(provider["provider_response_json"]) == {}


def test_ones_mcp_classifies_provider_timeout_without_persisting_a_response() -> None:
    fixture = _fixture()

    def time_out(*_args: Any, **_kwargs: Any) -> _ProviderResponse:
        raise TimeoutError("fixed test timeout")

    fixture["provider_http"]._open_response = time_out

    with pytest.raises(AppError) as raised:
        fixture["service"].search(
            claims=fixture["claims"],
            arguments={"keyword": "traceability", "issue_type": "demand", "limit": 5},
            correlation_id="ones-query-provider-timeout",
        )

    assert raised.value.error_code == "ones_provider_unavailable"
    provider = fixture["runtime"].database.execute_one(
        "select status, error_code, provider_response_json "
        "from mcp_operation_audit where correlation_id = ? and event_kind = 'PROVIDER'",
        ("ones-query-provider-timeout",),
    )
    assert provider == {
        "status": "FAILED",
        "error_code": "ones_provider_unavailable",
        "provider_response_json": "{}",
    }


@pytest.mark.parametrize(
    ("refresh_outcome", "credential_error"),
    [
        ("invalid_credentials", "ones_invalid_credentials"),
        ("subject_changed", "ones_credential_identity_changed"),
        ("team_missing", "ones_credential_identity_changed"),
    ],
)
def test_ones_mcp_refresh_fails_closed_when_login_identity_is_not_current(
    refresh_outcome: str,
    credential_error: str,
) -> None:
    fixture = _fixture(initial_token="stale-test-token")
    mock = fixture["mock"]

    def verify(*, email: str, password: str) -> VerifiedOnesIdentity:
        assert email == mock.email
        assert password == mock.password
        if refresh_outcome == "invalid_credentials":
            raise NonRetryableExecutionError(
                "fixed mock credentials rejected",
                safe_message="ONES 邮箱或密码错误",
                error_code="ones_invalid_credentials",
            )
        return VerifiedOnesIdentity.create(
            user_uuid=(
                "MOCK-ONES-USER-CHANGED" if refresh_outcome == "subject_changed" else mock.user_uuid
            ),
            display_name=mock.user_name,
            teams=(
                VerifiedOnesTeam(
                    id=(
                        "MOCK-ONES-TEAM-OTHER"
                        if refresh_outcome == "team_missing"
                        else mock.team_uuid
                    ),
                    name="Mock Team",
                ),
            ),
            token=mock.token,
        )

    fixture["login"].verify = verify

    with pytest.raises(AppError) as raised:
        fixture["service"].search(
            claims=fixture["claims"],
            arguments={"keyword": "traceability", "issue_type": "demand", "limit": 5},
            correlation_id=f"ones-query-refresh-{refresh_outcome}",
        )

    assert raised.value.error_code == "ones_credential_reverification_required"
    credential = fixture["runtime"].external_identity_credential_repository.get_by_identity(
        str(fixture["identity"]["id"])
    )
    assert credential is not None
    assert credential["status"] == "REAUTH_REQUIRED"
    assert credential["last_error_code"] == credential_error


def test_ones_mcp_refresh_cas_conflict_does_not_overwrite_the_winning_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(initial_token="stale-test-token")
    credentials = fixture["runtime"].external_identity_credential_repository
    original_rotate = credentials.rotate_token

    def lose_cas(*, credential_id: str, expected_revision: int, token: str) -> dict[str, Any]:
        original_rotate(
            credential_id=credential_id,
            expected_revision=expected_revision,
            token="concurrent-refresh-winner-token",
        )
        return original_rotate(
            credential_id=credential_id,
            expected_revision=expected_revision,
            token=token,
        )

    monkeypatch.setattr(credentials, "rotate_token", lose_cas)

    with pytest.raises(AppError) as raised:
        fixture["service"].search(
            claims=fixture["claims"],
            arguments={"keyword": "traceability", "issue_type": "demand", "limit": 5},
            correlation_id="ones-query-refresh-cas-conflict",
        )

    assert raised.value.error_code == "ones_credential_reverification_required"
    credential = credentials.resolve_active(
        credentials.get_by_identity(str(fixture["identity"]["id"]))["id"]
    )
    assert credential.revision == 2
    assert credential.secrets.token == "concurrent-refresh-winner-token"


def test_ones_mcp_second_401_marks_credential_reverification_required() -> None:
    fixture = _fixture(initial_token="stale-test-token")

    with pytest.raises(AppError) as raised:
        fixture["service"].search(
            claims=fixture["claims"],
            arguments={"keyword": "__401__", "issue_type": "defect", "limit": 5},
            correlation_id="ones-query-second-401",
        )

    assert raised.value.error_code == "ones_credential_reverification_required"
    credential = fixture["runtime"].external_identity_credential_repository.get_by_identity(
        str(fixture["identity"]["id"])
    )
    assert credential is not None
    assert credential["status"] == "REAUTH_REQUIRED"
    assert credential["last_error_code"] == "ones_provider_unauthorized_after_refresh"


def test_ones_mcp_rejects_extra_identity_fields_before_resolving_credentials() -> None:
    fixture = _fixture()

    with pytest.raises(AppError) as raised:
        fixture["service"].search(
            claims=fixture["claims"],
            arguments={
                "keyword": "traceability",
                "issue_type": "demand",
                "limit": 5,
                "user_id": "forged-user",
            },
            correlation_id="ones-query-forged-identity",
        )

    assert raised.value.error_code == "ones_tool_input_invalid"
    assert (
        fixture["runtime"].database.execute(
            "select * from mcp_operation_audit where correlation_id = ?",
            ("ones-query-forged-identity",),
        )
        == []
    )


def test_ones_mcp_fails_closed_for_missing_or_ambiguous_current_identity() -> None:
    missing = _fixture()
    missing["runtime"].database.execute(
        "delete from external_identity_credential where external_identity_id = ?",
        (missing["identity"]["id"],),
    )
    with pytest.raises(AppError) as no_credential:
        missing["service"].search(
            claims=missing["claims"],
            arguments={"keyword": "traceability", "issue_type": "demand", "limit": 5},
            correlation_id="ones-query-no-credential",
        )
    assert no_credential.value.error_code == "ones_credential_reverification_required"

    ambiguous = _fixture()
    ambiguous["runtime"].identity_repository.bind_external_identity(
        user_id="user_local_admin",
        provider="ones",
        tenant_code="default",
        external_subject_id="MOCK-ONES-USER-OTHER",
        connector_id="",
        display_name="Other ONES Identity",
        metadata={
            "team_uuids": [ambiguous["mock"].team_uuid],
            "default_team_id": ambiguous["mock"].team_uuid,
        },
    )
    with pytest.raises(AppError) as multiple:
        ambiguous["service"].search(
            claims=ambiguous["claims"],
            arguments={"keyword": "traceability", "issue_type": "demand", "limit": 5},
            correlation_id="ones-query-ambiguous",
        )
    assert multiple.value.error_code == "ones_identity_ambiguous"


@pytest.mark.parametrize(
    ("revoked_fact", "error_code"),
    [
        ("user_disabled", "ones_principal_user_inactive"),
        ("identity_disabled", "ones_identity_missing"),
        ("tool_revoked", "business_application_denied"),
    ],
)
def test_ones_mcp_rechecks_current_user_identity_and_tool_grant(
    revoked_fact: str,
    error_code: str,
) -> None:
    fixture = _fixture()
    if revoked_fact == "user_disabled":
        fixture["runtime"].database.execute(
            "update app_user set status = 'disabled' where id = ?",
            ("user_local_admin",),
        )
    elif revoked_fact == "identity_disabled":
        fixture["runtime"].database.execute(
            "update user_external_identity set status = 'disabled' where id = ?",
            (fixture["identity"]["id"],),
        )
    else:
        fixture["runtime"].database.execute(
            "delete from rbac_role_application_mcp_tool "
            "where tool_identifier = ? and application_access_id in ("
            "select id from rbac_role_application_access where application_id = ?)",
            (
                "ones_work_item_search",
                fixture["selection"]["application_id"],
            ),
        )

    with pytest.raises(AppError) as raised:
        fixture["service"].search(
            claims=fixture["claims"],
            arguments={"keyword": "traceability", "issue_type": "demand", "limit": 5},
            correlation_id=f"ones-query-{revoked_fact}",
        )

    assert raised.value.error_code == error_code


def test_project_role_members_rechecks_its_own_current_tool_grant() -> None:
    fixture = _fixture()
    fixture["runtime"].database.execute(
        "delete from rbac_role_application_mcp_tool "
        "where tool_identifier = ? and application_access_id in ("
        "select id from rbac_role_application_access where application_id = ?)",
        (
            PROJECT_ROLE_MEMBERS_TOOL_IDENTIFIER,
            fixture["selection"]["application_id"],
        ),
    )

    with pytest.raises(AppError) as raised:
        _list_project_role_members(
            fixture,
            project_uuid=fixture["mock"].config.project_uuid,
            correlation_id="ones-project-role-members-revoked",
        )

    assert raised.value.error_code == "business_application_denied"


def test_ones_mock_has_stable_refresh_identity_and_team_change_controls() -> None:
    mock = MockOnesSettings()
    client = TestClient(create_mock_app(), follow_redirects=False)

    changed = client.post(
        "/project/api/project/auth/login",
        json={
            "email": mock.email,
            "password": mock.config.control_passwords["subject_changed"],
        },
    )
    missing_team = client.post(
        "/project/api/project/auth/login",
        json={
            "email": mock.email,
            "password": mock.config.control_passwords["team_missing"],
        },
    )

    assert changed.status_code == 200
    assert changed.json()["user"]["uuid"] != mock.user_uuid
    assert missing_team.status_code == 200
    assert mock.team_uuid not in {team["uuid"] for team in missing_team.json()["teams"]}


def test_mcp_audit_detail_requires_audit_read_and_records_the_read() -> None:
    fixture = _fixture()
    fixture["service"].search(
        claims=fixture["claims"],
        arguments={"keyword": "traceability", "issue_type": "demand", "limit": 5},
        correlation_id="ones-audit-read",
    )
    runtime = fixture["runtime"]
    audit_row = runtime.database.execute_one(
        "select id from mcp_operation_audit where correlation_id = ? "
        "and event_kind = 'PROVIDER' order by created_at, id limit 1",
        ("ones-audit-read",),
    )
    assert audit_row is not None
    settings = replace(
        runtime.settings,
        environment="test",
        identity=replace(
            runtime.settings.identity,
            enabled=True,
            web_admin_enabled=True,
            test_identity_headers_enabled=True,
            cookie_secure=False,
        ),
    )
    runtime.settings = settings
    app = create_control_plane_app(settings, container_factory=lambda _: runtime)

    with TestClient(app) as client:
        unauthorized = client.get(f"/api/admin/mcp-operation-audits/{audit_row['id']}")
        authorized = client.get(
            f"/api/admin/mcp-operation-audits/{audit_row['id']}",
            headers={"x-admin-user-id": "admin"},
        )
        filtered = client.get(
            "/api/admin/mcp-operation-audits",
            params={
                "job_id": fixture["job"].id,
                "server_code": "ones-mcp",
                "tool_identifier": "ones_work_item_search",
                "event_kind": "PROVIDER",
                "status": "SUCCEEDED",
            },
            headers={"x-admin-user-id": "admin"},
        )
        read_audit = runtime.database.execute_one(
            "select actor_id from audit_event where event_type = 'mcp.audit.read' "
            "order by created_at desc limit 1"
        )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json()["event"]["provider_request"]["variables"]["keyword"] == (
        "traceability"
    )
    assert read_audit == {"actor_id": "user_local_admin"}
    assert filtered.status_code == 200
    assert len(filtered.json()["events"]) == 1
    assert filtered.json()["events"][0]["id"] == audit_row["id"]


def test_ones_mcp_fails_closed_when_required_business_audit_cannot_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()

    def reject_audit(*_args: Any, **_kwargs: Any) -> str:
        raise OnesMcpError(
            "audit unavailable",
            safe_message="ONES 查询审计不可用，请稍后重试",
            error_code="mcp_audit_unavailable",
        )

    monkeypatch.setattr(fixture["service"].audit, "begin", reject_audit)

    with pytest.raises(AppError) as raised:
        fixture["service"].search(
            claims=fixture["claims"],
            arguments={"keyword": "traceability", "issue_type": "demand", "limit": 5},
            correlation_id="ones-query-audit-down",
        )

    assert raised.value.error_code == "mcp_audit_unavailable"


def test_mcp_audit_failure_rolls_back_platform_audit_and_logs_only_error_type(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fixture = _fixture()
    database = fixture["runtime"].database
    original_execute = database.execute

    def fail_mcp_detail(sql: str, params: Any = ()) -> list[dict[str, Any]]:
        if "insert into mcp_operation_audit" in sql:
            raise RuntimeError("fixed persistence failure")
        return original_execute(sql, params)

    before = database.execute_one(
        "select count(*) as count from audit_event where event_type = 'mcp.operation.started'"
    )
    assert before is not None
    caplog.set_level("ERROR", logger="app.modules.mcp_audit.application")
    monkeypatch.setattr(database, "execute", fail_mcp_detail)

    with pytest.raises(AppError) as raised:
        fixture["service"].search(
            claims=fixture["claims"],
            arguments={"keyword": "traceability", "issue_type": "demand", "limit": 5},
            correlation_id="ones-query-audit-transaction",
        )

    monkeypatch.setattr(database, "execute", original_execute)
    after = database.execute_one(
        "select count(*) as count from audit_event where event_type = 'mcp.operation.started'"
    )
    assert raised.value.error_code == "mcp_audit_unavailable"
    assert after == before
    assert "error_type=RuntimeError" in caplog.text
    assert "traceability" not in caplog.text
    assert fixture["token"] not in caplog.text


def test_ones_mcp_rejects_provider_auth_fields_before_business_audit() -> None:
    fixture = _fixture()
    response = {
        "data": {
            "workItems": {
                "items": [],
                "total": 0,
                "truncated": False,
            }
        },
        "token": "must-never-be-audited",
    }
    fixture["provider_http"]._open_response = lambda *_args: _ProviderResponse(
        200,
        json.dumps(response).encode("utf-8"),
    )

    with pytest.raises(AppError) as raised:
        fixture["service"].search(
            claims=fixture["claims"],
            arguments={"keyword": "traceability", "issue_type": "demand", "limit": 5},
            correlation_id="ones-query-secret-field",
        )

    assert raised.value.error_code == "mcp_audit_auth_material_forbidden"
    rows = fixture["runtime"].database.execute(
        "select provider_response_json from mcp_operation_audit where correlation_id = ?",
        ("ones-query-secret-field",),
    )
    assert rows
    assert all("must-never-be-audited" not in row["provider_response_json"] for row in rows)


def test_mcp_audit_retention_deletes_business_payload_and_invalid_config_is_unready() -> None:
    fixture = _fixture()
    fixture["service"].search(
        claims=fixture["claims"],
        arguments={"keyword": "traceability", "issue_type": "demand", "limit": 5},
        correlation_id="ones-query-expired-audit",
    )
    fixture["runtime"].database.execute(
        "update mcp_operation_audit set created_at = '2000-01-01T00:00:00+00:00' "
        "where correlation_id = ?",
        ("ones-query-expired-audit",),
    )

    deleted = fixture["service"].audit.purge_expired(retention_days=30)

    assert deleted == 1
    app = create_mcp_app(
        fixture["service"],
        database=fixture["runtime"].database,
        max_request_bytes=32 * 1024,
        audit_retention_days=0,
        allowed_hosts=("testserver",),
    )
    with TestClient(app) as client:
        health = client.get("/health")
    assert health.status_code == 503


def test_ones_mcp_readiness_requires_the_credential_and_audit_schema() -> None:
    fixture = _fixture()
    fixture["runtime"].database.execute(
        "delete from schema_migration where cast(version as integer) >= 105"
    )
    app = create_mcp_app(
        fixture["service"],
        database=fixture["runtime"].database,
        max_request_bytes=32 * 1024,
        audit_retention_days=30,
        allowed_hosts=("testserver",),
    )

    with TestClient(app) as client:
        health = client.get("/health")

    assert health.status_code == 503
    assert health.json()["status"] == "degraded"
