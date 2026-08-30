from __future__ import annotations

from jsonschema import Draft202012Validator

from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.modules.mcp_tool_runtime.job_snapshot import JobMcpToolSnapshotService
from app.shared.dingtalk_tool_contracts import (
    DINGTALK_CONFIRMATION_POLICY,
    DINGTALK_EXCLUDED_TOOL_IDENTIFIERS,
    DINGTALK_TOOL_CONTRACTS,
)
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


def test_phase_2_catalog_is_exact_and_execution_metadata_is_fixed() -> None:
    assert len(EXPECTED_DINGTALK_TOOLS) == 27
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
