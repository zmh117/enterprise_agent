from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.agent.domain.runtime import AgentExecutionContext, McpRuntimeBinding
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
