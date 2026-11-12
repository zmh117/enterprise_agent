"""合成多页来源与 Job 文件验证，不使用真实账号或业务正文。"""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import validate

from app.modules.agent.infrastructure.skill_loader import SkillLoader
from app.python_runtime.job_sandbox import JobSandboxManager
from app.python_runtime.ones_result_bridge import materialize_result
from app.shared.exceptions import AppError
from app.shared.knowledge_tool_contracts import KNOWLEDGE_USAGE_INSTRUCTIONS
from app.shared.ones_tool_contracts import ONES_TOOL_CONTRACTS
from services.ones_mcp_server.provider.rest.operations import basic_queries as timeline
from services.ones_mcp_server.tools.query_services import OnesWorkItemMessageListService


STAMP = 1_767_225_600_123_456


def message(index, text="合成评论"):
    return {
        "uuid": f"M-{index}",
        "type": "discussion",
        "send_time": STAMP - index,
        "from": "USER-1",
        "text": text,
    }


def page(rows, more=False):
    return {"messages": rows, "count": len(rows), "has_next": more}


class TimelineHttp:
    target = SimpleNamespace(base_url="https://ones.example.test")

    def __init__(self, pages):
        self.pages, self.calls = list(pages), []

    def get_json(self, path, body, *, headers, query):
        assert body is None and path.endswith("/task/TASK-1/messages")
        self.calls.append(query)
        result = self.pages.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def collect(http):
    return timeline.WORK_ITEM_MESSAGES_OPERATION.execute(
        http, team_uuid="TEAM-1", work_item_uuid="TASK-1", token="synthetic", user_id="USER-1"
    ).output


def test_older_page_changes_resolution_and_file_exposes_coverage(tmp_path):
    http = TimelineHttp(
        [
            page([message(i, "主线修复") for i in range(100)], True),
            page([message(100, "现场未换包，回归仍复现，重新打开。")]),
        ]
    )
    result = collect(http)
    assert http.calls == [{"count": "100"}, {"count": "100", "max": str(STAMP - 99)}]
    assert result["returned"] == 101 and result["page_count"] == 2
    assert result["complete"] and result["messages_complete"] and result["total_known"]
    assert "现场未换包" in result["messages"][-1]["text"]
    assert result["newest_at"] > result["oldest_at"]
    validate(result, ONES_TOOL_CONTRACTS["ones_list_work_item_messages"].output_schema)
    sandbox = JobSandboxManager(tmp_path).create("job-timeline")
    summary = materialize_result(sandbox, "ones_list_work_item_messages", result)
    assert "messages" not in summary and summary["page_count"] == 2
    assert summary["complete"] and "未读完" in summary["read_hint"]
    path = sandbox.path / summary["result_file"]
    assert "现场未换包" in path.read_text()
    sandbox.authorize_tool("Read", {"file_path": str(path)})
    sandbox.cleanup()
    assert not path.exists()


@pytest.mark.parametrize("count", [0, 1, 99, 100, 101, 1000, 1001])
def test_actual_terminal_page_and_item_limit(count):
    rows = [message(i) for i in range(count)]
    pages = [page(rows[i : i + 100], i + 100 < count) for i in range(0, count, 100)] or [page([])]
    result = collect(TimelineHttp(pages))
    assert result["returned"] == min(count, 1000)
    assert result["messages_complete"] is (count <= 1000)
    assert result["complete"] is (count <= 1000)
    assert result["total_known"] is (count <= 1000)
    assert result["incomplete_reasons"] == (["item_limit"] if count > 1000 else [])


def test_short_pages_follow_explicit_has_next_and_page_cap(monkeypatch):
    monkeypatch.setattr(timeline, "MAX_MESSAGE_PAGES", 2)
    http = TimelineHttp([page([message(0)], True), page([message(1)], True)])
    result = collect(http)
    assert result["returned"] == 2 and result["incomplete_reasons"] == ["page_limit"]
    assert http.calls[-1]["max"] == str(STAMP)


@pytest.mark.parametrize(
    "bad",
    [
        page([message(0)], True),  # repeated UUID/time
        page([dict(message(1), send_time=STAMP + 1)]),
        page([message(2), message(1)]),  # unordered page
        page([], True),
        {"messages": [message(1)], "count": 2, "has_next": False},
        {"messages": [message(1)], "count": 1},
        page([message(i) for i in range(1, 102)]),
        page([dict(message(1), send_time=True)]),
        page([dict(message(1), send_time=STAMP)]),
        AppError("synthetic forbidden", error_code="ones_provider_forbidden"),
    ],
)
def test_later_page_failure_never_returns_partial_success(bad):
    with pytest.raises(AppError):
        collect(TimelineHttp([page([message(0)], True), bad]))


def test_bytes_and_deadline_are_bounded(monkeypatch):
    monkeypatch.setattr(timeline, "MAX_MESSAGE_BYTES", 10)
    with pytest.raises(AppError, match="fixed schema") as raised:
        collect(TimelineHttp([page([message(0)])]))
    assert raised.value.error_code == "ones_collection_size_exceeded"
    from app.shared import ones_io_budget

    ticks = iter([0, 91])
    monkeypatch.setattr(ones_io_budget.time, "monotonic", lambda: next(ticks))
    http = TimelineHttp([page([message(0)])])
    with pytest.raises(AppError) as expired:
        collect(http)
    assert expired.value.error_code == "ones_read_budget_exhausted" and not http.calls


@pytest.mark.parametrize("text", ["长" * 16001, "<b>" * 40000])
def test_content_truncation_survives_runtime_summary(tmp_path, text):
    result = collect(TimelineHttp([page([message(0, text)])]))
    assert result["messages_complete"] and not result["complete"]
    assert result["text_truncated_count"] == 1
    assert result["incomplete_reasons"] == ["text_limit"]
    sandbox = JobSandboxManager(tmp_path).create("job-long-comment")
    summary = materialize_result(sandbox, "ones_list_work_item_messages", result)
    assert not summary["complete"] and summary["incomplete_reasons"] == ["text_limit"]
    sandbox.cleanup()


def test_comments_are_safe_data_and_no_cursor_or_limit_is_public():
    result = collect(
        TimelineHttp(
            [
                page(
                    [
                        message(
                            0,
                            "<b>已修复</b><script>secret</script> token=private-value https://private.test/key",
                        )
                    ]
                )
            ]
        )
    )
    serialized = json.dumps(result)
    assert "private-value" not in serialized and "private.test" not in serialized
    assert result["messages"][0]["text"].startswith("已修复")
    service = object.__new__(OnesWorkItemMessageListService)
    contract = ONES_TOOL_CONTRACTS["ones_list_work_item_messages"]
    assert service.validate_arguments({"work_item_uuid": "TASK-1"}) == {"work_item_uuid": "TASK-1"}
    for key in ("limit", "cursor", "since", "max", "team_uuid", "url"):
        args = {"work_item_uuid": "TASK-1", key: "forbidden"}
        with pytest.raises(AppError):
            service.validate_arguments(args)
        with pytest.raises(Exception):
            validate(args, contract.input_schema)


def test_detail_discloses_truncated_description_and_related_items():
    from services.ones_mcp_server.provider.graphql.operations.business_queries import (
        _detail_response,
    )

    task = {
        "uuid": "T",
        "number": 1,
        "name": "合成问题",
        "project": {"uuid": "P", "name": "项目"},
        "issueType": {"uuid": "I", "name": "缺陷"},
        "status": {"uuid": "S", "name": "New", "category": "to_do"},
        "descriptionText": "长" * 4001,
    }
    task["relatedTasks"] = [deepcopy(task) for _ in range(101)]
    result = _detail_response({"data": {"task": task}}, {})
    assert result["description_truncated"] and result["related_items_truncated"]
    assert len(result["description"]) == 4000 and len(result["related_items"]) == 100


def test_knowledge_diagnosis_instructions_require_detail_and_comment_reading():
    skills = SkillLoader(Path(".claude/skills")).load(("ones-query", "bug-analysis"))
    for text in (KNOWLEDGE_USAGE_INSTRUCTIONS, skills["ones-query"]):
        for token in (
            "ones_get_work_item_detail",
            "ones_list_work_item_messages",
            "重开",
            "未",
            "text_truncated_count",
        ):
            assert token in text
    assert "评论" in skills["bug-analysis"] and "证据缺口" in skills["bug-analysis"]
