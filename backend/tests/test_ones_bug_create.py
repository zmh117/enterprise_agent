from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app.modules.external_action.card import render_confirmation_card
from app.modules.external_action.domain import ExternalActionIntentFacts, json_hash
from app.modules.external_action.repository import ExternalActionRepository
from app.modules.external_action.service import ExternalActionService, ExternalActionTokenSigner
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.modules.mcp_audit import McpAuditContext
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator
from app.shared.ones_tool_contracts import ONES_CREATE_BUG_TOOL_IDENTIFIER, ONES_TOOL_CONTRACTS
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError
from ones_mock.mock_ones_api import MockOnesSettings, create_app
from scripts.sync_ones_bug_create_field_catalog import build_catalog, render_catalog
from services.ones_mcp_server.bug_create import (
    compile_bug_create,
    compiled_bug_matches_readback,
    validate_bug_create_arguments,
)
from services.ones_mcp_server.bug_create_catalog import BugCreateFieldCatalog
from services.ones_mcp_server.provider.bug_create import (
    BugCreatePreflight,
    OnesBugCreateProvider,
)
from services.ones_mcp_server.errors import OnesMcpError, OnesProviderUnauthorized
from services.ones_mcp_server.tools.bug_create import OnesBugCreateService
from services.external_action_worker.ones_adapter import OnesExternalActionAdapter


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOL = ONES_CREATE_BUG_TOOL_IDENTIFIER


class _Audit:
    def record(self, *_args: object, **_kwargs: object) -> None:
        return None


class _ServiceAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def begin(self, context: object, *, business_request: dict[str, Any]) -> object:
        self.events.append({"kind": "begin", "request": business_request})
        return SimpleNamespace(mcp_call_id="mcp-create-1")

    def enrich_context(self, handle: object, context: object) -> object:
        return handle

    def append_event(self, handle: object, **values: Any) -> None:
        self.events.append(values)

    def complete(self, handle: object, **values: Any) -> None:
        self.events.append({"kind": "complete", **values})


def _configure_connector(database: Database) -> None:
    database.execute(
        """
        insert into dingtalk_enterprise
          (id, name, corp_id, status, verification_event_id, verified_at,
           revision, created_by, created_at, updated_at)
        values ('enterprise-1', '确认企业', 'corp-1', 'ACTIVE', '',
                '2026-09-03T00:00:00Z', 1, 'user-1',
                '2026-09-03T00:00:00Z', '2026-09-03T00:00:00Z')
        """
    )
    database.execute(
        """
        insert into integration_connector
          (id, connector_type, name, enabled, metadata, allow_ingress,
           revision, deleted, created_at, updated_at)
        values ('connector-1', 'dingtalk_enterprise_stream', 'confirm', 1, ?, 1,
                1, 0, '2026-09-03T00:00:00Z', '2026-09-03T00:00:00Z')
        """,
        (
            '{"card_templates":{"external_action_confirmation":'
            '{"contract_version":"external-action-confirmation-v1",'
            '"template_id":"ones-confirmation.schema"}}}',
        ),
    )


def _option(catalog: BugCreateFieldCatalog, field: str) -> str:
    return catalog.require_field(field).options[0]["uuid"]


def _arguments(catalog: BugCreateFieldCatalog, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "title": "称量结果显示错误",
        "project_uuid": "project-1",
        "description": "操作步骤：称量两次\n期望结果：标签正确\n实际结果：标签错误",
        "environment": "测试环境",
        "assignee_uuid": "user-owner",
        "defect_type_uuid": _option(catalog, "defect_type_uuid"),
        "urgency_uuid": _option(catalog, "urgency_uuid"),
        "severity_uuid": _option(catalog, "severity_uuid"),
        "discovery_difficulty_uuid": _option(catalog, "discovery_difficulty_uuid"),
        "reproduction_probability_uuid": _option(catalog, "reproduction_probability_uuid"),
        "product_uuids": ["product-1", "product-1"],
        "product_module_uuids": ["module-1", "module-1"],
        "discovery_stage_uuid": _option(catalog, "discovery_stage_uuid"),
        "online_defect_uuid": _option(catalog, "online_defect_uuid"),
        "historical_defect_uuid": _option(catalog, "historical_defect_uuid"),
        "affected_version_uuids": [
            _option(catalog, "affected_version_uuids"),
            _option(catalog, "affected_version_uuids"),
        ],
        "watcher_uuids": ["user-extra", "user-owner", "user-extra"],
        "field_provenance": [
            {"field": "environment", "source": "conversation_context"},
            {"field": "severity_uuid", "source": "field_catalog"},
        ],
    }
    values.update(overrides)
    return values


def _display(catalog: BugCreateFieldCatalog) -> dict[str, dict[str, str]]:
    affected = _option(catalog, "affected_version_uuids")
    return {
        "project_uuid": {"project-1": "示例项目"},
        "user_uuids": {
            "user-current": "当前用户",
            "user-owner": "负责人甲",
            "user-extra": "关注者乙",
        },
        "product_uuids": {"product-1": "MES"},
        "product_module_uuids": {"module-1": "称量"},
        "affected_version_uuids": {affected: "V5.0.1"},
    }


def test_create_bug_contract_is_strict_complete_and_governed() -> None:
    contract = ONES_TOOL_CONTRACTS[TOOL]
    definition = MCP_TOOL_MANIFEST[TOOL]
    assert contract.operation_code == "ones.task.create"
    assert contract.effect == "mutation"
    assert contract.confirmation_policy == "external_action_card_v1"
    assert contract.target_policy == "single_new_defect"
    assert definition.read_only is False
    assert definition.destructive is True
    assert definition.idempotent is True
    assert "仅钉钉来源" in contract.description
    assert "逐次确认" in contract.description
    Draft202012Validator.check_schema(contract.input_schema)
    catalog = BugCreateFieldCatalog.load()
    Draft202012Validator(contract.input_schema).validate(_arguments(catalog))

    forbidden = (
        "team_uuid",
        "provider_base_url",
        "headers",
        "token",
        "issue_type_uuid",
        "description_html",
        "field_values",
        "attachments",
        "related_task_uuids",
        "parent_uuid",
        "add_manhours",
        "sprint_uuid",
        "fixed_version_uuids",
    )
    for field in forbidden:
        with pytest.raises(Exception):
            Draft202012Validator(contract.input_schema).validate(
                {**_arguments(catalog), field: "forbidden"}
            )
    for required in contract.input_schema["required"]:
        invalid = _arguments(catalog)
        invalid.pop(required)
        with pytest.raises(Exception):
            Draft202012Validator(contract.input_schema).validate(invalid)


def test_catalog_is_generated_bounded_and_name_resolution_is_document_first() -> None:
    source = (PROJECT_ROOT / "ones_mock/ones/查询条件字典.yaml").read_bytes()
    generated = PROJECT_ROOT / "services/ones_mcp_server/resources/bug_create_field_catalog.json"
    assert render_catalog(build_catalog(source)) == generated.read_bytes()
    catalog = BugCreateFieldCatalog.load()
    assert catalog.fixed_issue_type_uuid == "B4TV9bu5"
    assert len(catalog.fields) == 15
    assert not catalog.reference_indexes["product_modules"]
    calls: list[str] = []

    def no_match(value: str) -> list[dict[str, str]]:
        calls.append(value)
        return []

    def module_match(value: str) -> list[dict[str, str]]:
        calls.append(value)
        return [{"uuid": "module-1", "name": "称量"}]

    project = catalog.reference_indexes["projects"][0]
    assert catalog.resolve_name(
        "projects",
        project["name"],
        live_lookup=no_match,
    ) == project
    assert calls == []
    assert catalog.resolve_name(
        "product_modules",
        "称量",
        live_lookup=module_match,
    ) == {"uuid": "module-1", "name": "称量"}
    assert calls == ["称量"]
    affected = catalog.reference_indexes["affected_versions"][0]
    assert catalog.resolve_name(
        "affected_versions",
        affected["name"],
        live_lookup=no_match,
    ) == affected
    assert calls == ["称量"]
    with pytest.raises(Exception):
        catalog.resolve_name(
            "product_modules",
            "同名模块",
            live_lookup=lambda _value: [
                {"uuid": "module-1", "name": "同名模块"},
                {"uuid": "module-2", "name": "同名模块"},
            ],
        )


@pytest.mark.parametrize(
    "overrides,error_code",
    [
        ({"description": "待补充复现步骤"}, "ones_bug_create_draft_incomplete"),
        ({"description": "<p>任意 HTML</p>"}, "ones_bug_create_html_rejected"),
        ({"title": "   "}, "ones_bug_create_arguments_invalid"),
        (
            {
                "field_provenance": [
                    {"field": "environment", "source": "current_message"},
                    {"field": "environment", "source": "ones_read"},
                ]
            },
            "ones_bug_create_provenance_invalid",
        ),
    ],
)
def test_create_argument_normalization_rejects_incomplete_or_unsafe_values(
    overrides: dict[str, Any], error_code: str
) -> None:
    catalog = BugCreateFieldCatalog.load()
    with pytest.raises(Exception) as caught:
        validate_bug_create_arguments(_arguments(catalog, **overrides))
    assert getattr(caught.value, "error_code", "") == error_code


def test_compiler_maps_every_field_deduplicates_watchers_and_renders_full_card() -> None:
    catalog = BugCreateFieldCatalog.load()
    compiled = compile_bug_create(
        _arguments(catalog),
        catalog=catalog,
        team_uuid=catalog.source_team_uuid,
        task_uuid="task-create-1",
        current_user_uuid="user-current",
        display_values=_display(catalog),
    )
    task = compiled.provider_payload["tasks"][0]
    assert task["uuid"] == "task-create-1"
    assert task["summary"] == task["field_values"][-2]["value"]
    assert task["assign"] == task["field_values"][1]["value"]
    assert task["watchers"] == ["user-current", "user-extra", "user-owner"]
    assert task["parent_uuid"] == ""
    assert task["add_manhours"] == []
    assert task["issue_type_uuid"] == "B4TV9bu5"
    assert len(task["field_values"]) == 15
    assert task["field_values"][-1]["value"].startswith("<p>")
    assert len(compiled.summary["fields"]) == 18
    card = render_confirmation_card(
        {
            "execution_provider_code": "ones",
            "operation_code": "ones.task.create",
            "target_resource_type": "task",
        },
        compiled.summary,
    )
    assert card["operationName"] == "创建缺陷"
    assert "环境（建议值）：测试环境" in card["detailText"]
    assert "工作项类型（系统固定）：缺陷" in card["detailText"]
    assert "关注者（系统默认）：当前用户、关注者乙、负责人甲" in card["detailText"]
    assert "task-create-1" not in card["detailText"]
    assert "field041" not in card["detailText"]
    assert "<p>" not in card["detailText"]


def test_card_rejects_over_budget_without_truncation() -> None:
    catalog = BugCreateFieldCatalog.load()
    compiled = compile_bug_create(
        _arguments(catalog, description="长描述" * 1500),
        catalog=catalog,
        team_uuid=catalog.source_team_uuid,
        task_uuid="task-create-long",
        current_user_uuid="user-current",
        display_values=_display(catalog),
    )
    with pytest.raises(Exception) as caught:
        render_confirmation_card(
            {
                "execution_provider_code": "ones",
                "operation_code": "ones.task.create",
                "target_resource_type": "task",
            },
            compiled.summary,
        )
    assert getattr(caught.value, "error_code", "") == "external_action_card_detail_too_large"


class _Http:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str],
        query: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append({"method": "POST", "path": path, "payload": payload, "headers": headers})
        return self.responses.pop(0)

    def get_json(
        self,
        path: str,
        payload: dict[str, Any] | None,
        *,
        headers: dict[str, str],
        query: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append({"method": "GET", "path": path, "payload": payload, "headers": headers})
        return self.responses.pop(0)


def _preflight_response(catalog: BugCreateFieldCatalog) -> dict[str, Any]:
    affected = _option(catalog, "affected_version_uuids")
    return {
        "ready": True,
        "can_create": True,
        "layout_version": "layout-v1",
        "required_field_uuids": sorted(field.provider_field_uuid for field in catalog.fields),
        "project": {"uuid": "project-1", "name": "示例项目"},
        "issue_type": {"uuid": "B4TV9bu5", "name": "缺陷"},
        "users": [
            {"uuid": "user-current", "name": "当前用户"},
            {"uuid": "user-owner", "name": "负责人甲"},
            {"uuid": "user-extra", "name": "关注者乙"},
        ],
        "products": [{"uuid": "product-1", "name": "MES"}],
        "product_modules": [
            {"uuid": "module-1", "name": "称量", "product_uuids": ["product-1"]}
        ],
        "affected_versions": [{"uuid": affected, "name": "V5.0.1", "kind": "affected"}],
    }


def test_provider_uses_only_fixed_paths_headers_and_full_readback() -> None:
    catalog = BugCreateFieldCatalog.load()
    arguments = _arguments(catalog)
    http = _Http([_preflight_response(catalog)])
    provider = OnesBugCreateProvider(http, catalog=catalog)  # type: ignore[arg-type]
    preflight = provider.preflight_create(
        team_uuid=catalog.source_team_uuid,
        provider_user_id="user-current",
        token="test-only-token",
        arguments=arguments,
    )
    compiled = compile_bug_create(
        arguments,
        catalog=catalog,
        team_uuid=catalog.source_team_uuid,
        task_uuid="task-create-provider",
        current_user_uuid="user-current",
        display_values=preflight.display_values,
    )
    readback = {**compiled.provider_payload["tasks"][0], "number": 42}
    http.responses.extend(
        [
            {
                "tasks": [
                    {
                        "uuid": "task-create-provider",
                        "project_uuid": "project-1",
                        "issue_type_uuid": "B4TV9bu5",
                        "summary": arguments["title"],
                        "parent_uuid": "",
                        "number": 42,
                    }
                ],
                "bad_tasks": [],
            },
            {"found": True, "task": readback},
        ]
    )
    assert provider.create_bug(
        team_uuid=catalog.source_team_uuid,
        provider_user_id="user-current",
        token="test-only-token",
        payload=compiled.provider_payload,
    )["number"] == 42
    assert compiled_bug_matches_readback(
        compiled,
        provider.read_created_bug(
            team_uuid=catalog.source_team_uuid,
            task_uuid="task-create-provider",
            provider_user_id="user-current",
            token="test-only-token",
        )
        or {},
    )
    assert [call["method"] for call in http.calls] == ["POST", "POST", "GET"]
    assert http.calls[0]["path"].endswith("/tasks/create_preflight")
    assert http.calls[1]["path"].endswith("/tasks/add3")
    assert http.calls[2]["path"].endswith("/tasks/task-create-provider/create_readback")
    assert all(set(call["headers"]) == {"Ones-Auth-Token", "Ones-User-Id"} for call in http.calls)


def test_provider_preflight_fails_closed_for_catalog_capability_and_layout() -> None:
    catalog = BugCreateFieldCatalog.load()
    invalid_option_http = _Http([])
    invalid_option_provider = OnesBugCreateProvider(
        invalid_option_http, catalog=catalog  # type: ignore[arg-type]
    )
    with pytest.raises(OnesMcpError) as invalid_option:
        invalid_option_provider.preflight_create(
            team_uuid=catalog.source_team_uuid,
            provider_user_id="user-current",
            token="test-only-token",
            arguments=_arguments(catalog, urgency_uuid="missing-option"),
        )
    assert invalid_option.value.error_code == "ones_bug_create_option_invalid"
    assert invalid_option_http.calls == []

    unavailable_http = _Http([{"ready": False, "can_create": False}])
    unavailable_provider = OnesBugCreateProvider(
        unavailable_http, catalog=catalog  # type: ignore[arg-type]
    )
    with pytest.raises(OnesMcpError) as unavailable:
        unavailable_provider.preflight_create(
            team_uuid=catalog.source_team_uuid,
            provider_user_id="user-current",
            token="test-only-token",
            arguments=_arguments(catalog),
        )
    assert unavailable.value.error_code == "ones_bug_create_capability_not_ready"

    incompatible = _preflight_response(catalog)
    incompatible["required_field_uuids"] = []
    incompatible_provider = OnesBugCreateProvider(
        _Http([incompatible]), catalog=catalog  # type: ignore[arg-type]
    )
    with pytest.raises(OnesMcpError) as layout:
        incompatible_provider.preflight_create(
            team_uuid=catalog.source_team_uuid,
            provider_user_id="user-current",
            token="test-only-token",
            arguments=_arguments(catalog),
        )
    assert layout.value.error_code == "ones_bug_create_layout_mismatch"


@pytest.mark.parametrize("conversation_type", ["private", "group"])
def test_mcp_prepare_creates_only_private_confirmation_after_preflight(
    conversation_type: str,
) -> None:
    catalog = BugCreateFieldCatalog.load()
    arguments = _arguments(catalog)

    class _Provider:
        def __init__(self) -> None:
            self.preflight_calls = 0
            self.create_calls = 0

        def preflight_create(self, **_values: Any) -> BugCreatePreflight:
            self.preflight_calls += 1
            return BugCreatePreflight(
                layout_version="layout-v1",
                validation_hash="v" * 64,
                display_values=_display(catalog),
            )

        def create_bug(self, **_values: Any) -> dict[str, Any]:
            self.create_calls += 1
            return {"created": True}

    class _Database:
        @staticmethod
        def execute_one(_sql: str, _parameters: object) -> dict[str, int]:
            return {"revision": 7}

    class _Resolver:
        database = _Database()

        @staticmethod
        def authenticate(_token: str, *, required_scope: str) -> dict[str, str]:
            assert required_scope.endswith(":ones_create_bug:invoke")
            return {"job_id": "job-1"}

        @staticmethod
        def audit_context(*_args: object, **_kwargs: object) -> object:
            return McpAuditContext(
                correlation_id="correlation-1",
                job_id="job-1",
                session_id="session-1",
                invocation_id="job-1.attempt-0",
                actor_user_id="user-1",
                server_code="ones-mcp",
                tool_identifier=TOOL,
            )

        @staticmethod
        def resolve(*_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(
                job_id="job-1",
                session_id="session-1",
                actor_user_id="user-1",
                business_application_id="application-1",
                agent_publication_id="agent-publication-1",
                application_publication_id="application-publication-1",
                principal_jti="principal-1",
                external_identity_id="ones-identity-1",
                provider_user_id="user-current",
                provider_email="ignored@example.test",
                team_id=catalog.source_team_uuid,
                credential=SimpleNamespace(
                    id="credential-1",
                    revision=3,
                    secrets=SimpleNamespace(token="provider-token"),
                ),
            )

        @staticmethod
        def resolve_confirmation_route(_principal: object) -> object:
            return SimpleNamespace(
                source_connector_id="connector-1",
                dingtalk_enterprise_id="enterprise-1",
                target_external_subject_id="staff-1",
                target_union_id="union-1",
                conversation_type=conversation_type,
            )

    class _Actions:
        def __init__(self) -> None:
            self.values: dict[str, Any] = {}

        def prepare(self, **values: Any) -> tuple[dict[str, Any], bool]:
            self.values = values
            return (
                {
                    "id": "action-create-1",
                    "revision": 1,
                    "expires_at": "2030-01-01T00:00:00+00:00",
                },
                True,
            )

    provider = _Provider()
    actions = _Actions()
    service = OnesBugCreateService(
        resolver=_Resolver(),  # type: ignore[arg-type]
        provider=provider,  # type: ignore[arg-type]
        catalog=catalog,
        external_actions=actions,  # type: ignore[arg-type]
        audit=_ServiceAudit(),  # type: ignore[arg-type]
        credentials=SimpleNamespace(mark_used=lambda **_kwargs: None),  # type: ignore[arg-type]
        credential_refresh=SimpleNamespace(),  # type: ignore[arg-type]
    )
    output = service.invoke(
        claims={"job_id": "job-1"},
        arguments=arguments,
        correlation_id="correlation-1",
        invocation_id="job-1.attempt-0",
    )

    assert output["status"] == "confirmation_required"
    assert provider.preflight_calls == 1
    assert provider.create_calls == 0
    facts = actions.values["facts"]
    assert isinstance(facts, ExternalActionIntentFacts)
    assert facts.operation_code == "ones.task.create"
    assert facts.target_external_subject_id == "staff-1"
    assert len(facts.target_resource_id) == 16
    assert facts.target_resource_id not in str(output["summary"])
    assert actions.values["ttl_seconds"] == 900
    assert set(actions.values["arguments"]) == {"request"}


def _summary(title: str) -> dict[str, Any]:
    return {
        "operation": "创建缺陷",
        "target": title,
        "fields": [
            {"label": f"字段{index}", "value": f"值{index}", "marker": ""}
            for index in range(18)
        ],
    }


def _facts(
    catalog: BugCreateFieldCatalog,
    *,
    task_uuid: str,
    supersedes: str = "",
) -> ExternalActionIntentFacts:
    request = {"title": "同内容"}
    return ExternalActionIntentFacts(
        job_id="job-1",
        session_id="session-1",
        actor_user_id="user-1",
        business_application_id="application-1",
        agent_publication_id="agent-publication-1",
        application_publication_id="application-publication-1",
        source_connector_id="connector-1",
        dingtalk_enterprise_id="enterprise-1",
        target_external_subject_id="staff-1",
        target_union_id="union-1",
        server_code="ones-mcp",
        tool_identifier=TOOL,
        schema_hash=MCP_TOOL_MANIFEST[TOOL].schema_hash,
        confirmation_policy="external_action_card_v1",
        operation_code="ones.task.create",
        execution_provider_code="ones",
        execution_external_identity_id="ones-identity-1",
        execution_scope_id=catalog.source_team_uuid,
        target_resource_type="task",
        target_resource_id=task_uuid,
        precondition={"confirmed_values": request},
        field_catalog_version=catalog.catalog_version,
        field_catalog_hash=catalog.content_sha256,
        supersedes_intent_id=supersedes,
    )


def test_create_intent_uses_mcp_call_id_and_supersedes_atomically() -> None:
    database = Database("sqlite:///:memory:")
    Migrator(database, default_migrations_dir(), migrator_build="bug-chain-test").run()
    database.execute("pragma foreign_keys = off")
    _configure_connector(database)
    repository = ExternalActionRepository(database)
    signer = ExternalActionTokenSigner("k" * 32)
    service = ExternalActionService(
        repository,
        signer,
        _Audit(),  # type: ignore[arg-type]
    )
    catalog = BugCreateFieldCatalog.load()
    frozen = {"request": {"title": "同内容"}}

    first, created = service.prepare(
        facts=_facts(catalog, task_uuid="task-create-a"),
        arguments=frozen,
        arguments_hash=json_hash(frozen["request"]),
        safe_summary=_summary("版本一"),
        mcp_call_id="call-create-a",
    )
    replay, replay_created = service.prepare(
        facts=_facts(catalog, task_uuid="task-create-other"),
        arguments=frozen,
        arguments_hash=json_hash(frozen["request"]),
        safe_summary=_summary("版本一"),
        mcp_call_id="call-create-a",
    )
    with pytest.raises(NonRetryableExecutionError) as conflicting_replay:
        service.prepare(
            facts=_facts(
                catalog,
                task_uuid="task-create-other",
                supersedes=str(first["id"]),
            ),
            arguments=frozen,
            arguments_hash=json_hash(frozen["request"]),
            safe_summary=_summary("版本一"),
            mcp_call_id="call-create-a",
        )
    assert conflicting_replay.value.error_code == "external_action_mcp_call_conflict"
    independent, independent_created = service.prepare(
        facts=_facts(catalog, task_uuid="task-create-b"),
        arguments=frozen,
        arguments_hash=json_hash(frozen["request"]),
        safe_summary=_summary("独立同内容"),
        mcp_call_id="call-create-b",
    )
    revised, revised_created = service.prepare(
        facts=_facts(catalog, task_uuid="task-create-c", supersedes=str(first["id"])),
        arguments={"request": {"title": "修订"}},
        arguments_hash=json_hash({"title": "修订"}),
        safe_summary=_summary("版本二"),
        mcp_call_id="call-create-c",
    )

    assert created and not replay_created and independent_created and revised_created
    assert replay["id"] == first["id"]
    assert independent["id"] != first["id"]
    old = repository.get(str(first["id"])) or {}
    assert old["status"] == "SUPERSEDED"
    assert old["superseded_by_intent_id"] == revised["id"]
    assert revised["supersedes_intent_id"] == first["id"]
    assert revised["proposal_chain_id"] == first["proposal_chain_id"]
    assert repository.claim_approved(worker_id="worker") is None
    outboxes = database.execute(
        "select event_kind, payload_json from external_action_card_outbox order by created_at, id"
    )
    assert len(outboxes) == 4
    assert any("已被新版本替代" in str(item["payload_json"]) for item in outboxes)
    old_callback = service.handle_callback(
        connector_id="connector-1",
        corp_id="corp-1",
        out_track_id=str(first["id"]),
        user_id="staff-1",
        action="agree",
        revision=1,
        intent_token=signer.issue(str(first["id"]), 1),
    )
    assert old_callback.status == "SUPERSEDED"
    assert old_callback.duplicate is True
    assert (
        old_callback.response["cardData"]["cardParamMap"]["statusText"]
        == "已被新版本替代，请使用最新确认卡"
    )

    approved, changed = repository.transition_from_callback(
        intent_id=str(independent["id"]),
        expected_revision=1,
        action="agree",
    )
    assert changed is True and approved["status"] == "APPROVED"
    intent_count = database.execute_one("select count(*) as count from external_action_intent")
    outbox_count = database.execute_one("select count(*) as count from external_action_card_outbox")
    assert intent_count is not None and outbox_count is not None
    before_intents = int(intent_count["count"])
    before_outboxes = int(outbox_count["count"])
    with pytest.raises(NonRetryableExecutionError) as denied:
        service.prepare(
            facts=_facts(
                catalog,
                task_uuid="task-create-denied",
                supersedes=str(independent["id"]),
            ),
            arguments={"request": {"title": "不可替代"}},
            arguments_hash=json_hash({"title": "不可替代"}),
            safe_summary=_summary("不可替代"),
            mcp_call_id="call-create-denied",
        )
    assert denied.value.error_code == "external_action_supersede_denied"
    current_intents = database.execute_one(
        "select count(*) as count from external_action_intent"
    )
    current_outboxes = database.execute_one(
        "select count(*) as count from external_action_card_outbox"
    )
    assert current_intents is not None and current_intents["count"] == before_intents
    assert current_outboxes is not None and current_outboxes["count"] == before_outboxes


def test_only_one_concurrent_revision_can_supersede_a_pending_proposal() -> None:
    database = Database("sqlite:///:memory:", pool_max_size=1)
    Migrator(database, default_migrations_dir(), migrator_build="bug-chain-race-test").run()
    database.execute("pragma foreign_keys = off")
    _configure_connector(database)
    repository = ExternalActionRepository(database)
    service = ExternalActionService(
        repository,
        ExternalActionTokenSigner("k" * 32),
        _Audit(),  # type: ignore[arg-type]
    )
    catalog = BugCreateFieldCatalog.load()
    first, _ = service.prepare(
        facts=_facts(catalog, task_uuid="task-race-base"),
        arguments={"request": {"title": "原版本"}},
        arguments_hash=json_hash({"title": "原版本"}),
        safe_summary=_summary("原版本"),
        mcp_call_id="call-race-base",
    )
    barrier = Barrier(2)

    def revise(index: int) -> str:
        barrier.wait()
        try:
            service.prepare(
                facts=_facts(
                    catalog,
                    task_uuid=f"task-race-{index}",
                    supersedes=str(first["id"]),
                ),
                arguments={"request": {"title": f"修订{index}"}},
                arguments_hash=json_hash({"title": f"修订{index}"}),
                safe_summary=_summary(f"修订{index}"),
                mcp_call_id=f"call-race-{index}",
            )
        except NonRetryableExecutionError as exc:
            return exc.error_code
        return "committed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(revise, (1, 2)))

    assert sorted(results) == ["committed", "external_action_supersede_denied"]
    old = repository.get(str(first["id"])) or {}
    assert old["status"] == "SUPERSEDED"
    successor_count = database.execute_one(
        "select count(*) as count from external_action_intent where supersedes_intent_id = ?",
        (first["id"],),
    )
    assert successor_count is not None and successor_count["count"] == 1


def test_create_attempt_is_persisted_once_before_provider_call() -> None:
    database = Database("sqlite:///:memory:")
    Migrator(database, default_migrations_dir(), migrator_build="bug-attempt-test").run()
    database.execute("pragma foreign_keys = off")
    _configure_connector(database)
    repository = ExternalActionRepository(database)
    service = ExternalActionService(
        repository,
        ExternalActionTokenSigner("k" * 32),
        _Audit(),  # type: ignore[arg-type]
    )
    catalog = BugCreateFieldCatalog.load()
    frozen = {"request": {"title": "尝试"}}
    intent, _ = service.prepare(
        facts=_facts(catalog, task_uuid="task-attempt"),
        arguments=frozen,
        arguments_hash=json_hash(frozen["request"]),
        safe_summary=_summary("尝试"),
        mcp_call_id="call-attempt",
    )
    database.execute(
        "update external_action_intent set status = 'EXECUTING' where id = ?",
        (intent["id"],),
    )
    first, first_started = repository.mark_provider_attempt_started(
        str(intent["id"]), request_hash="a" * 64, catalog_hash=catalog.content_sha256
    )
    second, second_started = repository.mark_provider_attempt_started(
        str(intent["id"]), request_hash="a" * 64, catalog_hash=catalog.content_sha256
    )
    assert first_started is True
    assert second_started is False
    assert first["provider_attempt_status"] == second["provider_attempt_status"] == "STARTED"


@pytest.mark.parametrize(
    "provider_failures,expected_create_calls,expected_readback_token",
    [
        ((), 1, "provider-token"),
        (
            (
                RetryableExecutionError(
                    "synthetic timeout",
                    safe_message="模拟超时",
                    error_code="synthetic_timeout",
                ),
            ),
            1,
            "provider-token",
        ),
        (
            (
                OnesMcpError(
                    "synthetic invalid response",
                    safe_message="模拟非法响应",
                    error_code="ones_bug_create_response_invalid",
                ),
            ),
            1,
            "provider-token",
        ),
        ((ConnectionError("synthetic disconnect"),), 1, "provider-token"),
        (
            (
                OnesProviderUnauthorized(
                    "synthetic unauthorized",
                    safe_message="模拟登录失效",
                    error_code="ones_provider_unauthorized",
                ),
                RetryableExecutionError(
                    "synthetic timeout after refresh",
                    safe_message="模拟刷新后超时",
                    error_code="synthetic_timeout_after_refresh",
                ),
            ),
            2,
            "refreshed-provider-token",
        ),
    ],
)
def test_worker_create_attempt_is_never_replayed_and_result_is_verified(
    provider_failures: tuple[Exception, ...],
    expected_create_calls: int,
    expected_readback_token: str,
) -> None:
    database = Database("sqlite:///:memory:")
    Migrator(database, default_migrations_dir(), migrator_build="bug-worker-test").run()
    database.execute("pragma foreign_keys = off")
    _configure_connector(database)
    catalog = BugCreateFieldCatalog.load()
    arguments = _arguments(catalog)
    preflight = BugCreatePreflight(
        layout_version="layout-v1",
        validation_hash="v" * 64,
        display_values=_display(catalog),
    )
    compiled = compile_bug_create(
        arguments,
        catalog=catalog,
        team_uuid=catalog.source_team_uuid,
        task_uuid="WorkerCreate01",
        current_user_uuid="user-current",
        display_values=preflight.display_values,
    )
    facts = replace(
        _facts(catalog, task_uuid="WorkerCreate01"),
        precondition={
            "identity_revision": 7,
            "credential_revision": 3,
                "layout_version": preflight.layout_version,
                "validation_hash": preflight.validation_hash,
                "display_values": preflight.display_values,
                "confirmed_values": compiled.normalized_arguments,
        },
    )
    repository = ExternalActionRepository(database)
    service = ExternalActionService(
        repository,
        ExternalActionTokenSigner("k" * 32),
        _Audit(),  # type: ignore[arg-type]
    )
    intent, _ = service.prepare(
        facts=facts,
        arguments={"request": compiled.normalized_arguments},
        arguments_hash=json_hash(compiled.normalized_arguments),
        safe_summary=compiled.summary,
        mcp_call_id="call-worker-create",
    )
    database.execute(
        "update external_action_intent set status = 'EXECUTING' where id = ?",
        (intent["id"],),
    )
    intent = repository.get(str(intent["id"])) or {}

    class _CreateProvider:
        def __init__(self) -> None:
            self.create_calls = 0
            self.preflight_calls = 0
            self.payload: dict[str, Any] | None = None
            self.failures = list(provider_failures)
            self.readback_tokens: list[str] = []

        def preflight_create(self, **_values: Any) -> BugCreatePreflight:
            self.preflight_calls += 1
            return preflight

        @staticmethod
        def request_hash(payload: dict[str, Any]) -> str:
            return json_hash(payload)

        def create_bug(self, *, payload: dict[str, Any], **_values: Any) -> dict[str, Any]:
            self.create_calls += 1
            self.payload = payload
            if self.failures:
                raise self.failures.pop(0)
            task = payload["tasks"][0]
            return {"uuid": task["uuid"], "number": 900001, "status": "created"}

        def read_created_bug(self, **values: Any) -> dict[str, Any] | None:
            self.readback_tokens.append(str(values["token"]))
            payload = self.payload or compiled.provider_payload
            return {**payload["tasks"][0], "number": 900001}

    provider = _CreateProvider()
    runtime = SimpleNamespace(
        database=database,
        audit_service=_Audit(),
    )

    class _Adapter(OnesExternalActionAdapter):
        def _reauthorize(self, _intent: dict[str, Any]) -> tuple[dict[str, Any], Any]:
            return (
                {"external_subject_id": "user-current", "revision": 7},
                SimpleNamespace(secrets=SimpleNamespace(token="provider-token")),
            )

        def _refresh_credential(
            self,
            _intent: dict[str, Any],
            _identity: dict[str, Any],
            _credential: Any,
        ) -> Any:
            return SimpleNamespace(
                secrets=SimpleNamespace(token="refreshed-provider-token")
            )

    adapter = _Adapter(runtime, create_provider=provider)  # type: ignore[arg-type]
    outcome = adapter.execute(intent)
    assert outcome.result["verified"] is True
    assert outcome.result["number"] == 900001
    assert provider.create_calls == expected_create_calls
    assert provider.preflight_calls == 1
    assert provider.readback_tokens[-1] == expected_readback_token
    assert outcome.card_fields == {
        "providerName": "ONES",
        "operationName": "创建缺陷",
        "targetName": arguments["title"],
        "detailText": (
            "缺陷编号：#900001\n标题：称量结果显示错误\n"
            "所属项目：示例项目\n负责人：负责人甲"
        ),
    }

    persisted = repository.get(str(intent["id"])) or {}
    repeated = adapter.reconcile_interrupted(persisted)
    assert repeated is not None
    assert repeated.result["verified"] is True
    assert provider.create_calls == expected_create_calls
    assert provider.preflight_calls == 1


def test_worker_create_readback_mismatch_is_uncertain() -> None:
    catalog = BugCreateFieldCatalog.load()
    arguments = _arguments(catalog)
    compiled = compile_bug_create(
        arguments,
        catalog=catalog,
        team_uuid=catalog.source_team_uuid,
        task_uuid="MismatchCreate01",
        current_user_uuid="user-current",
        display_values=_display(catalog),
    )
    provider = SimpleNamespace(
        read_created_bug=lambda **_kwargs: {
            **compiled.provider_payload["tasks"][0],
            "number": 1,
            "summary": "不一致标题",
        }
    )
    adapter = OnesExternalActionAdapter.__new__(OnesExternalActionAdapter)
    adapter._create_provider = provider  # type: ignore[assignment]
    with pytest.raises(RetryableExecutionError) as caught:
        adapter._reconcile_create(
            {"execution_scope_id": catalog.source_team_uuid, "target_resource_id": "MismatchCreate01"},
            {"external_subject_id": "user-current"},
            SimpleNamespace(secrets=SimpleNamespace(token="provider-token")),
            compiled,
            status_text="核验",
        )
    assert caught.value.error_code == "ones_bug_create_readback_mismatch"


def test_provider_statuses_distinguish_rejected_and_uncertain_writes() -> None:
    from services.ones_mcp_server.provider.http_client import OnesProviderHttpClient

    rejected = OnesProviderHttpClient.status_error(400)
    conflict = OnesProviderHttpClient.status_error(409)
    unavailable = OnesProviderHttpClient.status_error(503)
    assert isinstance(rejected, NonRetryableExecutionError)
    assert rejected.error_code == "ones_provider_request_rejected"
    assert isinstance(conflict, RetryableExecutionError)
    assert conflict.error_code == "ones_provider_write_conflict"
    assert isinstance(unavailable, RetryableExecutionError)
    assert unavailable.error_code == "ones_provider_unavailable"


def test_mock_supports_preflight_add3_readback_conflict_and_mismatch() -> None:
    settings = MockOnesSettings()
    app = create_app(settings)
    client = TestClient(app)
    headers = {
        "Ones-Auth-Token": settings.token,
        "Ones-User-Id": settings.user_uuid,
    }
    catalog = BugCreateFieldCatalog.load()
    arguments = _arguments(
        catalog,
        project_uuid=settings.config.project_uuid,
        assignee_uuid=settings.user_uuid,
        watcher_uuids=[],
        product_uuids=["MOCK-PRODUCT-001"],
        product_module_uuids=["MOCK-PRODUCT-MODULE-001"],
    )
    provider_http = _Http([])
    del provider_http  # The HTTP contract itself is covered above; use real ASGI routes here.
    preflight_payload = {
        "project_uuid": arguments["project_uuid"],
        "issue_type_uuid": "B4TV9bu5",
        "user_uuids": [settings.user_uuid],
        "product_uuids": arguments["product_uuids"],
        "product_module_uuids": arguments["product_module_uuids"],
        "affected_version_uuids": arguments["affected_version_uuids"],
    }
    preflight = client.post(
        f"/project/api/project/team/{settings.team_uuid}/tasks/create_preflight",
        headers=headers,
        json=preflight_payload,
    )
    assert preflight.status_code == 200
    displays = {
        "project_uuid": {
            str(preflight.json()["project"]["uuid"]): str(preflight.json()["project"]["name"])
        },
        "user_uuids": {
            str(item["uuid"]): str(item["name"]) for item in preflight.json()["users"]
        },
        "product_uuids": {
            str(item["uuid"]): str(item["name"]) for item in preflight.json()["products"]
        },
        "product_module_uuids": {
            str(item["uuid"]): str(item["name"])
            for item in preflight.json()["product_modules"]
        },
        "affected_version_uuids": {
            str(item["uuid"]): str(item["name"])
            for item in preflight.json()["affected_versions"]
        },
    }
    compiled = compile_bug_create(
        arguments,
        catalog=catalog,
        team_uuid=catalog.source_team_uuid,
        task_uuid="MockCreateTask01",
        current_user_uuid=settings.user_uuid,
        display_values=displays,
    )
    created = client.post(
        f"/project/api/project/team/{settings.team_uuid}/tasks/add3",
        headers=headers,
        json=compiled.provider_payload,
    )
    assert created.status_code == 200
    readback = client.get(
        f"/project/api/project/team/{settings.team_uuid}/tasks/MockCreateTask01/create_readback",
        headers=headers,
    )
    assert readback.status_code == 200
    assert compiled_bug_matches_readback(compiled, readback.json()["task"])
    conflict = client.post(
        f"/project/api/project/team/{settings.team_uuid}/tasks/add3",
        headers=headers,
        json=compiled.provider_payload,
    )
    assert conflict.status_code == 409
    app.state.ones_mock_bug_create_mode = "mismatch"
    mismatched = compile_bug_create(
        arguments,
        catalog=catalog,
        team_uuid=catalog.source_team_uuid,
        task_uuid="MockCreateTask02",
        current_user_uuid=settings.user_uuid,
        display_values=displays,
    )
    assert client.post(
        f"/project/api/project/team/{settings.team_uuid}/tasks/add3",
        headers=headers,
        json=mismatched.provider_payload,
    ).status_code == 200
    mismatch_readback = client.get(
        f"/project/api/project/team/{settings.team_uuid}/tasks/MockCreateTask02/create_readback",
        headers=headers,
    ).json()["task"]
    assert not compiled_bug_matches_readback(mismatched, mismatch_readback)

    for mode, status_code in (("timeout", 503), ("disconnect", 503)):
        app.state.ones_mock_bug_create_mode = mode
        ambiguous = compile_bug_create(
            arguments,
            catalog=catalog,
            team_uuid=catalog.source_team_uuid,
            task_uuid=f"MockCreate{mode.title()}",
            current_user_uuid=settings.user_uuid,
            display_values=displays,
        )
        assert client.post(
            f"/project/api/project/team/{settings.team_uuid}/tasks/add3",
            headers=headers,
            json=ambiguous.provider_payload,
        ).status_code == status_code
        assert client.get(
            f"/project/api/project/team/{settings.team_uuid}/tasks/"
            f"MockCreate{mode.title()}/create_readback",
            headers=headers,
        ).json() == {"found": False}

    app.state.ones_mock_bug_create_mode = "not_ready"
    not_ready = client.post(
        f"/project/api/project/team/{settings.team_uuid}/tasks/create_preflight",
        headers=headers,
        json=preflight_payload,
    )
    assert not_ready.json() == {"ready": False, "can_create": False}
