from __future__ import annotations

from jsonschema import Draft202012Validator

from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.modules.mcp_tool_runtime.job_snapshot import JobMcpToolSnapshotService
from app.shared.dingtalk_tool_contracts import (
    DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER,
    DINGTALK_CONFIRMATION_POLICY,
    DINGTALK_EXCLUDED_TOOL_IDENTIFIERS,
    DINGTALK_OFFICIAL_PROFILE_TOOL_CLASSIFICATION,
    DINGTALK_OFFICIAL_TOOL_NAMES,
    DINGTALK_SEND_MESSAGE_TO_GROUP_TOOL_IDENTIFIER,
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
    "dingtalk_get_aitable_supported_search_filters": (
        "read",
        "dingtalk.aitable.reference.search_filters.get",
        "static_official_reference",
    ),
    "dingtalk_get_aitable_supported_field_info": (
        "read",
        "dingtalk.aitable.reference.field_info.get",
        "static_official_reference",
    ),
    "dingtalk_get_aitable_record_values_format": (
        "read",
        "dingtalk.aitable.reference.record_values_format.get",
        "static_official_reference",
    ),
    "dingtalk_list_aitable_sheets": (
        "read",
        "dingtalk.aitable.sheet.list",
        "explicit_aitable_resource_for_current_operator",
    ),
    "dingtalk_get_aitable_sheet": (
        "read",
        "dingtalk.aitable.sheet.get",
        "explicit_aitable_resource_for_current_operator",
    ),
    "dingtalk_list_aitable_fields": (
        "read",
        "dingtalk.aitable.field.list",
        "explicit_aitable_resource_for_current_operator",
    ),
    "dingtalk_list_aitable_records": (
        "read",
        "dingtalk.aitable.record.list",
        "explicit_aitable_resource_for_current_operator",
    ),
    "dingtalk_get_aitable_record": (
        "read",
        "dingtalk.aitable.record.get",
        "explicit_aitable_resource_for_current_operator",
    ),
    "dingtalk_create_aitable_sheet": (
        "mutation",
        "dingtalk.aitable.sheet.create",
        "explicit_aitable_resource_for_current_operator",
    ),
    "dingtalk_update_aitable_sheet": (
        "mutation",
        "dingtalk.aitable.sheet.update",
        "explicit_aitable_resource_for_current_operator",
    ),
    "dingtalk_create_aitable_field": (
        "mutation",
        "dingtalk.aitable.field.create",
        "explicit_aitable_resource_for_current_operator",
    ),
    "dingtalk_update_aitable_field": (
        "mutation",
        "dingtalk.aitable.field.update",
        "explicit_aitable_resource_for_current_operator",
    ),
    "dingtalk_insert_aitable_records": (
        "mutation",
        "dingtalk.aitable.record.insert",
        "explicit_aitable_resource_for_current_operator",
    ),
    "dingtalk_update_aitable_records": (
        "mutation",
        "dingtalk.aitable.record.update",
        "explicit_aitable_resource_for_current_operator",
    ),
    DINGTALK_SEND_MESSAGE_TO_GROUP_TOOL_IDENTIFIER: (
        "mutation",
        "dingtalk.robot.group_message.send",
        "current_source_group",
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

OFFICIAL_DESCRIPTION_MARKERS = {
    "dingtalk_search_users": ("姓名", "姓名拼音", "英文名称", "user_id"),
    "dingtalk_get_user": ("user_id", "详细信息", "union_id"),
    "dingtalk_list_department_users": ("指定部门", "所有成员", "user_id"),
    "dingtalk_search_departments": ("部门名称", "拼音", "部门ID"),
    "dingtalk_get_department": ("部门名称", "父部门", "管理员", "权限设置"),
    "dingtalk_list_sub_departments": ("下一级子部门", "基础信息"),
    "dingtalk_list_todos": ("查询钉钉待办/任务列表",),
    "dingtalk_create_todo": ("创建", "待办"),
    "dingtalk_update_todo": ("更新", "待办"),
    "dingtalk_complete_todo": ("更新执行人", "待办完成状态"),
    "dingtalk_get_calendar_event": ("查询单个", "日程", "详细信息"),
    "dingtalk_list_calendar_events": ("查询钉钉日程视图", "时间范围", "日程列表"),
    "dingtalk_list_calendar_attendees": ("日程参与者列表",),
    "dingtalk_create_calendar_event": (
        "创建一个新的钉钉日程",
        "时间",
        "地点",
        "参与者",
        "提醒",
        "重复规则",
    ),
    "dingtalk_update_calendar_event": ("修改已存在", "日程"),
    "dingtalk_search_aitables": ("根据名称查询", "AI表格/多维表"),
    "dingtalk_get_aitable_supported_search_filters": ("支持的搜索过滤条件",),
    "dingtalk_get_aitable_supported_field_info": ("支持的字段类型", "额外属性"),
    "dingtalk_get_aitable_record_values_format": ("记录值格式",),
    "dingtalk_list_aitable_sheets": ("所有数据表",),
    "dingtalk_get_aitable_sheet": ("单个数据表", "ID和名称"),
    "dingtalk_list_aitable_fields": ("指定数据表", "所有字段"),
    "dingtalk_list_aitable_records": ("指定数据表", "多行记录"),
    "dingtalk_get_aitable_record": ("指定数据表", "单行记录"),
    "dingtalk_create_aitable_sheet": ("创建", "数据表"),
    "dingtalk_update_aitable_sheet": ("更新", "数据表", "名称"),
    "dingtalk_create_aitable_field": ("创建字段",),
    "dingtalk_update_aitable_field": ("更新", "字段"),
    "dingtalk_insert_aitable_records": ("指定数据表", "新增行记录"),
    "dingtalk_update_aitable_records": ("指定数据表", "多行记录"),
    DINGTALK_SEND_MESSAGE_TO_GROUP_TOOL_IDENTIFIER: (
        "向群聊发送普通消息",
        "非DING",
        "非待办",
    ),
    DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER: (
        "一个或多个个人用户",
        "一对一单聊",
        "不能用于群聊",
    ),
    "dingtalk_send_work_notification": ("发送钉钉工作通知消息", "支持markdown消息类型"),
    "dingtalk_get_work_notification_progress": ("发送进度", "实时查询"),
    "dingtalk_get_work_notification_result": ("发送结果", "发送状态", "统计信息"),
}

GOVERNANCE_SUBSET_MARKERS = {
    "dingtalk_create_todo": ("标题、描述和截止时间", "不接受任意执行人或参与人"),
    "dingtalk_update_todo": (
        "只更新标题、描述和截止时间",
        "不修改执行人、参与人或完成状态",
        "dingtalk_complete_todo",
    ),
    "dingtalk_complete_todo": ("不支持替其他执行人更新", "重新打开"),
    "dingtalk_get_calendar_event": (
        "日程字段白名单",
        "dingtalk_list_calendar_attendees",
    ),
    "dingtalk_list_calendar_events": (
        "日程字段白名单",
        "dingtalk_list_calendar_attendees",
    ),
    "dingtalk_create_calendar_event": ("不支持参与者、提醒或重复规则",),
    "dingtalk_update_calendar_event": ("不修改参与者、提醒或重复规则",),
    "dingtalk_search_aitables": ("只接受名称关键词", "不接受模型指定创建者过滤条件"),
    "dingtalk_list_aitable_records": ("官方notablev1分页接口", "不接受字段过滤条件"),
    "dingtalk_create_aitable_sheet": ("原用户确认", "不支持删除"),
    "dingtalk_update_aitable_sheet": ("原用户确认", "不支持删除"),
    "dingtalk_create_aitable_field": ("原用户确认", "不支持删除"),
    "dingtalk_update_aitable_field": ("原用户确认", "不支持删除"),
    DINGTALK_SEND_MESSAGE_TO_GROUP_TOOL_IDENTIFIER: ("markdown普通消息", "受信钉钉来源群"),
    DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER: (
        "markdown普通消息",
        "全部匹配者",
        "全部已核实user_id放入同一批",
        "单数目标仍有多个候选",
    ),
    "dingtalk_send_work_notification": ("只向当前用户本人",),
}


def test_governed_catalog_is_exact_and_execution_metadata_is_fixed() -> None:
    assert len(EXPECTED_DINGTALK_TOOLS) == 35
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
        assert contract.open_world is (
            effect == "read" and target_policy != "static_official_reference"
        )
        assert contract.requires_target_union_id is (
            target_policy
            not in {
                "enterprise_directory_visible_scope",
                "static_official_reference",
                "current_user_work_notification_history",
            }
        )

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


def test_aitable_record_schema_accepts_official_bounded_value_formats() -> None:
    schema = DINGTALK_TOOL_CONTRACTS["dingtalk_insert_aitable_records"].input_schema
    payload = {
        "base_id": "base-1",
        "sheet_id": "sheet-1",
        "records": [
            {
                "fields": {
                    "标题": "示例",
                    "排名": 1,
                    "单选": "选项一",
                    "多选": ["选项一", "选项二"],
                    "日期": 1788105600000,
                    "人员": [{"unionId": "union-1"}],
                    "部门": [{"deptId": "1"}],
                    "关联": {"linkedRecordIds": ["record-1"]},
                    "链接": {"text": "钉钉", "link": "https://www.dingtalk.com"},
                }
            }
        ],
    }

    assert list(Draft202012Validator(schema).iter_errors(payload)) == []


def test_create_todo_input_schema_hash_remains_mvp_compatible() -> None:
    assert (
        MCP_TOOL_MANIFEST["dingtalk_create_todo"].schema_hash
        == "8de526e0593a7a4520bd4e35b2c71699b3b2ff5d7e5f59c237bdf0328eb9ee38"
    )


def test_group_robot_and_work_notification_contracts_are_explicit() -> None:
    expected = "402f0f259941318877432487b3d6501339ec80958772acf532211406c6c82aca"
    group = MCP_TOOL_MANIFEST[DINGTALK_SEND_MESSAGE_TO_GROUP_TOOL_IDENTIFIER]
    assert group.schema_hash == expected
    assert "官方功能：使用企业机器人向群聊发送普通消息" in group.description
    assert "当前 Job 的受信钉钉来源群" in group.description
    assert "私聊或按 user_id" in group.description
    assert "dingtalk_batch_send_message_to_users_by_robot" in group.description
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
    assert "只表示发送请求已受理" in definition.description
    assert "最终送达必须以钉钉事实为准" in definition.description


def test_async_message_contracts_do_not_claim_final_delivery() -> None:
    group = MCP_TOOL_MANIFEST[DINGTALK_SEND_MESSAGE_TO_GROUP_TOOL_IDENTIFIER]
    notice = MCP_TOOL_MANIFEST["dingtalk_send_work_notification"]

    assert "只表示发送请求已受理" in group.description
    assert "不能宣称消息已最终送达" in group.description
    assert "只表示异步发送任务已提交" in notice.description
    assert "发送进度和发送结果 Tool" in notice.description


def test_read_result_contracts_are_bounded_and_require_business_fields() -> None:
    notice_result = DINGTALK_TOOL_CONTRACTS[
        "dingtalk_get_work_notification_result"
    ].output_schema["properties"]["result"]
    assert set(notice_result["required"]) == {
        "task_id",
        "invalid_user_ids",
        "invalid_user_count",
        "forbidden_user_ids",
        "forbidden_user_count",
        "failed_user_ids",
        "failed_user_count",
        "read_user_ids",
        "read_user_count",
        "unread_user_ids",
        "unread_user_count",
        "invalid_department_ids",
        "invalid_department_count",
        "truncated",
    }
    assert notice_result["properties"]["invalid_user_ids"]["maxItems"] == 50

    required_strings = (
        ("dingtalk_get_department", "department", ("name",)),
        ("dingtalk_list_todos", "todos", ("subject",)),
        (
            "dingtalk_get_calendar_event",
            "event",
            ("title", "start_time", "end_time"),
        ),
        ("dingtalk_search_aitables", "aitables", ("name",)),
        ("dingtalk_list_aitable_sheets", "sheets", ("name",)),
        (
            "dingtalk_list_aitable_fields",
            "fields",
            ("name", "field_type"),
        ),
    )
    for identifier, field, names in required_strings:
        container = DINGTALK_TOOL_CONTRACTS[identifier].output_schema["properties"][field]
        item = container["items"] if "items" in container else container
        for name in names:
            assert name in item["required"]
            assert item["properties"][name]["minLength"] == 1


def test_explicitly_excluded_tools_never_enter_contract_or_manifest() -> None:
    assert DINGTALK_EXCLUDED_TOOL_IDENTIFIERS
    assert set(DINGTALK_EXCLUDED_TOOL_IDENTIFIERS).isdisjoint(DINGTALK_TOOL_CONTRACTS)
    assert set(DINGTALK_EXCLUDED_TOOL_IDENTIFIERS).isdisjoint(MCP_TOOL_MANIFEST)


def test_each_registered_tool_maps_one_to_one_to_an_official_capability() -> None:
    assert set(DINGTALK_OFFICIAL_TOOL_NAMES) == set(DINGTALK_TOOL_CONTRACTS)
    assert len(set(DINGTALK_OFFICIAL_TOOL_NAMES.values())) == 35
    assert (
        DINGTALK_OFFICIAL_TOOL_NAMES[DINGTALK_SEND_MESSAGE_TO_GROUP_TOOL_IDENTIFIER]
        == "sendMessageToGroupByRobot"
    )
    assert (
        DINGTALK_OFFICIAL_TOOL_NAMES[DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER]
        == "batchSendMessageToUsersByRobot"
    )


def test_all_tools_in_the_seven_official_profiles_are_classified_once() -> None:
    assert set(DINGTALK_OFFICIAL_PROFILE_TOOL_CLASSIFICATION) == {
        "dingtalk-contacts",
        "dingtalk-department",
        "dingtalk-notable",
        "dingtalk-calendar",
        "dingtalk-tasks",
        "dingtalk-robot-send-message",
        "dingtalk-notice",
    }
    all_names: list[str] = []
    registered: set[str] = set()
    for categories in DINGTALK_OFFICIAL_PROFILE_TOOL_CLASSIFICATION.values():
        assert set(categories) == {"registered", "excluded", "resource"}
        for category, names in categories.items():
            all_names.extend(names)
            if category == "registered":
                registered.update(names)
    assert len(all_names) == 52
    assert len(set(all_names)) == 52
    assert registered == set(DINGTALK_OFFICIAL_TOOL_NAMES.values())


def test_all_model_visible_descriptions_separate_official_semantics_and_governance() -> None:
    for contract in DINGTALK_TOOL_CONTRACTS.values():
        assert contract.description.startswith("官方功能："), contract.identifier
        assert "平台治理：" in contract.description, contract.identifier


def test_all_registered_tool_descriptions_keep_official_function_semantics() -> None:
    assert set(OFFICIAL_DESCRIPTION_MARKERS) == set(DINGTALK_TOOL_CONTRACTS)
    assert set(DINGTALK_OFFICIAL_TOOL_NAMES) == set(DINGTALK_TOOL_CONTRACTS)

    for identifier, markers in OFFICIAL_DESCRIPTION_MARKERS.items():
        official_part = DINGTALK_TOOL_CONTRACTS[identifier].description.split("平台治理：", 1)[0]
        normalized = "".join(official_part.split()).replace("_", "").lower()
        for marker in markers:
            normalized_marker = "".join(marker.split()).replace("_", "").lower()
            assert normalized_marker in normalized, (identifier, marker, official_part)


def test_descriptions_disclose_governed_subsets_of_broader_official_tools() -> None:
    for identifier, markers in GOVERNANCE_SUBSET_MARKERS.items():
        governance_part = DINGTALK_TOOL_CONTRACTS[identifier].description.split(
            "平台治理：", 1
        )[1]
        normalized = "".join(governance_part.split()).replace("_", "").lower()
        for marker in markers:
            normalized_marker = "".join(marker.split()).replace("_", "").lower()
            assert normalized_marker in normalized, (
                identifier,
                marker,
                governance_part,
            )


def test_get_user_contract_matches_latest_batch_lookup_without_legacy_arguments() -> None:
    contract = DINGTALK_TOOL_CONTRACTS["dingtalk_get_user"]

    assert contract.input_schema["required"] == ["user_id"]
    assert set(contract.input_schema["properties"]) == {"user_id"}
    user_properties = contract.output_schema["properties"]["user"]["properties"]
    assert "job_number" in user_properties
    assert "mobile" not in user_properties
    assert "avatar" not in user_properties
    assert "最新批量用户查询接口" in contract.description
    assert "只需原样传入 user_id" in contract.description


def test_aitable_v1_contracts_bind_resources_to_current_operator() -> None:
    search = DINGTALK_TOOL_CONTRACTS["dingtalk_search_aitables"]
    assert search.target_policy == "current_user_aitable_operator"
    assert "operator 由当前 Job 服务端解析" in search.description

    for identifier in (
        "dingtalk_list_aitable_sheets",
        "dingtalk_get_aitable_sheet",
        "dingtalk_list_aitable_fields",
        "dingtalk_list_aitable_records",
        "dingtalk_get_aitable_record",
    ):
        contract = DINGTALK_TOOL_CONTRACTS[identifier]
        assert contract.target_policy == "explicit_aitable_resource_for_current_operator"
        assert "企业应用 Access Token" in contract.description
        assert "operator" in contract.description

    for identifier in (
        "dingtalk_create_aitable_sheet",
        "dingtalk_update_aitable_sheet",
        "dingtalk_create_aitable_field",
        "dingtalk_update_aitable_field",
        "dingtalk_insert_aitable_records",
        "dingtalk_update_aitable_records",
    ):
        contract = DINGTALK_TOOL_CONTRACTS[identifier]
        assert contract.target_policy == "explicit_aitable_resource_for_current_operator"
        assert "企业应用 Access Token" in contract.description
        assert "operator" in contract.description


def test_new_job_snapshot_metadata_detects_operation_policy_drift() -> None:
    definition = MCP_TOOL_MANIFEST[DINGTALK_SEND_MESSAGE_TO_GROUP_TOOL_IDENTIFIER]
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
