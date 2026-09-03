from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from jsonschema import Draft202012Validator
from pathlib import Path
import pytest
from types import SimpleNamespace

from app.modules.external_action.domain import (
    ExternalActionIntentFacts,
    canonical_json,
    json_hash,
)
from app.modules.external_action.card import render_confirmation_card
from app.modules.external_action.repository import ExternalActionRepository
from app.modules.external_action.service import ExternalActionService, ExternalActionTokenSigner
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator
from app.shared.dingtalk_tool_contracts import DINGTALK_MUTATION_TOOL_IDENTIFIERS
from app.shared.exceptions import (
    NonRetryableExecutionError,
    PermissionDenied,
    RetryableExecutionError,
)
from app.shared.ones_tool_contracts import ONES_TOOL_CONTRACTS
from services.ones_mcp_server.task_update_catalog import TaskUpdateFieldCatalog
from services.ones_mcp_server.task_update import OnesTaskSnapshot, compile_task_update
from services.ones_mcp_server.provider.task_update import OnesTaskUpdateProvider
from services.ones_mcp_server.tools.task_update import OnesTaskUpdateService
from services.external_action_worker.ones_adapter import OnesExternalActionAdapter
from services.ones_mcp_server.errors import OnesMcpError, OnesProviderUnauthorized
from services.ones_mcp_server.auth.principal import OnesPrincipalResolver
from scripts.sync_ones_task_update_field_catalog import build_catalog, render_catalog


TOOL_IDENTIFIER = "ones_update_task"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _Audit:
    def record(self, *_args: object, **_kwargs: object) -> None:
        return None


def _configure_confirmation_connector(database: Database) -> None:
    database.execute(
        """
        insert into integration_connector
          (id, connector_type, name, enabled, metadata, allow_ingress,
           revision, deleted, created_at, updated_at)
        values (?, 'dingtalk_enterprise_stream', ?, 1, ?, 1, 4, 0,
                '2026-09-03T00:00:00Z', '2026-09-03T00:00:00Z')
        """,
        (
            "connector-1",
            "ones-confirmation-connector",
            (
                '{"card_templates":{"external_action_confirmation":'
                '{"contract_version":"external-action-confirmation-v1",'
                '"template_id":"ones-confirmation.schema"}}}'
            ),
        ),
    )


class _TaskHttp:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def post_json(
        self,
        path: str,
        payload: dict[str, object],
        *,
        headers: dict[str, str],
        query: dict[str, str] | None = None,
    ) -> dict[str, object]:
        self.calls.append({"path": path, "payload": payload, "headers": headers, "query": query})
        return self.responses.pop(0)


class _McpAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def begin(self, _context: object, *, business_request: dict[str, object]) -> object:
        self.events.append({"kind": "begin", "request": business_request})
        return SimpleNamespace(mcp_call_id="mcp-call-1", result_meta=lambda: {})

    def append_event(self, _handle: object, **values: object) -> None:
        self.events.append(values)

    def complete(self, _handle: object, **values: object) -> None:
        self.events.append({"kind": "complete", **values})


_EXISTING_ONES_SCHEMA_HASHES = {
    "ones_get_test_case_detail": "81f646d23d550f7adb5243bbbd841f2ae25afd34897546f00d6158d7f1002153",
    "ones_get_users_by_uuids": "e56c66b8b87a71f6c1ef9b6bc7e90c0be32a32b22af0bd411a05dbb960eb0a72",
    "ones_get_work_item_detail": "9e6564274e6ca35e58d30fdaca2e9816e41a9e6cbda1e4432df1081e73c07b7c",
    "ones_list_issue_types": "5e304bab23739ff953b45e2fc386e04df7216aaf9495a5723b8346c9e22f6ed3",
    "ones_list_project_role_members": "3db73cd406df6c67411c65fa6518434282eebeef527467fd200115892a48807d",
    "ones_list_project_sprints": "5e304bab23739ff953b45e2fc386e04df7216aaf9495a5723b8346c9e22f6ed3",
    "ones_list_test_plans": "0407d48eea711e5c73f2d1f35159cc1617033c73be88f292acc3311753c45648",
    "ones_list_testcase_libraries": "0407d48eea711e5c73f2d1f35159cc1617033c73be88f292acc3311753c45648",
    "ones_list_testcase_modules": "3f6cbeb50f9c2efd69b05cd5a31173ec1e92d6ab604478c0c6c34c39370e1e53",
    "ones_list_work_item_messages": "d58ffbb7041cdf58846ace1c2ed944af82ec3d115abb36972cff2db62d898dfb",
    "ones_query_test_cases": "7397eeb0ff2079d53019ed8258eb7210d0028185a0ececc6a51ddd74ccdf97b7",
    "ones_query_work_items": "914d1fe3e2e8e15e60335ad55b432c4ad8d3a97b2a8fb64d85c13a9d085e521a",
    "ones_query_work_items_with_custom_options": "c44d58c07f09b9bca66fc916843b96126995babb7a2bf7aabbd3d592674f78b8",
    "ones_resolve_query_conditions": "2bcfa7c98012e3dccfb9de3c37d88584b3c937e045a6e3214173ed7237f8b8c8",
    "ones_search_projects": "c833ed4154d5d8bc80762b468a0ed4a1c0f331a936028f99c0474c90d2995928",
    "ones_search_team_users": "bbbb4652555ebcfd283172e7dd179766bde847b61206aaa89dd77943501328a6",
    "ones_work_item_search": "ecd528fde74736d6f1dd89d7fcba260d00037d38aa2e9156ddff58d7d1fffe37",
}


def test_ones_update_task_is_a_strict_confirmed_single_defect_patch_contract() -> None:
    contract = ONES_TOOL_CONTRACTS[TOOL_IDENTIFIER]
    definition = MCP_TOOL_MANIFEST[TOOL_IDENTIFIER]

    assert contract.effect == "mutation"
    assert contract.confirmation_policy == "external_action_card_v1"
    assert contract.operation_code == "ones.task.update"
    assert contract.risk_level == "high"
    assert contract.target_policy == "single_existing_defect"
    assert definition.read_only is False
    assert definition.destructive is True
    assert definition.idempotent is True
    assert definition.open_world is False

    schema = contract.input_schema
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate({"uuid": "task-1", "title": "修复后的标题"})
    validator.validate({"uuid": "task-1", "watcher_uuids": []})

    for invalid in (
        {"uuid": "task-1"},
        {"title": "缺少 uuid"},
        {"uuid": "task-1", "title": None},
        {"uuid": "task-1", "status_uuid": "status-1"},
        {"uuid": "task-1", "field_values": []},
        {"uuid": "task-1", "field_uuid": "field038"},
        {"uuid": "task-1", "type": 1},
        {"uuid": "task-1", "headers": {}},
        {"uuid": "task-1", "team_uuid": "team-1"},
    ):
        with pytest.raises(Exception):
            validator.validate(invalid)


def test_existing_ones_reads_and_dingtalk_mutations_keep_their_contracts() -> None:
    assert {
        identifier: MCP_TOOL_MANIFEST[identifier].schema_hash
        for identifier in sorted(ONES_TOOL_CONTRACTS)
        if identifier != TOOL_IDENTIFIER
    } == _EXISTING_ONES_SCHEMA_HASHES
    for identifier in _EXISTING_ONES_SCHEMA_HASHES:
        definition = MCP_TOOL_MANIFEST[identifier]
        assert definition.effect == "read"
        assert definition.confirmation_policy == "none"
        assert definition.read_only is True

    for identifier in DINGTALK_MUTATION_TOOL_IDENTIFIERS:
        definition = MCP_TOOL_MANIFEST[identifier]
        assert definition.server_code == "dingtalk-mcp"
        assert definition.effect == "mutation"
        assert definition.confirmation_policy == "external_action_card_v1"
        assert definition.read_only is False


def test_task_update_catalog_is_bounded_team_scoped_and_excludes_status() -> None:
    catalog = TaskUpdateFieldCatalog.load()

    assert len(catalog.fields) == 29
    assert len(catalog.content_sha256) == 64
    assert catalog.catalog_version
    assert {field.semantic_name for field in catalog.fields} == {
        name
        for name in ONES_TOOL_CONTRACTS[TOOL_IDENTIFIER].input_schema["properties"]
        if name != "uuid"
    }
    assert "status_uuid" not in {field.semantic_name for field in catalog.fields}
    catalog.require_team(catalog.source_team_uuid)
    with pytest.raises(Exception) as caught:
        catalog.require_team("another-team")
    assert getattr(caught.value, "error_code", "") == "ones_task_update_catalog_scope_mismatch"


def test_generated_task_update_catalog_matches_dictionary_and_excludes_dynamic_data() -> None:
    source = (PROJECT_ROOT / "ones_mock/ones/查询条件字典.yaml").read_bytes()
    generated = PROJECT_ROOT / "services/ones_mcp_server/resources/task_update_field_catalog.json"

    assert render_catalog(build_catalog(source)) == generated.read_bytes()
    rendered = generated.read_text()
    assert '"provider_field_uuid": "field041"' in rendered
    assert '"provider_field_uuid": "field012"' in rendered
    assert "4QhXszHZ" not in rendered
    assert "NsNWZEpn" not in rendered
    assert "sprint_in" not in rendered
    assert "status_uuid" not in rendered


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.replace(
            "field038:  # 严重程度 type=1",
            "field038:  # 严重程度 type=99",
            1,
        ),
        lambda value: value.replace(
            "    5iKtZTwj: 非阻塞",
            "    3YsgbD57: 非阻塞",
        ),
    ],
    ids=["unknown-provider-type", "duplicate-option-uuid"],
)
def test_task_update_catalog_generator_rejects_ambiguous_provider_data(
    mutation: Callable[[str], str],
) -> None:
    source = (PROJECT_ROOT / "ones_mock/ones/查询条件字典.yaml").read_text()
    with pytest.raises(ValueError):
        build_catalog(mutation(source).encode("utf-8"))


def _snapshot_for_field(semantic_name: str) -> OnesTaskSnapshot:
    catalog = TaskUpdateFieldCatalog.load()
    return OnesTaskSnapshot(
        uuid="task-1",
        number=42,
        title="旧标题",
        issue_type_name="缺陷",
        project_uuid="project-1",
        team_uuid=catalog.source_team_uuid,
        server_update_stamp="1001",
        can_edit=True,
        can_update_watchers=True,
        available_fields=frozenset({semantic_name}),
        values={
            semantic_name: []
            if catalog.require_field(semantic_name).value_kind in {"users", "entities", "options"}
            else "旧值"
        },
        display_values={semantic_name: "旧值"},
    )


@pytest.mark.parametrize(
    "semantic_name",
    tuple(field.semantic_name for field in TaskUpdateFieldCatalog.load().fields),
)
def test_compile_task_update_maps_every_verified_semantic_field(
    semantic_name: str,
) -> None:
    catalog = TaskUpdateFieldCatalog.load()
    field = catalog.require_field(semantic_name)
    proposed: object
    if field.value_kind == "number":
        proposed = 2
    elif field.value_kind in {"users", "entities"}:
        proposed = ["entity-1"]
    elif field.value_kind == "options":
        proposed = [field.options[0]["uuid"]]
    elif field.value_kind == "option":
        proposed = field.options[0]["uuid"]
    elif field.value_kind in {"user", "sprint"}:
        proposed = "entity-1"
    else:
        proposed = "新标题" if semantic_name == "title" else "新值"
    resolved = (
        {semantic_name: {"entity-1": "实体甲"}}
        if field.value_kind in {"user", "users", "sprint", "entities"}
        else {}
    )

    compiled = compile_task_update(
        {"uuid": "task-1", semantic_name: proposed},
        snapshot=_snapshot_for_field(semantic_name),
        catalog=catalog,
        resolved_entities=resolved,
    )

    assert compiled is not None
    task = compiled.provider_payload["tasks"][0]
    if semantic_name == "title":
        assert task["name"] == task["summary"] == proposed
    elif semantic_name == "description":
        assert task["descriptionText"] == proposed
        assert task["desc_rich"] == "<p>新值</p>"
    elif semantic_name == "assignee_uuid":
        assert task["assign"] == proposed
    else:
        assert task["field_values"] == [
            {
                "field_uuid": field.provider_field_uuid,
                "type": field.provider_type,
                "value": proposed,
            }
        ]
    assert compiled.changes[0]["field"] == field.label


@pytest.mark.parametrize(
    "semantic_name",
    tuple(
        field.semantic_name for field in TaskUpdateFieldCatalog.load().fields if field.allow_clear
    ),
)
def test_compile_task_update_uses_only_catalog_verified_clear_values(
    semantic_name: str,
) -> None:
    catalog = TaskUpdateFieldCatalog.load()
    field = catalog.require_field(semantic_name)
    proposed: object = [] if field.value_kind in {"users", "entities", "options"} else ""
    snapshot = replace(
        _snapshot_for_field(semantic_name),
        values={
            semantic_name: (
                ["old-entity"] if field.value_kind in {"users", "entities", "options"} else "旧值"
            )
        },
    )

    compiled = compile_task_update(
        {"uuid": "task-1", semantic_name: proposed},
        snapshot=snapshot,
        catalog=catalog,
        resolved_entities={},
    )

    assert compiled is not None
    assert compiled.changes[0]["after"] == "清空"
    task = compiled.provider_payload["tasks"][0]
    if semantic_name == "description":
        assert task["descriptionText"] == ""
        assert task["desc_rich"] == "<p></p>"
    else:
        assert task["field_values"][0]["value"] == proposed


def test_compile_task_update_rejects_non_defect_permissions_and_layout_drift() -> None:
    catalog = TaskUpdateFieldCatalog.load()
    base = _snapshot_for_field("title")

    for snapshot, error_code in (
        (replace(base, issue_type_name="需求"), "ones_task_update_non_defect"),
        (replace(base, issue_type_name="非缺陷需求"), "ones_task_update_non_defect"),
        (replace(base, can_edit=False), "ones_task_update_permission_denied"),
        (replace(base, available_fields=frozenset()), "ones_task_update_field_not_applicable"),
    ):
        with pytest.raises(Exception) as caught:
            compile_task_update(
                {"uuid": "task-1", "title": "新标题"},
                snapshot=snapshot,  # type: ignore[arg-type]
                catalog=catalog,
                resolved_entities={},
            )
        assert getattr(caught.value, "error_code", "") == error_code

    assert (
        compile_task_update(
            {"uuid": "task-1", "title": "旧值"},
            snapshot=base,
            catalog=catalog,
            resolved_entities={},
        )
        is None
    )


def test_compile_task_update_emits_fixed_patch_and_complete_display_diff() -> None:
    catalog = TaskUpdateFieldCatalog.load()
    severity = catalog.require_field("severity_uuid").options[0]
    snapshot = OnesTaskSnapshot(
        uuid="task-1",
        number=42,
        title="旧标题",
        issue_type_name="缺陷",
        project_uuid="project-1",
        team_uuid=catalog.source_team_uuid,
        server_update_stamp="1001",
        can_edit=True,
        can_update_watchers=True,
        available_fields=frozenset(field.semantic_name for field in catalog.fields),
        values={
            "title": "旧标题",
            "description": "旧描述",
            "watcher_uuids": ["user-1"],
            "severity_uuid": "",
        },
        display_values={
            "title": "旧标题",
            "description": "旧描述",
            "watcher_uuids": ["甲"],
            "severity_uuid": "（空）",
        },
    )

    compiled = compile_task_update(
        {
            "uuid": "task-1",
            "title": "新标题",
            "description": "<script>不可执行</script>",
            "watcher_uuids": [],
            "severity_uuid": severity["uuid"],
        },
        snapshot=snapshot,
        catalog=catalog,
        resolved_entities={},
    )

    assert compiled is not None
    task = compiled.provider_payload["tasks"][0]
    assert task["name"] == task["summary"] == "新标题"
    assert task["descriptionText"] == "<script>不可执行</script>"
    assert "&lt;script&gt;" in task["desc_rich"]
    assert "<script>" not in task["desc_rich"]
    assert task["field_values"] == [
        {"field_uuid": "field008", "type": 13, "value": []},
        {"field_uuid": "field038", "type": 1, "value": severity["uuid"]},
    ]
    assert compiled.changes == (
        {"field": "标题", "before": "旧标题", "after": "新标题"},
        {
            "field": "描述",
            "before": "旧描述",
            "after": "<script>不可执行</script>",
        },
        {"field": "关注者", "before": "甲", "after": "清空"},
        {"field": "严重程度", "before": "（空）", "after": severity["name"]},
    )


def test_ones_action_intent_idempotency_includes_resource_snapshot() -> None:
    database = Database("sqlite:///:memory:")
    Migrator(database, default_migrations_dir(), migrator_build="ones-intent-test").run()
    database.execute("pragma foreign_keys = off")
    _configure_confirmation_connector(database)
    service = ExternalActionService(
        ExternalActionRepository(database),
        ExternalActionTokenSigner("k" * 32),
        _Audit(),  # type: ignore[arg-type]
    )
    catalog = TaskUpdateFieldCatalog.load()
    arguments = {"uuid": "task-1", "title": "新标题"}
    base = dict(
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
        tool_identifier=TOOL_IDENTIFIER,
        schema_hash=MCP_TOOL_MANIFEST[TOOL_IDENTIFIER].schema_hash,
        confirmation_policy="external_action_card_v1",
        operation_code="ones.task.update",
        confirmation_channel_code="dingtalk",
        execution_provider_code="ones",
        execution_external_identity_id="ones-identity-1",
        execution_scope_id=catalog.source_team_uuid,
        target_resource_type="task",
        target_resource_id="task-1",
        field_catalog_version=catalog.catalog_version,
        field_catalog_hash=catalog.content_sha256,
    )

    first, created = service.prepare(
        facts=ExternalActionIntentFacts(
            **base,
            precondition={"server_update_stamp": "1001"},
        ),
        arguments=arguments,
        arguments_hash=json_hash(arguments),
        safe_summary={"operation": "更新缺陷", "target": "#42 新标题", "changes": []},
        mcp_call_id="call-1",
    )
    replay, replay_created = service.prepare(
        facts=ExternalActionIntentFacts(
            **base,
            precondition={"server_update_stamp": "1001"},
        ),
        arguments=arguments,
        arguments_hash=json_hash(arguments),
        safe_summary={"operation": "更新缺陷", "target": "#42 新标题", "changes": []},
        mcp_call_id="call-2",
    )
    changed, changed_created = service.prepare(
        facts=ExternalActionIntentFacts(
            **base,
            precondition={"server_update_stamp": "1002"},
        ),
        arguments=arguments,
        arguments_hash=json_hash(arguments),
        safe_summary={"operation": "更新缺陷", "target": "#42 新标题", "changes": []},
        mcp_call_id="call-3",
    )
    catalog_changed, catalog_changed_created = service.prepare(
        facts=ExternalActionIntentFacts(
            **{
                **base,
                "field_catalog_version": "2030-01-01-bbbbbbbbbbbbbbbb",
                "field_catalog_hash": "b" * 64,
            },
            precondition={"server_update_stamp": "1001"},
        ),
        arguments=arguments,
        arguments_hash=json_hash(arguments),
        safe_summary={"operation": "更新缺陷", "target": "#42 新标题", "changes": []},
        mcp_call_id="call-4",
    )

    assert created is True
    assert replay_created is False
    assert replay["id"] == first["id"]
    assert changed_created is True
    assert changed["id"] != first["id"]
    assert catalog_changed_created is True
    assert catalog_changed["id"] not in {first["id"], changed["id"]}
    assert database.execute_one("select count(*) as count from external_action_card_outbox") == {
        "count": 3
    }


def test_ones_action_intent_preserves_full_card_summary_beyond_legacy_limit() -> None:
    database = Database("sqlite:///:memory:")
    Migrator(database, default_migrations_dir(), migrator_build="ones-summary-budget-test").run()
    database.execute("pragma foreign_keys = off")
    _configure_confirmation_connector(database)
    repository = ExternalActionRepository(database)
    service = ExternalActionService(
        repository,
        ExternalActionTokenSigner("k" * 32),
        _Audit(),  # type: ignore[arg-type]
    )
    catalog = TaskUpdateFieldCatalog.load()
    changes = [
        {
            "field": f"字段{index}",
            "before": "旧" * 55,
            "after": "新" * 55,
        }
        for index in range(29)
    ]
    summary = {"operation": "更新缺陷", "target": "#42 长摘要", "changes": changes}
    detail = render_confirmation_card(
        {
            "execution_provider_code": "ones",
            "operation_code": "ones.task.update",
            "target_resource_type": "task",
        },
        summary,
    )["detailText"]
    assert len(detail) <= 4000
    assert len(canonical_json(summary)) > 4096
    arguments = {"uuid": "task-1", "title": "新标题"}
    facts = ExternalActionIntentFacts(
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
        tool_identifier=TOOL_IDENTIFIER,
        schema_hash=MCP_TOOL_MANIFEST[TOOL_IDENTIFIER].schema_hash,
        confirmation_policy="external_action_card_v1",
        operation_code="ones.task.update",
        execution_provider_code="ones",
        execution_external_identity_id="ones-identity-1",
        execution_scope_id=catalog.source_team_uuid,
        target_resource_type="task",
        target_resource_id="task-1",
        precondition={"server_update_stamp": "1001"},
        field_catalog_version=catalog.catalog_version,
        field_catalog_hash=catalog.content_sha256,
    )

    intent, created = service.prepare(
        facts=facts,
        arguments=arguments,
        arguments_hash=json_hash(arguments),
        safe_summary=summary,
        mcp_call_id="call-long-summary",
    )

    assert created is True
    assert repository.decode_json(intent["confirmation_summary_json"]) == summary
    assert len(str(intent["safe_summary_json"])) <= 4096


def test_external_action_rejects_secret_material_before_persistence() -> None:
    database = Database("sqlite:///:memory:")
    Migrator(database, default_migrations_dir(), migrator_build="secret-rejection-test").run()
    service = ExternalActionService(
        ExternalActionRepository(database),
        ExternalActionTokenSigner("k" * 32),
        _Audit(),  # type: ignore[arg-type]
    )

    with pytest.raises(Exception) as caught:
        service.prepare(
            facts={},
            arguments={"uuid": "task-1", "access_token": "must-not-persist"},
            arguments_hash="a" * 64,
            safe_summary={"operation": "更新缺陷"},
            mcp_call_id="call-secret",
        )

    assert getattr(caught.value, "error_code", "") == "mcp_audit_auth_material_forbidden"
    assert database.execute_one("select count(*) as count from external_action_intent") == {
        "count": 0
    }


def test_ones_confirmation_card_reuses_template_and_never_truncates_diff() -> None:
    fields = render_confirmation_card(
        {
            "execution_provider_code": "ones",
            "operation_code": "ones.task.update",
            "target_resource_type": "task",
        },
        {
            "operation": "更新缺陷",
            "target": "#42 登录失败",
            "changes": [
                {"field": "标题", "before": "旧标题", "after": "新标题"},
                {"field": "关注者", "before": "甲", "after": "乙、丙"},
            ],
        },
    )

    assert fields == {
        "providerName": "ONES",
        "operationName": "更新缺陷",
        "targetName": "#42 登录失败",
        "detailText": "标题：旧标题 → 新标题\n关注者：甲 → 乙、丙",
    }

    with pytest.raises(Exception) as caught:
        render_confirmation_card(
            {
                "execution_provider_code": "ones",
                "operation_code": "ones.task.update",
                "target_resource_type": "task",
            },
            {
                "operation": "更新缺陷",
                "target": "#42 登录失败",
                "changes": [
                    {"field": "描述", "before": "旧", "after": "新" * 4000},
                ],
            },
        )
    assert getattr(caught.value, "error_code", "") == "external_action_card_detail_too_large"


def test_task_update_provider_uses_only_fixed_detail_and_update3_contracts() -> None:
    catalog = TaskUpdateFieldCatalog.load()
    http = _TaskHttp(
        [
            {
                "data": {
                    "task": {
                        "uuid": "task-1",
                        "number": 42,
                        "name": "登录失败",
                        "serverUpdateStamp": 1001,
                        "project": {"uuid": "project-1"},
                        "issueType": {"uuid": "type-1", "name": "缺陷"},
                        "canEdit": True,
                        "hasEditPermission": True,
                        "canUpdateWatchers": True,
                        "hasUpdateWatchersPermission": True,
                        "descriptionText": "旧描述",
                        "assign": {"uuid": "user-1", "name": "甲"},
                        "watchers": [],
                    }
                }
            },
            {"bad_tasks": []},
        ]
    )
    provider = OnesTaskUpdateProvider(http, catalog=catalog)  # type: ignore[arg-type]

    snapshot = provider.read_task(
        team_uuid=catalog.source_team_uuid,
        task_uuid="task-1",
        provider_user_id="user-1",
        token="provider-token",
    )
    result = provider.update_task(
        team_uuid=catalog.source_team_uuid,
        provider_user_id="user-1",
        token="provider-token",
        payload={"tasks": [{"uuid": "task-1", "name": "新标题", "summary": "新标题"}]},
    )

    assert snapshot.uuid == "task-1"
    assert snapshot.server_update_stamp == "1001"
    assert snapshot.can_edit is True
    assert result == {"updated": True, "bad_tasks": []}
    assert http.calls[0]["path"] == (
        f"/project/api/project/team/{catalog.source_team_uuid}/items/graphql"
    )
    assert http.calls[0]["query"] == {"t": "Task"}
    assert http.calls[1]["path"] == (
        f"/project/api/project/team/{catalog.source_team_uuid}/tasks/update3"
    )
    assert all("provider-token" not in str(call["payload"]) for call in http.calls)


@pytest.mark.parametrize(
    ("response", "error_code"),
    [
        ({"bad_tasks": [{"uuid": "task-1"}]}, "ones_task_update_rejected"),
        ({"success": True}, "ones_task_update_response_invalid"),
    ],
)
def test_task_update_provider_rejects_partial_or_malformed_results(
    response: dict[str, object],
    error_code: str,
) -> None:
    catalog = TaskUpdateFieldCatalog.load()
    provider = OnesTaskUpdateProvider(
        _TaskHttp([response]),  # type: ignore[arg-type]
        catalog=catalog,
    )

    with pytest.raises(Exception) as caught:
        provider.update_task(
            team_uuid=catalog.source_team_uuid,
            provider_user_id="user-1",
            token="provider-token",
            payload={"tasks": [{"uuid": "task-1", "name": "新标题"}]},
        )

    assert getattr(caught.value, "error_code", "") == error_code


def test_ones_update_task_prepares_intent_without_calling_update3() -> None:
    catalog = TaskUpdateFieldCatalog.load()
    snapshot = OnesTaskSnapshot(
        uuid="task-1",
        number=42,
        title="旧标题",
        issue_type_name="缺陷",
        project_uuid="project-1",
        team_uuid=catalog.source_team_uuid,
        server_update_stamp="1001",
        can_edit=True,
        can_update_watchers=True,
        available_fields=frozenset({"title"}),
        values={"title": "旧标题"},
        display_values={"title": "旧标题"},
    )

    class _Provider:
        def __init__(self) -> None:
            self.update_calls = 0

        def read_task(self, **_kwargs: object) -> OnesTaskSnapshot:
            return snapshot

        def resolve_entities(self, **_kwargs: object) -> dict[str, dict[str, str]]:
            return {}

        def update_task(self, **_kwargs: object) -> dict[str, object]:
            self.update_calls += 1
            return {"updated": True}

    class _Resolver:
        def authenticate(self, _token: str, *, required_scope: str) -> dict[str, str]:
            assert required_scope.endswith(":ones_update_task:invoke")
            return {"job_id": "job-1"}

        def audit_context(self, *_args: object, **_kwargs: object) -> object:
            return object()

        def resolve(self, *_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(
                job_id="job-1",
                session_id="session-1",
                actor_user_id="user-1",
                business_application_id="application-1",
                agent_publication_id="agent-publication-1",
                application_publication_id="application-publication-1",
                external_identity_id="ones-identity-1",
                provider_user_id="ones-user-1",
                provider_email="ignored@example.test",
                team_id=catalog.source_team_uuid,
                credential=SimpleNamespace(
                    id="credential-1",
                    revision=1,
                    secrets=SimpleNamespace(token="provider-token"),
                ),
            )

        def resolve_confirmation_route(self, _principal: object) -> object:
            return SimpleNamespace(
                source_connector_id="connector-1",
                dingtalk_enterprise_id="enterprise-1",
                target_external_subject_id="staff-1",
                target_union_id="union-1",
                conversation_type="group",
            )

    class _ExternalActions:
        def __init__(self) -> None:
            self.prepared: list[dict[str, object]] = []

        def prepare(self, **values: object) -> tuple[dict[str, object], bool]:
            self.prepared.append(values)
            return (
                {
                    "id": "action-1",
                    "revision": 1,
                    "expires_at": "2030-01-01T00:00:00+00:00",
                },
                True,
            )

    provider = _Provider()
    external_actions = _ExternalActions()
    service = OnesTaskUpdateService(
        resolver=_Resolver(),  # type: ignore[arg-type]
        provider=provider,  # type: ignore[arg-type]
        catalog=catalog,
        external_actions=external_actions,  # type: ignore[arg-type]
        audit=_McpAudit(),  # type: ignore[arg-type]
        credentials=SimpleNamespace(mark_used=lambda **_kwargs: None),  # type: ignore[arg-type]
        credential_refresh=SimpleNamespace(),  # type: ignore[arg-type]
    )

    output = service.invoke(
        claims={"job_id": "job-1"},
        arguments={"uuid": "task-1", "title": "新标题"},
        correlation_id="correlation-1",
        invocation_id="job-1.attempt-0",
    )

    assert output["status"] == "confirmation_required"
    assert output["action_intent_id"] == "action-1"
    assert provider.update_calls == 0
    facts = external_actions.prepared[0]["facts"]
    assert isinstance(facts, ExternalActionIntentFacts)
    assert facts.execution_provider_code == "ones"
    assert facts.confirmation_channel_code == "dingtalk"
    assert facts.target_resource_id == "task-1"


class _PreparationProvider:
    def __init__(self, snapshot: OnesTaskSnapshot) -> None:
        self.snapshot = snapshot
        self.read_calls = 0
        self.update_calls = 0

    def read_task(self, **_values: object) -> OnesTaskSnapshot:
        self.read_calls += 1
        return self.snapshot

    @staticmethod
    def resolve_entities(**_values: object) -> dict[str, dict[str, str]]:
        return {}

    def update_task(self, **_values: object) -> dict[str, object]:
        self.update_calls += 1
        return {"updated": True}


class _PreparationActions:
    def __init__(self) -> None:
        self.prepared: list[dict[str, object]] = []

    def prepare(self, **values: object) -> tuple[dict[str, object], bool]:
        self.prepared.append(values)
        return (
            {
                "id": "action-1",
                "revision": 1,
                "expires_at": "2030-01-01T00:00:00+00:00",
            },
            True,
        )


class _PreparationResolver:
    def __init__(self, catalog: TaskUpdateFieldCatalog, *, route_error: bool = False) -> None:
        self.catalog = catalog
        self.route_error = route_error

    @staticmethod
    def authenticate(_token: str, *, required_scope: str) -> dict[str, str]:
        assert required_scope.endswith(":ones_update_task:invoke")
        return {"job_id": "job-1"}

    @staticmethod
    def audit_context(*_args: object, **_kwargs: object) -> object:
        return object()

    def resolve(self, *_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(
            job_id="job-1",
            session_id="session-1",
            actor_user_id="user-1",
            business_application_id="application-1",
            agent_publication_id="agent-publication-1",
            application_publication_id="application-publication-1",
            external_identity_id="ones-identity-1",
            provider_user_id="ones-user-1",
            provider_email="ignored@example.test",
            team_id=self.catalog.source_team_uuid,
            credential=SimpleNamespace(
                id="credential-1",
                revision=1,
                secrets=SimpleNamespace(token="provider-token"),
            ),
        )

    def resolve_confirmation_route(self, _principal: object) -> object:
        if self.route_error:
            raise OnesMcpError(
                "web jobs cannot create confirmation routes",
                safe_message="ONES 缺陷更新仅支持从钉钉会话发起",
                error_code="ones_mutation_dingtalk_source_required",
            )
        return SimpleNamespace(
            source_connector_id="connector-1",
            dingtalk_enterprise_id="enterprise-1",
            target_external_subject_id="staff-1",
            target_union_id="union-1",
            conversation_type="direct",
        )


def _preparation_service(
    catalog: TaskUpdateFieldCatalog,
    provider: _PreparationProvider,
    actions: _PreparationActions,
    *,
    route_error: bool = False,
) -> OnesTaskUpdateService:
    return OnesTaskUpdateService(
        resolver=_PreparationResolver(catalog, route_error=route_error),  # type: ignore[arg-type]
        provider=provider,  # type: ignore[arg-type]
        catalog=catalog,
        external_actions=actions,  # type: ignore[arg-type]
        audit=_McpAudit(),  # type: ignore[arg-type]
        credentials=SimpleNamespace(mark_used=lambda **_kwargs: None),  # type: ignore[arg-type]
        credential_refresh=SimpleNamespace(),  # type: ignore[arg-type]
    )


def test_ones_update_task_rejects_web_route_before_provider_or_intent() -> None:
    catalog = TaskUpdateFieldCatalog.load()
    provider = _PreparationProvider(_snapshot_for_field("title"))
    actions = _PreparationActions()
    service = _preparation_service(catalog, provider, actions, route_error=True)

    with pytest.raises(OnesMcpError) as caught:
        service.invoke(
            claims={"job_id": "job-1"},
            arguments={"uuid": "task-1", "title": "新标题"},
            correlation_id="correlation-1",
            invocation_id="job-1.attempt-0",
        )

    assert caught.value.error_code == "ones_mutation_dingtalk_source_required"
    assert provider.read_calls == 0
    assert actions.prepared == []


@pytest.mark.parametrize("conversation_type", ["direct", "group"])
def test_confirmation_route_is_always_the_originating_dingtalk_operator(
    conversation_type: str,
) -> None:
    class _RouteDatabase:
        @staticmethod
        def execute_one(_query: str, _params: object) -> dict[str, object]:
            return {
                "source_connector_id": "connector-1",
                "source_channel": "dingtalk",
                "session_source_connector_id": "connector-1",
                "conversation_type": conversation_type,
                "external_conversation_id": "conversation-1",
                "connector_type": "dingtalk_enterprise_stream",
                "enabled": 1,
                "allow_ingress": 1,
                "dingtalk_enterprise_id": "enterprise-1",
                "enterprise_status": "ACTIVE",
            }

        @staticmethod
        def execute(_query: str, _params: object) -> list[dict[str, object]]:
            return [{"external_subject_id": "staff-1", "union_id": "union-1"}]

    resolver = OnesPrincipalResolver(
        _RouteDatabase(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
    )

    route = resolver.resolve_confirmation_route(
        SimpleNamespace(job_id="job-1", session_id="session-1", actor_user_id="user-1")
    )

    assert route.conversation_type == conversation_type
    assert route.target_external_subject_id == "staff-1"
    assert route.target_union_id == "union-1"


def test_ones_update_task_short_circuits_no_change_without_intent() -> None:
    catalog = TaskUpdateFieldCatalog.load()
    provider = _PreparationProvider(_snapshot_for_field("title"))
    actions = _PreparationActions()
    service = _preparation_service(catalog, provider, actions)

    output = service.invoke(
        claims={"job_id": "job-1"},
        arguments={"uuid": "task-1", "title": "旧值"},
        correlation_id="correlation-1",
        invocation_id="job-1.attempt-0",
    )

    assert output == {"status": "no_update"}
    assert actions.prepared == []
    assert provider.update_calls == 0


def test_ones_update_task_rejects_oversized_card_before_intent() -> None:
    catalog = TaskUpdateFieldCatalog.load()
    snapshot = OnesTaskSnapshot(
        uuid="task-1",
        number=42,
        title="旧标题",
        issue_type_name="缺陷",
        project_uuid="project-1",
        team_uuid=catalog.source_team_uuid,
        server_update_stamp="1001",
        can_edit=True,
        can_update_watchers=True,
        available_fields=frozenset({"description"}),
        values={"description": "旧值"},
        display_values={"description": "旧值"},
    )
    provider = _PreparationProvider(snapshot)
    actions = _PreparationActions()
    service = _preparation_service(catalog, provider, actions)

    with pytest.raises(NonRetryableExecutionError) as caught:
        service.invoke(
            claims={"job_id": "job-1"},
            arguments={"uuid": "task-1", "description": "新" * 4000},
            correlation_id="correlation-1",
            invocation_id="job-1.attempt-0",
        )

    assert caught.value.error_code == "external_action_card_detail_too_large"
    assert actions.prepared == []
    assert provider.update_calls == 0


def _execution_intent(
    catalog: TaskUpdateFieldCatalog,
    *,
    request: dict[str, object],
    provider_payload: dict[str, object],
    server_update_stamp: str = "1001",
) -> dict[str, object]:
    precondition = {
        "server_update_stamp": server_update_stamp,
        "issue_type_name": "缺陷",
        "project_uuid": "project-1",
        "confirmed_values": request,
    }
    facts = ExternalActionIntentFacts(
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
        tool_identifier=TOOL_IDENTIFIER,
        schema_hash=MCP_TOOL_MANIFEST[TOOL_IDENTIFIER].schema_hash,
        confirmation_policy="external_action_card_v1",
        operation_code="ones.task.update",
        execution_provider_code="ones",
        execution_external_identity_id="ones-identity-1",
        execution_scope_id=catalog.source_team_uuid,
        target_resource_type="task",
        target_resource_id="task-1",
        precondition=precondition,
        field_catalog_version=catalog.catalog_version,
        field_catalog_hash=catalog.content_sha256,
    )
    repository_facts = facts.as_repository_facts(arguments_hash=json_hash(request))
    return {
        "id": "action-1",
        **repository_facts,
        "arguments_json": canonical_json(
            {
                "request": request,
                "provider_payload": provider_payload,
                "changes": [],
            }
        ),
        "precondition_json": canonical_json(precondition),
    }


class _ExecutionProvider:
    def __init__(
        self,
        snapshots: list[object],
        *,
        update_failure: Exception | None = None,
    ) -> None:
        self.snapshots = list(snapshots)
        self.update_failure = update_failure
        self.update_calls: list[dict[str, object]] = []
        self.read_tokens: list[str] = []

    def read_task(self, **values: object) -> object:
        self.read_tokens.append(str(values["token"]))
        result = self.snapshots.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    @staticmethod
    def resolve_entities(**_values: object) -> dict[str, dict[str, str]]:
        return {}

    def update_task(self, **values: object) -> dict[str, object]:
        self.update_calls.append(values)
        if self.update_failure is not None:
            raise self.update_failure
        return {"updated": True}


def _adapter_for_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider: _ExecutionProvider,
    *,
    runtime: object | None = None,
    credential: object | None = None,
    login_verifier: object | None = None,
) -> OnesExternalActionAdapter:
    effective_runtime = runtime or SimpleNamespace()
    effective_credential = credential or SimpleNamespace(
        id="credential-1",
        revision=1,
        secrets=SimpleNamespace(
            token="provider-token",
            email="ignored@example.test",
            password="ignored-password",
        ),
    )
    adapter = OnesExternalActionAdapter(
        effective_runtime,
        login_verifier=login_verifier,  # type: ignore[arg-type]
    )
    adapter._provider = provider  # type: ignore[assignment]
    monkeypatch.setattr(
        adapter,
        "_reauthorize",
        lambda _intent: ({"external_subject_id": "ones-user-1"}, effective_credential),
    )
    return adapter


class _ReauthorizationDatabase:
    def __init__(self, catalog: TaskUpdateFieldCatalog) -> None:
        self.catalog = catalog
        self.ones_identity_enabled = True
        self.team_uuids = [catalog.source_team_uuid]

    def execute_one(self, query: str, _params: object) -> dict[str, object] | None:
        if "from agent_job" in query:
            return {
                "session_id": "session-1",
                "internal_user_id": "user-1",
                "business_application_id": "application-1",
                "agent_publication_id": "agent-publication-1",
                "business_application_publication_id": "application-publication-1",
                "source_connector_id": "connector-1",
                "user_status": "enabled",
                "user_account_type": "human",
            }
        if "provider = 'dingtalk'" in query:
            return {"id": "dingtalk-identity-1", "union_id": "union-1"}
        if "provider = 'ones'" in query:
            if not self.ones_identity_enabled:
                return None
            return {
                "id": "ones-identity-1",
                "external_subject_id": "ones-user-1",
                "metadata_json": canonical_json(
                    {
                        "team_uuids": self.team_uuids,
                        "default_team_id": "a-new-default-team",
                    }
                ),
            }
        raise AssertionError(f"unexpected query: {query}")


def test_ones_worker_reauthorizes_exact_identity_and_frozen_team() -> None:
    catalog = TaskUpdateFieldCatalog.load()
    database = _ReauthorizationDatabase(catalog)
    credential = SimpleNamespace(provider="ones")
    credentials = SimpleNamespace(
        get_by_identity=lambda _identity_id: {"id": "credential-1", "status": "ACTIVE"},
        resolve_active=lambda _credential_id: credential,
    )
    runtime = SimpleNamespace(
        database=database,
        mcp_tool_snapshot_service=SimpleNamespace(
            verify=lambda _job_id: {
                "snapshot": {
                    "tools": [
                        {
                            "server_code": "ones-mcp",
                            "tool_identifier": TOOL_IDENTIFIER,
                            "schema_hash": MCP_TOOL_MANIFEST[TOOL_IDENTIFIER].schema_hash,
                        }
                    ]
                }
            }
        ),
        business_authorization_service=SimpleNamespace(require=lambda **_values: {}),
        external_identity_credential_repository=credentials,
    )
    adapter = OnesExternalActionAdapter(runtime)
    request = {"uuid": "task-1", "title": "新标题"}
    intent = _execution_intent(
        catalog,
        request=request,
        provider_payload={"tasks": [{"uuid": "task-1"}]},
    )

    identity, resolved = adapter._reauthorize(intent)
    assert identity["id"] == "ones-identity-1"
    assert resolved is credential

    database.team_uuids = ["a-new-default-team"]
    with pytest.raises(NonRetryableExecutionError) as team_error:
        adapter._reauthorize(intent)
    assert team_error.value.error_code == "ones_task_update_team_revoked"

    database.team_uuids = [catalog.source_team_uuid]
    database.ones_identity_enabled = False
    with pytest.raises(NonRetryableExecutionError) as identity_error:
        adapter._reauthorize(intent)
    assert identity_error.value.error_code == "ones_task_update_identity_revoked"

    database.ones_identity_enabled = True

    def deny_authorization(**_values: object) -> None:
        raise PermissionDenied(
            "business authorization revoked",
            safe_message="当前用户已无权执行该 ONES 更新",
            error_code="business_authorization_denied",
        )

    runtime.business_authorization_service = SimpleNamespace(require=deny_authorization)
    with pytest.raises(PermissionDenied) as authorization_error:
        adapter._reauthorize(intent)
    assert authorization_error.value.error_code == "business_authorization_denied"


def test_ones_worker_catalog_drift_requires_a_new_confirmation() -> None:
    catalog = TaskUpdateFieldCatalog.load()
    adapter = OnesExternalActionAdapter(SimpleNamespace())
    request = {"uuid": "task-1", "title": "新标题"}
    intent = _execution_intent(
        catalog,
        request=request,
        provider_payload={"tasks": [{"uuid": "task-1"}]},
    )
    intent["field_catalog_hash"] = "f" * 64

    with pytest.raises(NonRetryableExecutionError) as caught:
        adapter._reauthorize(intent)

    assert caught.value.error_code == "ones_task_update_catalog_drift"
    assert caught.value.safe_message == "缺陷更新字段目录已变化，请重新发起并确认"


def test_ones_worker_rejects_any_snapshot_change_before_update3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = TaskUpdateFieldCatalog.load()
    old = _snapshot_for_field("title")
    request = {"uuid": "task-1", "title": "新标题"}
    compiled = compile_task_update(
        request,
        snapshot=old,
        catalog=catalog,
        resolved_entities={},
    )
    assert compiled is not None
    changed = replace(old, server_update_stamp="1002")
    provider = _ExecutionProvider([changed])
    adapter = _adapter_for_provider(monkeypatch, provider)

    with pytest.raises(NonRetryableExecutionError) as caught:
        adapter.execute(
            _execution_intent(
                catalog,
                request=request,
                provider_payload=compiled.provider_payload,
            )
        )

    assert caught.value.error_code == "ones_task_update_precondition_changed"
    assert provider.update_calls == []


def test_ones_worker_writes_once_and_verifies_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = TaskUpdateFieldCatalog.load()
    old = _snapshot_for_field("title")
    request = {"uuid": "task-1", "title": "新标题"}
    compiled = compile_task_update(
        request,
        snapshot=old,
        catalog=catalog,
        resolved_entities={},
    )
    assert compiled is not None
    updated = replace(
        old,
        server_update_stamp="1002",
        values={"title": "新标题"},
        display_values={"title": "新标题"},
    )
    provider = _ExecutionProvider([old, updated])
    adapter = _adapter_for_provider(monkeypatch, provider)

    outcome = adapter.execute(
        _execution_intent(
            catalog,
            request=request,
            provider_payload=compiled.provider_payload,
        )
    )

    assert outcome.result == {"updated": True, "verified": True}
    assert len(provider.update_calls) == 1
    assert provider.update_calls[0]["payload"] == compiled.provider_payload


def test_ones_worker_reconciles_unknown_result_without_replaying_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = TaskUpdateFieldCatalog.load()
    old = _snapshot_for_field("title")
    request = {"uuid": "task-1", "title": "新标题"}
    compiled = compile_task_update(
        request,
        snapshot=old,
        catalog=catalog,
        resolved_entities={},
    )
    assert compiled is not None
    updated = replace(old, values={"title": "新标题"}, display_values={"title": "新标题"})
    provider = _ExecutionProvider(
        [old, updated],
        update_failure=RetryableExecutionError(
            "connection lost",
            safe_message="ONES 更新结果未知",
            error_code="ones_task_update_result_unknown",
        ),
    )
    adapter = _adapter_for_provider(monkeypatch, provider)

    outcome = adapter.execute(
        _execution_intent(
            catalog,
            request=request,
            provider_payload=compiled.provider_payload,
        )
    )

    assert outcome.result["reconciled"] is True
    assert len(provider.update_calls) == 1


def test_ones_worker_reconciles_interrupted_lease_with_read_only_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = TaskUpdateFieldCatalog.load()
    old = _snapshot_for_field("title")
    updated = replace(old, values={"title": "新标题"}, display_values={"title": "新标题"})
    request = {"uuid": "task-1", "title": "新标题"}
    compiled = compile_task_update(
        request,
        snapshot=old,
        catalog=catalog,
        resolved_entities={},
    )
    assert compiled is not None
    provider = _ExecutionProvider([updated])
    adapter = _adapter_for_provider(monkeypatch, provider)

    outcome = adapter.reconcile_interrupted(
        _execution_intent(
            catalog,
            request=request,
            provider_payload=compiled.provider_payload,
        )
    )

    assert outcome is not None and outcome.result["reconciled"] is True
    assert provider.update_calls == []


def test_ones_worker_refreshes_expired_credential_only_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = TaskUpdateFieldCatalog.load()
    old = _snapshot_for_field("title")
    updated = replace(old, values={"title": "新标题"}, display_values={"title": "新标题"})
    request = {"uuid": "task-1", "title": "新标题"}
    compiled = compile_task_update(
        request,
        snapshot=old,
        catalog=catalog,
        resolved_entities={},
    )
    assert compiled is not None
    unauthorized = OnesProviderUnauthorized(
        "expired",
        safe_message="ONES 凭据已过期",
        error_code="ones_provider_unauthorized",
    )
    provider = _ExecutionProvider([unauthorized, old, updated])
    old_credential = SimpleNamespace(
        id="credential-1",
        revision=1,
        secrets=SimpleNamespace(
            token="old-token",
            email="ignored@example.test",
            password="ignored-password",
        ),
    )
    refreshed = SimpleNamespace(
        id="credential-1",
        revision=2,
        secrets=SimpleNamespace(
            token="new-token",
            email="ignored@example.test",
            password="ignored-password",
        ),
    )

    class _Credentials:
        rotated = 0

        def rotate_token(self, **values: object) -> None:
            assert values["expected_revision"] == 1
            self.rotated += 1

        @staticmethod
        def resolve_active(_credential_id: str) -> object:
            return refreshed

        @staticmethod
        def mark_reauth_required(**_values: object) -> None:
            raise AssertionError("successful refresh must not require reauthentication")

    credentials = _Credentials()
    runtime = SimpleNamespace(
        external_identity_credential_repository=credentials,
        audit_service=_Audit(),
    )
    verifier = SimpleNamespace(
        verify=lambda **_values: SimpleNamespace(
            user_uuid="ones-user-1",
            team_uuids=(catalog.source_team_uuid,),
            token="new-token",
        )
    )
    adapter = _adapter_for_provider(
        monkeypatch,
        provider,
        runtime=runtime,
        credential=old_credential,
        login_verifier=verifier,
    )

    outcome = adapter.execute(
        _execution_intent(
            catalog,
            request=request,
            provider_payload=compiled.provider_payload,
        )
    )

    assert outcome.result["verified"] is True
    assert credentials.rotated == 1
    assert provider.read_tokens == ["old-token", "new-token", "new-token"]
