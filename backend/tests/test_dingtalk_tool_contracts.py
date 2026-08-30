from __future__ import annotations

from jsonschema import Draft202012Validator

from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.modules.mcp_tool_runtime.job_snapshot import JobMcpToolSnapshotService
from app.shared.dingtalk_tool_contracts import (
    DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER,
    DINGTALK_CONFIRMATION_POLICY,
    DINGTALK_EXCLUDED_TOOL_IDENTIFIERS,
    DINGTALK_TOOL_CONTRACTS,
)
from app.shared.database import Database
from app.shared.tool_contract import tool_schema_hash


EXPECTED_DINGTALK_TOOLS = {
    "dingtalk_search_users": (
        "read",
        "dingtalk.contact.user.search",
        "enterprise_directory_visible_scope",
    ),
    "dingtalk_get_user": (
        "read",
        "dingtalk.contact.user.get",
        "enterprise_directory_visible_scope",
    ),
    "dingtalk_list_department_users": (
        "read",
        "dingtalk.contact.department_users.list",
        "enterprise_directory_visible_scope",
    ),
    "dingtalk_search_departments": (
        "read",
        "dingtalk.department.search",
        "enterprise_directory_visible_scope",
    ),
    "dingtalk_get_department": (
        "read",
        "dingtalk.department.get",
        "enterprise_directory_visible_scope",
    ),
    "dingtalk_list_sub_departments": (
        "read",
        "dingtalk.department.children.list",
        "enterprise_directory_visible_scope",
    ),
    "dingtalk_list_todos": ("read", "dingtalk.todo.list", "current_user_todo"),
    "dingtalk_create_todo": ("mutation", "dingtalk.todo.create", "current_user_todo"),
    "dingtalk_update_todo": ("mutation", "dingtalk.todo.update", "current_user_todo"),
    "dingtalk_complete_todo": ("mutation", "dingtalk.todo.complete", "current_user_todo"),
    "dingtalk_get_calendar_event": (
        "read",
        "dingtalk.calendar.event.get",
        "current_user_primary_calendar",
    ),
    "dingtalk_list_calendar_events": (
        "read",
        "dingtalk.calendar.event.list",
        "current_user_primary_calendar",
    ),
    "dingtalk_list_calendar_attendees": (
        "read",
        "dingtalk.calendar.attendee.list",
        "current_user_primary_calendar",
    ),
    "dingtalk_create_calendar_event": (
        "mutation",
        "dingtalk.calendar.event.create",
        "current_user_primary_calendar",
    ),
    "dingtalk_update_calendar_event": (
        "mutation",
        "dingtalk.calendar.event.update",
        "current_user_primary_calendar",
    ),
    "dingtalk_search_aitables": (
        "read",
        "dingtalk.aitable.search",
        "current_user_aitable_operator",
    ),
    "dingtalk_list_aitable_sheets": (
        "read",
        "dingtalk.aitable.sheet.list",
        "current_user_aitable_operator",
    ),
    "dingtalk_get_aitable_sheet": (
        "read",
        "dingtalk.aitable.sheet.get",
        "current_user_aitable_operator",
    ),
    "dingtalk_list_aitable_fields": (
        "read",
        "dingtalk.aitable.field.list",
        "current_user_aitable_operator",
    ),
    "dingtalk_list_aitable_records": (
        "read",
        "dingtalk.aitable.record.list",
        "current_user_aitable_operator",
    ),
    "dingtalk_get_aitable_record": (
        "read",
        "dingtalk.aitable.record.get",
        "current_user_aitable_operator",
    ),
    "dingtalk_insert_aitable_records": (
        "mutation",
        "dingtalk.aitable.record.insert",
        "current_user_aitable_operator",
    ),
    "dingtalk_update_aitable_records": (
        "mutation",
        "dingtalk.aitable.record.update",
        "current_user_aitable_operator",
    ),
    "dingtalk_send_robot_message": (
        "mutation",
        "dingtalk.robot.message.send",
        "current_source_conversation",
    ),
    DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER: (
        "mutation",
        "dingtalk.robot.batch_send_message_to_users",
        "explicit_enterprise_user_ids",
    ),
    "dingtalk_send_work_notification": (
        "mutation",
        "dingtalk.work_notification.send",
        "current_user_work_notification",
    ),
    "dingtalk_get_work_notification_progress": (
        "read",
        "dingtalk.work_notification.progress.get",
        "current_user_work_notification_history",
    ),
    "dingtalk_get_work_notification_result": (
        "read",
        "dingtalk.work_notification.result.get",
        "current_user_work_notification_history",
    ),
}


def test_governed_catalog_is_exact_and_execution_metadata_is_fixed() -> None:
    assert len(EXPECTED_DINGTALK_TOOLS) == 28
    assert set(DINGTALK_TOOL_CONTRACTS) == set(EXPECTED_DINGTALK_TOOLS)

    for identifier, (effect, operation_code, target_policy) in EXPECTED_DINGTALK_TOOLS.items():
        contract = DINGTALK_TOOL_CONTRACTS[identifier]
        definition = MCP_TOOL_MANIFEST[identifier]
        expected_policy = "none" if effect == "read" else DINGTALK_CONFIRMATION_POLICY
        expected_risk = "low" if effect == "read" else "medium"

        assert contract.identifier == identifier
        assert contract.effect == effect
        assert contract.confirmation_policy == expected_policy
        assert contract.operation_code == operation_code
        assert contract.risk_level == expected_risk
        assert contract.target_policy == target_policy
        assert contract.required_scope == f"mcp:dingtalk-mcp:{identifier}:invoke"
        assert contract.read_only is (effect == "read")
        assert contract.destructive is (effect == "mutation")
        assert contract.idempotent is True
        assert contract.open_world is (effect == "read")

        assert definition.server_code == "dingtalk-mcp"
        assert definition.effect == contract.effect
        assert definition.confirmation_policy == contract.confirmation_policy
        assert definition.operation_code == contract.operation_code
        assert definition.risk_level == contract.risk_level
        assert definition.target_policy == contract.target_policy
        assert definition.required_scope == contract.required_scope
        assert definition.read_only == contract.read_only
        assert definition.destructive == contract.destructive
        assert definition.idempotent == contract.idempotent
        assert definition.open_world == contract.open_world
        assert definition.schema_hash == tool_schema_hash(contract.input_schema)


def test_phase_2_contract_schemas_are_closed_and_valid() -> None:
    for contract in DINGTALK_TOOL_CONTRACTS.values():
        Draft202012Validator.check_schema(contract.input_schema)
        Draft202012Validator.check_schema(contract.output_schema)
        assert contract.input_schema["type"] == "object"
        assert contract.input_schema["additionalProperties"] is False
        assert contract.output_schema["type"] == "object"
        assert contract.output_schema["additionalProperties"] is False


def test_create_todo_input_schema_hash_remains_mvp_compatible() -> None:
    assert (
        MCP_TOOL_MANIFEST["dingtalk_create_todo"].schema_hash
        == "8de526e0593a7a4520bd4e35b2c71699b3b2ff5d7e5f59c237bdf0328eb9ee38"
    )


def test_existing_robot_and_work_notification_schema_hashes_remain_compatible() -> None:
    expected = "402f0f259941318877432487b3d6501339ec80958772acf532211406c6c82aca"
    current_source = MCP_TOOL_MANIFEST["dingtalk_send_robot_message"]
    assert current_source.schema_hash == expected
    assert "仅准备向当前钉钉来源群或当前私聊发起人" in current_source.description
    assert "不支持按姓名或任意 user_id 定向发送" in current_source.description
    assert "dingtalk_batch_send_message_to_users_by_robot" in current_source.description
    assert MCP_TOOL_MANIFEST["dingtalk_send_work_notification"].schema_hash == expected


def test_official_robot_user_batch_contract_is_closed_without_invented_count_limit() -> None:
    definition = MCP_TOOL_MANIFEST[DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER]
    schema = definition.input_schema

    assert schema["required"] == ["user_ids", "msg_param"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["user_ids"]["minItems"] == 1
    assert "maxItems" not in schema["properties"]["user_ids"]
    assert schema["properties"]["msg_param"]["additionalProperties"] is False
    assert definition.operation_code == "dingtalk.robot.batch_send_message_to_users"
    assert definition.target_policy == "explicit_enterprise_user_ids"
    assert "dingtalk_search_users" in definition.description
    assert "dingtalk_get_user" in definition.description
    assert "本 Job" in definition.description
    assert "让用户选择" in definition.description
    assert "不得改用工作通知" in definition.description


def test_explicitly_excluded_tools_never_enter_contract_or_manifest() -> None:
    assert DINGTALK_EXCLUDED_TOOL_IDENTIFIERS
    assert set(DINGTALK_EXCLUDED_TOOL_IDENTIFIERS).isdisjoint(DINGTALK_TOOL_CONTRACTS)
    assert set(DINGTALK_EXCLUDED_TOOL_IDENTIFIERS).isdisjoint(MCP_TOOL_MANIFEST)


def test_new_job_snapshot_metadata_detects_operation_policy_drift() -> None:
    definition = MCP_TOOL_MANIFEST["dingtalk_send_robot_message"]
    frozen = {
        "effect": definition.effect,
        "confirmation_policy": definition.confirmation_policy,
        "operation_code": definition.operation_code,
        "risk_level": definition.risk_level,
        "target_policy": definition.target_policy,
    }
    assert JobMcpToolSnapshotService._execution_metadata_drifted(frozen, definition) is False
    assert (
        JobMcpToolSnapshotService._execution_metadata_drifted(
            {**frozen, "operation_code": "dingtalk.raw.request"},
            definition,
        )
        is True
    )
    # Historical MVP snapshots only froze effect/policy and remain executable
    # while still failing closed if either historical fact drifts.
    assert (
        JobMcpToolSnapshotService._execution_metadata_drifted(
            {
                "effect": definition.effect,
                "confirmation_policy": definition.confirmation_policy,
            },
            definition,
        )
        is False
    )


def test_user_batch_tool_requires_new_application_publication_and_role_grant() -> None:
    database = Database("sqlite:///:memory:")
    database.execute_script(
        """
        create table business_application_publication_mcp_tool (
          application_publication_id text not null,
          agent_publication_id text not null,
          server_code text not null,
          tool_identifier text not null,
          schema_hash text not null
        );
        create table agent_job_mcp_tool_snapshot (
          id text primary key,
          job_id text not null unique,
          application_publication_id text,
          agent_publication_id text not null,
          schema_version integer not null,
          snapshot_json text not null,
          snapshot_hash text not null,
          authorization_hash text not null,
          created_at text not null
        );
        """
    )
    definition = MCP_TOOL_MANIFEST[DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER]
    user_flow_identifiers = (
        "dingtalk_search_users",
        "dingtalk_get_user",
        DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER,
    )
    for identifier in user_flow_identifiers:
        flow_definition = MCP_TOOL_MANIFEST[identifier]
        database.execute(
            """
            insert into business_application_publication_mcp_tool
              (application_publication_id, agent_publication_id, server_code,
               tool_identifier, schema_hash)
            values (?, ?, ?, ?, ?)
            """,
            (
                "application-publication-new",
                "agent-publication-new",
                flow_definition.server_code,
                flow_definition.identifier,
                flow_definition.schema_hash,
            ),
        )
    service = JobMcpToolSnapshotService(database)
    granted = {
        "tool_grants": [
            {
                "tool_identifier": definition.identifier,
                "source_role_codes": ["message-sender"],
            }
        ]
    }

    common = {
        "requester_id": "user-1",
        "application_id": "application-1",
        "application_config_hash": "config-hash",
        "routing_context": {},
        "business_authorization": {},
    }
    old_publication = service.freeze(
        job_id="job-old-publication",
        application_publication_id="application-publication-old",
        agent_publication_id="agent-publication-new",
        runtime_authorization=granted,
        **common,
    )
    ungranted = service.freeze(
        job_id="job-without-grant",
        application_publication_id="application-publication-new",
        agent_publication_id="agent-publication-new",
        runtime_authorization={"tool_grants": []},
        **common,
    )
    current = service.freeze(
        job_id="job-current-publication-and-grant",
        application_publication_id="application-publication-new",
        agent_publication_id="agent-publication-new",
        runtime_authorization=granted,
        **common,
    )
    current_user_flow = service.freeze(
        job_id="job-current-user-flow",
        application_publication_id="application-publication-new",
        agent_publication_id="agent-publication-new",
        runtime_authorization={
            "tool_grants": [
                {
                    "tool_identifier": identifier,
                    "source_role_codes": ["message-sender"],
                }
                for identifier in user_flow_identifiers
            ]
        },
        **common,
    )

    assert old_publication["snapshot"]["tools"] == []
    assert ungranted["snapshot"]["tools"] == []
    assert [
        value["tool_identifier"] for value in current["snapshot"]["tools"]
    ] == [DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER]
    assert {
        value["tool_identifier"] for value in current_user_flow["snapshot"]["tools"]
    } == set(user_flow_identifiers)
