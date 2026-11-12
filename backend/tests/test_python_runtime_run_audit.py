from __future__ import annotations

import json
from pathlib import Path
from dataclasses import replace

import pytest

from app.modules.agent.domain.runtime import AgentExecutionContext, McpRuntimeBinding
from app.python_runtime.job_sandbox import JobSandboxManager
from app.python_runtime.run_audit import (
    RunAuditRecorder,
    decode_audit_chunks,
    encode_audit_chunks,
)


def _context(marker: str) -> AgentExecutionContext:
    return AgentExecutionContext(
        system_role=f"system::{marker}",
        business_instructions=f"business::{marker}",
        safety_rules=["safe"],
        user_question=f"user::{marker}",
        project_code="default",
        allowed_tools=[],
        tool_restrictions=["governed"],
        skills={"audit-skill": f"skill::{marker}"},
        retrieved_context={
            "session": f"session::{marker}",
            "file": f"file::{marker}",
        },
        conversation_summary=f"conversation::{marker}",
        model="claude-test",
        publication_id="publication-1",
        application_publication_id="application-publication-1",
        runtime_protocol_version="1.5",
        effective_tool_names=("mcp__example__lookup",),
        mcp_bindings=(
            McpRuntimeBinding(
                server_code="example",
                tool_name="lookup",
                required_scope="mcp:example:lookup:invoke",
                tool_schema_hash="a" * 64,
            ),
        ),
    )


def test_code_tool_audit_keeps_denial_and_pending_status_without_source_bodies(tmp_path):
    context = replace(_context("synthetic"), retrieved_context={"code_source": {"job_id": "job"}})
    recorder = RunAuditRecorder(
        context, system_prompt="synthetic", raw_api_dir=tmp_path, permission_snapshot={}
    )
    recorder.observe_code_tool_events(
        [
            {
                "tool_call_id": "read-1",
                "tool_name": "Read",
                "status": "STARTED",
                "request_payload": {"file_path": "DO_NOT_COPY/private.cpp"},
            },
            {
                "tool_call_id": "read-1",
                "tool_name": "Read",
                "status": "DENIED",
                "error_code": "CODE_SOURCE_SENSITIVE",
                "response_summary": {"text": "DO_NOT_COPY"},
            },
            {
                "tool_call_id": "glob-2",
                "tool_name": "Glob",
                "status": "STARTED",
                "request_payload": {"pattern": "DO_NOT_COPY"},
            },
        ]
    )
    audit = recorder.finalize(status="FAILED")
    assert [(item["tool_name"], item["status"]) for item in audit["tool_executions"]] == [
        ("Read", "DENIED"),
        ("Glob", "STARTED"),
    ]
    assert audit["tool_executions"][0]["error_code"] == "CODE_SOURCE_SENSITIVE"
    assert audit["summary"]["tool_call_count"] == 2
    assert "DO_NOT_COPY" not in json.dumps(audit)
    assert audit["sdk_messages"] == []


@pytest.mark.parametrize("shape", ["flat", "nested", "sdk"])
def test_extraction_init_projects_observed_metadata_without_message_body(tmp_path, shape):
    from claude_agent_sdk import SystemMessage
    from app.python_runtime.claude_client import _permission_snapshot

    context = replace(_context("synthetic"), retrieved_context={"code_source": {"job_id": "job"}})
    permissions = _permission_snapshot(context)
    assert permissions["sdk_version"] != "unknown"
    assert permissions["cli_version"] not in {"unknown", "unavailable"}
    recorder = RunAuditRecorder(
        context, system_prompt="synthetic", raw_api_dir=tmp_path, permission_snapshot=permissions
    )
    data = {
        "tools": ["Read", "Glob", "Grep", "Write", "Edit", "UnexpectedTool"],
        "skills": ["bundled-skill"],
        "mcp_servers": [{"name": "unexpected-mcp", "status": "connected", "token": "DO_NOT_COPY"}],
        "cwd": "/DO_NOT_COPY/private",
        "apiKeySource": "DO_NOT_COPY",
        "system_prompt": "DO_NOT_COPY source code",
        "extra": {"body": "DO_NOT_COPY"},
    }
    message = (
        SystemMessage(subtype="init", data=data)
        if shape == "sdk"
        else {
            "type": "system",
            "subtype": "init",
            **({"data": data} if shape == "nested" else data),
        }
    )
    recorder.observe_message(message)
    result = recorder.finalize(status="SUCCEEDED")
    snapshot = result["init_snapshot"]
    assert snapshot["data"] == {
        "tools": data["tools"],
        "skills": ["bundled-skill"],
        "mcp_servers": [{"name": "unexpected-mcp", "status": "connected"}],
        "metadata_complete": True,
    }
    assert snapshot["sdk_version"] == permissions["sdk_version"]
    assert snapshot["cli_version"] == permissions["cli_version"]
    assert result["summary"]["registered_tool_count"] == 6
    assert result["sdk_messages"] == result["api_requests"] == result["api_responses"] == []
    assert "DO_NOT_COPY" not in json.dumps(result)
    digest, chunks = encode_audit_chunks(result)
    # The existing invocation transport must preserve the restricted init snapshot.
    restored = decode_audit_chunks(chunks, expected_sha256=digest, expected_count=len(chunks))
    assert restored["init_snapshot"] == snapshot


def test_extraction_init_is_bounded_and_does_not_invent_missing_lists(tmp_path):
    context = replace(_context("synthetic"), retrieved_context={"code_source": {"job_id": "job"}})
    recorder = RunAuditRecorder(
        context, system_prompt="synthetic", raw_api_dir=tmp_path, permission_snapshot={}
    )
    assert recorder.audit["init_snapshot"] == {}
    recorder.observe_message({"type": "system", "subtype": "init", "data": {}})
    assert recorder.audit["init_snapshot"]["data"] == {
        "tools": None,
        "skills": None,
        "mcp_servers": None,
        "metadata_complete": False,
    }
    recorder.observe_message(
        {
            "type": "system",
            "subtype": "init",
            "data": {
                "tools": ["Read"] * 300,
                "skills": ["safe-skill", "/private/path", "DO_NOT_COPY secret", {}, "x" * 129],
                "mcp_servers": [
                    {"name": "safe", "status": "DO_NOT_COPY"},
                    {"name": "/DO_NOT_COPY", "status": "connected"},
                ],
            },
        }
    )
    snapshot = recorder.audit["init_snapshot"]
    assert len(snapshot["data"]["tools"]) == 256
    assert snapshot["data"]["skills"] == ["safe-skill"]
    assert snapshot["data"]["mcp_servers"] == [{"name": "safe", "status": "unknown"}]
    assert snapshot["data"]["metadata_complete"] is False
    assert "DO_NOT_COPY" not in json.dumps(snapshot)


def test_recorder_keeps_complete_model_visible_content_and_raw_bodies(
    tmp_path: Path,
) -> None:
    marker = "secret-like-business-text::api_key=kept-because-model-visible"
    raw_dir = tmp_path / "raw-api"
    raw_dir.mkdir()
    (raw_dir / "001.request.json").write_text(
        json.dumps(
            {
                "system": f"raw-system::{marker}",
                "messages": [{"role": "user", "content": marker}],
                "tools": [
                    {
                        "name": "mcp__example__lookup",
                        "input_schema": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (raw_dir / "001.response.json").write_text(
        json.dumps({"content": [{"type": "text", "text": marker}]}),
        encoding="utf-8",
    )
    recorder = RunAuditRecorder(
        _context(marker),
        system_prompt=f"built-system::{marker}",
        raw_api_dir=raw_dir,
        permission_snapshot={"allowed_tools": ["mcp__example__lookup"]},
    )
    recorder.observe_message(
        {
            "type": "system",
            "subtype": "init",
            "data": {"tools": ["mcp__example__lookup"]},
        }
    )
    recorder.observe_message(
        {
            "type": "assistant",
            "message": {
                "id": "message-1",
                "model": "claude-test",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cache_creation_input_tokens": 10,
                    "cache_read_input_tokens": 30,
                },
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "mcp__example__lookup",
                        "input": {"query": marker},
                    }
                ],
            },
        }
    )
    recorder.observe_message(
        {
            "type": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool-1",
                    "content": f"tool-result::{marker}",
                }
            ],
        }
    )
    recorder.observe_message(
        {
            "type": "result",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_creation_input_tokens": 10,
                "cache_read_input_tokens": 30,
            },
            "total_cost_usd": 0.123,
            "num_turns": 1,
        }
    )

    audit = recorder.finalize(status="SUCCEEDED", final_answer=marker)

    serialized = json.dumps(audit, ensure_ascii=False)
    assert marker in serialized
    assert audit["system_prompt"] == f"built-system::{marker}"
    assert all("rendered_text" not in item for item in audit["context_manifest"]["sources"])
    session_source = next(
        item
        for item in audit["context_manifest"]["sources"]
        if item["source_type"] == "retrieved_context" and item["name"] == "session"
    )
    assert session_source["content"] == f"session::{marker}"
    assert session_source["character_count"] == len(f"session::{marker}")
    assert audit["api_requests"][0]["body"]["messages"][0]["content"] == marker
    assert audit["api_responses"][0]["body"]["content"][0]["text"] == marker
    assert audit["tool_executions"][0]["input"]["query"] == marker
    assert audit["tool_executions"][0]["output"] == f"tool-result::{marker}"
    assert audit["summary"] == {
        "model_request_count": 1,
        "max_request_context_tokens": 140,
        "cumulative_input_tokens": 100,
        "cumulative_output_tokens": 20,
        "cache_creation_input_tokens": 10,
        "cache_read_input_tokens": 30,
        "total_cost_usd": 0.123,
        "registered_tool_count": 1,
        "max_loaded_tool_count": 1,
        "auto_approved_tool_count": 1,
        "tool_call_count": 1,
        "distinct_tool_count": 1,
    }
    assert any(
        item.get("source") == "raw_api_request"
        and item["definition"]["input_schema"]["properties"]["query"] == {"type": "string"}
        for item in audit["tool_definitions"]
    )


def test_recorder_drains_completed_raw_api_files_within_tmp_budget(
    tmp_path: Path,
) -> None:
    sandbox = JobSandboxManager(tmp_path / "sandboxes").create("job-audit-budget")
    try:
        raw_dir = sandbox.path / "tmp" / "raw-api"
        raw_dir.mkdir(parents=True)
        recorder = RunAuditRecorder(
            _context("budget"),
            system_prompt="built-system::budget",
            raw_api_dir=raw_dir,
            permission_snapshot={"allowed_tools": []},
        )

        for index in range(10):
            (raw_dir / "current.request.json").write_text(
                json.dumps({"messages": [{"index": index}], "tools": []}),
                encoding="utf-8",
            )
            (raw_dir / "current.response.json").write_text(
                json.dumps({"content": [{"index": index}]}),
                encoding="utf-8",
            )
            recorder.observe_message(
                {"type": "system", "subtype": "progress", "data": {"index": index}}
            )
            sandbox.assert_within_limits()

        assert list(raw_dir.rglob("*.json")) == []
        audit = recorder.finalize(status="SUCCEEDED")
        assert len(audit["api_requests"]) == 10
        assert len(audit["api_responses"]) == 10
        assert len(audit["usage"]["raw_api_request_metrics"]) == 10
        assert audit["summary"]["model_request_count"] == 10
    finally:
        sandbox.cleanup()


def test_audit_chunks_round_trip_complete_unicode_and_detect_tampering() -> None:
    audit = {
        "system_prompt": "完整提示词" * 20_000,
        "tool_executions": [{"output": "完整工具结果" * 10_000}],
    }

    digest, chunks = encode_audit_chunks(audit)

    assert len(chunks) > 1
    assert (
        decode_audit_chunks(
            chunks,
            expected_sha256=digest,
            expected_count=len(chunks),
        )
        == audit
    )

    tampered = [dict(item) for item in chunks]
    tampered[0]["content"] = tampered[0]["content"][:-4] + "AAAA"
    with pytest.raises(ValueError, match="digest"):
        decode_audit_chunks(
            tampered,
            expected_sha256=digest,
            expected_count=len(tampered),
        )
