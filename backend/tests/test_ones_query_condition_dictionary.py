from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.shared.exceptions import AppError
from scripts.sync_ones_query_condition_dictionary import (
    build_snapshot,
    render_snapshot,
    sync,
)
from services.ones_mcp_server.condition_dictionary import QueryConditionDictionary


SYNTHETIC_SOURCE = """# 查询条件字典：filterGroup 中 UUID -> 中文/显示名
# 数据来源：ONES 团队 MOCK-ONES-TEAM-001，接口拉取日期 2026-08-27。UUID 以接口实时数据为准。
statusCategory_in:
  done: 完成
status_in:
  MOCK-STATUS-DONE: 已完成  # 完成
issueType_in:
  MOCK-TYPE-TASK: 任务
project_in:
  MOCK-PROJECT: 合成项目
assign_in:
  MOCK-USER: 合成人员
all_option_fields:
  MOCK-CUSTOM-FIELD-SEVERITY:  # 严重程度 type=1
    MOCK-CUSTOM-OPTION-HIGH: 严重
    MOCK-CUSTOM-OPTION-HIGH-ALT: 严重
    MOCK-CUSTOM-OPTION-LOW: 一般
  MOCK-CUSTOM-FIELD-TAGS:  # 标签 type=16
    MOCK-CUSTOM-OPTION-REGRESSION: 回归
sprint_in:
  MOCK-SPRINT: 合成迭代
"""


def _dictionary(tmp_path: Path) -> QueryConditionDictionary:
    source = tmp_path / "source.yaml"
    output = tmp_path / "dictionary.json"
    source.write_text(SYNTHETIC_SOURCE, encoding="utf-8")
    sync(source, output)
    return QueryConditionDictionary.load(output)


def test_sync_builds_deterministic_minimal_snapshot(tmp_path: Path) -> None:
    source_bytes = SYNTHETIC_SOURCE.encode("utf-8")
    first = render_snapshot(build_snapshot(source_bytes))
    second = render_snapshot(build_snapshot(source_bytes))
    assert first == second
    payload = json.loads(first)
    assert set(payload) == {
        "captured_at",
        "content_sha256",
        "custom_option_fields",
        "dictionary_version",
        "schema_version",
        "source_sha256",
        "source_team_uuid",
        "statuses",
    }
    rendered = first.decode("utf-8")
    for forbidden in (
        "assign_in",
        "project_in",
        "sprint_in",
        "issueType_in",
        "MOCK-USER",
        "合成人员",
        "合成项目",
        "合成迭代",
        "Ones-Auth-Token",
        "email",
        "phone",
    ):
        assert forbidden not in rendered


def test_sync_failure_does_not_replace_existing_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "source.yaml"
    output = tmp_path / "dictionary.json"
    source.write_text("status_in: {}\n", encoding="utf-8")
    output.write_text("preserved", encoding="utf-8")
    with pytest.raises(ValueError):
        sync(source, output)
    assert output.read_text(encoding="utf-8") == "preserved"

    source.write_text(
        SYNTHETIC_SOURCE.replace("2026-08-27", "2026-13-40"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="capture date"):
        sync(source, output)
    assert output.read_text(encoding="utf-8") == "preserved"


def test_dictionary_resolves_names_and_validates_custom_option_ownership(
    tmp_path: Path,
) -> None:
    dictionary = _dictionary(tmp_path)
    status = dictionary.resolve(
        team_uuid="MOCK-ONES-TEAM-001",
        condition_type="status",
        keyword="完成",
        field_keyword="",
        limit=20,
    )
    assert status["matches"] == [
        {
            "condition_type": "status",
            "uuid": "MOCK-STATUS-DONE",
            "name": "已完成",
            "category": "done",
        }
    ]

    options = dictionary.resolve(
        team_uuid="MOCK-ONES-TEAM-001",
        condition_type="custom_option",
        keyword="严重",
        field_keyword="严重程度",
        limit=20,
    )
    assert options["matches"] == [
        {
            "condition_type": "custom_option",
            "field_uuid": "MOCK-CUSTOM-FIELD-SEVERITY",
            "field_name": "严重程度",
            "option_uuid": "MOCK-CUSTOM-OPTION-HIGH",
            "option_name": "严重",
        },
        {
            "condition_type": "custom_option",
            "field_uuid": "MOCK-CUSTOM-FIELD-SEVERITY",
            "field_name": "严重程度",
            "option_uuid": "MOCK-CUSTOM-OPTION-HIGH-ALT",
            "option_name": "严重",
        },
    ]
    assert dictionary.validated_custom_filters(
        team_uuid="MOCK-ONES-TEAM-001",
        filters=[
            {
                "field_uuid": "MOCK-CUSTOM-FIELD-SEVERITY",
                "option_uuids": ["MOCK-CUSTOM-OPTION-HIGH"],
            }
        ],
    ) == [
        {
            "field_uuid": "MOCK-CUSTOM-FIELD-SEVERITY",
            "filter_key": "_MOCK-CUSTOM-FIELD-SEVERITY_in",
            "option_uuids": ["MOCK-CUSTOM-OPTION-HIGH"],
        }
    ]

    with pytest.raises(AppError) as wrong_team:
        dictionary.resolve(
            team_uuid="OTHER-TEAM",
            condition_type="status",
            keyword="完成",
            field_keyword="",
            limit=20,
        )
    assert wrong_team.value.error_code == "ones_query_condition_scope_mismatch"

    with pytest.raises(AppError) as cross_field:
        dictionary.validated_custom_filters(
            team_uuid="MOCK-ONES-TEAM-001",
            filters=[
                {
                    "field_uuid": "MOCK-CUSTOM-FIELD-TAGS",
                    "option_uuids": ["MOCK-CUSTOM-OPTION-HIGH"],
                }
            ],
        )
    assert cross_field.value.error_code == "ones_query_condition_invalid"


def test_dictionary_rejects_digest_tampering(tmp_path: Path) -> None:
    source = tmp_path / "source.yaml"
    output = tmp_path / "dictionary.json"
    source.write_text(SYNTHETIC_SOURCE, encoding="utf-8")
    sync(source, output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["statuses"][0]["name"] = "tampered"
    output.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(AppError) as raised:
        QueryConditionDictionary.load(output)
    assert raised.value.error_code == "ones_query_condition_resource_invalid"


def test_dictionary_rejects_version_tampering(tmp_path: Path) -> None:
    source = tmp_path / "source.yaml"
    output = tmp_path / "dictionary.json"
    source.write_text(SYNTHETIC_SOURCE, encoding="utf-8")
    sync(source, output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["dictionary_version"] = "2026-08-27-unrelated"
    output.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(AppError) as raised:
        QueryConditionDictionary.load(output)
    assert raised.value.error_code == "ones_query_condition_resource_invalid"
