from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from mcp import ClientSession, types
from mcp.client._memory import InMemoryTransport
import pytest

from app.modules.agent.domain.runtime import (
    AgentExecutionContext,
    AgentRunRequest,
    McpRuntimeBinding,
)
from app.modules.model_connection.domain import ModelRuntimeBinding
from app.python_runtime.claude_client import ClaudeSdk, load_claude_agent_sdk
from app.python_runtime.file_mcp_bridge import (
    ClaudePythonFileBridge,
    PreparedFileMaterialization,
)
from app.python_runtime.file_transfer import FileUploadReceipt
from app.python_runtime.job_sandbox import JobSandboxLimits, JobSandboxManager
from app.python_runtime.mcp_config import FixedMcpClaudeSdkClient
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import test_settings as build_settings


SOURCE = b"initial Python Runtime TXT"


def _behavior(value: Any) -> str | None:
    return value.get("behavior") if isinstance(value, dict) else getattr(value, "behavior", None)


class _RemoteFileSession:
    def __init__(self) -> None:
        self.calls = 0
        self.read_timeouts: list[object] = []

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        **kwargs: Any,
    ) -> types.CallToolResult:
        self.calls += 1
        self.read_timeouts.append(kwargs.get("read_timeout_seconds"))
        if name == "file_prepare_materialization":
            control = {
                "protocol": "enterprise-agent.file-transfer/v1",
                "action": "MATERIALIZE",
                "transfer_id": "transfer-python-1",
                "sandbox_entry_handle": "sandbox-entry-python-1",
                "relative_path": "inputs/source-python.txt",
                "expected_size_bytes": len(SOURCE),
                "expected_sha256": hashlib.sha256(SOURCE).hexdigest(),
            }
        else:
            assert name == "file_create_commit_intent"
            control = {
                "protocol": "enterprise-agent.file-transfer/v1",
                "action": "UPLOAD_COMMIT",
                "commit_id": f"commit-python-{self.calls}",
                "sandbox_entry_handle": arguments["sandbox_entry_handle"],
            }
        return types.CallToolResult(
            content=[types.TextContent(type="text", text='{"status":"PREPARED"}')],
            meta={
                "enterprise-agent/mcp-call-id": f"mcp-call-python-{self.calls}",
                "enterprise-agent/agent-tool-call-id": (f"persisted-call-python-{self.calls}"),
                "enterprise-agent/file-transfer": control,
            },
        )


class _TransferPort:
    def __init__(self) -> None:
        self.uploaded: list[bytes] = []

    def download(self, **_kwargs: Any) -> list[bytes]:
        return [SOURCE]

    def upload(self, *, content: Any, **_kwargs: Any) -> FileUploadReceipt:
        body = b"".join(content)
        self.uploaded.append(body)
        return FileUploadReceipt(
            file_id=f"file-python-{len(self.uploaded)}",
            version_id=f"version-python-{len(self.uploaded)}",
            size_bytes=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
            status="COMMITTED",
            delivery_id="",
            delivery_status="NOT_REQUESTED",
        )


def test_real_python_runtime_sdk_loop_uses_local_file_bridge_before_model_result(
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}
    remote = _RemoteFileSession()
    transfer = _TransferPort()
    real_sdk = load_claude_agent_sdk()

    async def query(
        *,
        prompt: Any,
        options: dict[str, Any],
        **_kwargs: Any,
    ) -> Any:
        captured.update(options)
        assert not isinstance(prompt, str)
        captured["streamed_prompt"] = [item async for item in prompt]
        config = options["mcp_servers"]["file_service"]
        instance = config["instance"] if isinstance(config, dict) else config.instance
        async with InMemoryTransport(instance) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                descriptions = {
                    tool.name: tool.description for tool in (await session.list_tools()).tools
                }
                select_description = descriptions["select_sandbox_output"] or ""
                assert "文件持久化步骤1/2" in select_description
                assert "宿主机是Windows" in select_description
                assert "返回SELECTED只表示" in select_description
                assert "必须继续调用file_create_commit_intent" in select_description
                sandbox = Path(options["cwd"])
                materialized_path = sandbox / "inputs/source-python.txt"
                assert materialized_path.read_bytes() == SOURCE
                assert options["permission_mode"] == "default"
                assert options["allowed_tools"] == []
                assert "inputs/source-python.txt" in options["system_prompt"]
                assert "2026-08-15T21:30:00+08:00" in options["system_prompt"]
                assert SOURCE.decode() not in options["system_prompt"]

                assert (
                    _behavior(
                        await options["can_use_tool"](
                            "Edit",
                            {
                                "file_path": "inputs/source-python.txt",
                                "old_string": SOURCE.decode(),
                                "new_string": "edited Python Runtime TXT",
                            },
                            object(),
                        )
                    )
                    == "allow"
                )
                materialized_path.write_text("edited Python Runtime TXT", encoding="utf-8")
                commit_arguments = {
                    "sandbox_entry_handle": "sandbox-entry-python-1",
                    "file_id": "file-python-1",
                    "base_version_id": "version-python-0",
                    "display_name": "source-python.txt",
                    "user_intent": "MODIFY",
                    "delivery_mode": "WORKSPACE_ONLY",
                }
                assert (
                    _behavior(
                        await options["can_use_tool"](
                            "mcp__file_service__file_create_commit_intent",
                            commit_arguments,
                            object(),
                        )
                    )
                    == "allow"
                )
                committed = await session.call_tool("file_create_commit_intent", commit_arguments)
                assert transfer.uploaded[0] == b"edited Python Runtime TXT"

                output = sandbox / "outputs/generated.txt"
                output.write_text("generated Python Runtime TXT", encoding="utf-8")
                assert (
                    _behavior(
                        await options["can_use_tool"](
                            "mcp__file_service__select_sandbox_output",
                            {"relative_path": "outputs/generated.txt"},
                            object(),
                        )
                    )
                    == "allow"
                )
                selected = await session.call_tool(
                    "select_sandbox_output",
                    {"relative_path": "outputs/generated.txt"},
                )
                selected_payload = json.loads(selected.content[0].text)  # type: ignore[union-attr]
                selected_handle = selected_payload["runtime_file_bridge"]["sandbox_entry_handle"]
                generated_arguments = {
                    "sandbox_entry_handle": selected_handle,
                    "display_name": "generated.txt",
                    "user_intent": "GENERATE",
                    "delivery_mode": "DEFAULT",
                }
                generated = await session.call_tool(
                    "file_create_commit_intent", generated_arguments
                )
                assert transfer.uploaded[1] == b"generated Python Runtime TXT"

                for tool_use_id, name, result in (
                    (
                        "tool-python-commit",
                        "mcp__file_service__file_create_commit_intent",
                        committed,
                    ),
                    (
                        "tool-python-select",
                        "mcp__file_service__select_sandbox_output",
                        selected,
                    ),
                    (
                        "tool-python-generated",
                        "mcp__file_service__file_create_commit_intent",
                        generated,
                    ),
                ):
                    yield {
                        "type": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": tool_use_id,
                                "name": name,
                                "input": {},
                            }
                        ],
                    }
                    yield {
                        "type": "user",
                        "tool_use_result": result.model_dump(by_alias=True, exclude_none=True),
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": result.model_dump(by_alias=True, exclude_none=True)[
                                    "content"
                                ],
                                "is_error": result.is_error,
                            }
                        ],
                    }
        yield {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "python runtime file bridge complete",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    sdk = ClaudeSdk(
        query=query,
        options=lambda **kwargs: kwargs,
        tool=real_sdk.tool,
        create_sdk_mcp_server=real_sdk.create_sdk_mcp_server,
        tool_annotations=real_sdk.tool_annotations,
        permission_allow=real_sdk.permission_allow,
        permission_deny=real_sdk.permission_deny,
    )

    def bridge_factory(**kwargs: Any) -> ClaudePythonFileBridge:
        return ClaudePythonFileBridge(
            **kwargs,
            remote_session=remote,
            transfer_port=transfer,
        )

    binding = ModelRuntimeBinding(
        protocol="anthropic_compatible",
        base_url="https://model.invalid/anthropic",
        model="test-model",
        default_opus_model="test-model",
        default_sonnet_model="test-model",
        default_haiku_model="test-model",
        subagent_model="test-model",
        effort_level="max",
        secret_ref="secret://not-projected",
    )
    context = AgentExecutionContext(
        system_role="task file agent",
        safety_rules=["sandbox only"],
        user_question="edit and generate TXT",
        project_code="project-1",
        allowed_tools=[],
        tool_restrictions=["TXT only"],
        skills={},
        retrieved_context={
            "file_manifest": {
                "schema_version": 5,
                "workspace_catalog_revision_id": "workspace-catalog-python-1",
                "manifest_hash": "c" * 64,
                "observed_at": "2026-08-15T22:00:00+08:00",
                "items": [
                    {
                        "file_id": "file-python-1",
                        "version_id": "version-python-0",
                        "display_name": "source-python.txt",
                        "format_code": "TXT",
                        "source_kind": "CURRENT_MESSAGE",
                        "allowed_actions": [
                            "READ_METADATA",
                            "MATERIALIZE",
                            "EDIT",
                            "COMMIT",
                        ],
                        "auto_materialize": True,
                        "conflict_candidate": False,
                        "source_received_at": "2026-08-15T21:30:00+08:00",
                        "version_created_at": "2026-08-15T21:30:03+08:00",
                        "materialization_size_bytes": 7,
                    }
                ],
            }
        },
        conversation_summary="",
        publication_id="agent-publication-1",
        application_publication_id="application-publication-1",
        model_runtime_binding=binding,
        mcp_bindings=(
            McpRuntimeBinding(
                server_code="file-service",
                tool_name="file_prepare_materialization",
                required_scope="mcp:file-service:file_prepare_materialization:invoke",
                tool_schema_hash="a" * 64,
            ),
            McpRuntimeBinding(
                server_code="file-service",
                tool_name="file_create_commit_intent",
                required_scope="mcp:file-service:file_create_commit_intent:invoke",
                tool_schema_hash="b" * 64,
            ),
        ),
        max_tool_calls=8,
        runtime_protocol_version="1.3",
    )
    principal = "test-only-python-file-principal"
    client = FixedMcpClaudeSdkClient(
        limits=build_settings().execution,
        api_key="test-only-model-secret",
        mcp_server_url="http://tool-mcp:9103/mcp",
        file_mcp_server_url="http://file-service:9105/mcp",
        file_principal_token=principal,
        sandbox_manager=JobSandboxManager(tmp_path / "sandboxes"),
        file_bridge_factory=bridge_factory,
    )
    client.sdk_loader = lambda: sdk

    result = client.run(
        AgentRunRequest(
            job_id="job-python-file-bridge",
            user_id="app-user-1",
            project_code="project-1",
            invocation_id="invocation-python-file-bridge",
            context=context,
        )
    )

    assert result.final_answer == "python runtime file bridge complete"
    assert captured["streamed_prompt"] == [
        {
            "type": "user",
            "session_id": "",
            "message": {"role": "user", "content": "edit and generate TXT"},
            "parent_tool_use_id": None,
        }
    ]
    assert remote.read_timeouts == [300.0, 300.0, 300.0]
    assert len(transfer.uploaded) == 2
    assert not Path(captured["cwd"]).exists()
    serialized_events = json.dumps(result.tool_events, ensure_ascii=False)
    assert SOURCE.decode() not in serialized_events
    assert principal not in serialized_events


def test_python_runtime_reserves_all_automatic_inputs_before_first_download(
    tmp_path: Path,
) -> None:
    bridge_state: dict[str, Any] = {
        "prepared": [],
        "materialized": [],
        "closed": False,
    }

    async def query(**_kwargs: Any) -> Any:
        raise AssertionError("model query must not run after Sandbox preflight rejection")
        yield  # pragma: no cover

    sdk = ClaudeSdk(
        query=query,
        options=lambda **kwargs: kwargs,
        tool=None,
        create_sdk_mcp_server=None,
        tool_annotations=None,
    )

    class FakePreparedBridge:
        server = {"type": "sdk", "name": "enterprise-file-bridge"}
        local_tool_names: tuple[str, ...] = ()

        async def connect(self) -> None:
            return None

        async def close(self) -> None:
            bridge_state["closed"] = True

        async def prepare_materialization(
            self,
            *,
            file_id: str,
            version_id: str,
        ) -> PreparedFileMaterialization:
            bridge_state["prepared"].append((file_id, version_id))
            return PreparedFileMaterialization(
                file_id=file_id,
                version_id=version_id,
                expected_size_bytes=8 * 1024 * 1024,
                control_result={},
            )

        async def materialize_prepared(
            self,
            prepared: PreparedFileMaterialization,
        ) -> dict[str, Any]:
            bridge_state["materialized"].append((prepared.file_id, prepared.version_id))
            raise AssertionError("download must not start before the full batch is reserved")

    def bridge_factory(**_kwargs: Any) -> FakePreparedBridge:
        return FakePreparedBridge()

    binding = ModelRuntimeBinding(
        protocol="anthropic_compatible",
        base_url="https://model.invalid/anthropic",
        model="test-model",
        default_opus_model="test-model",
        default_sonnet_model="test-model",
        default_haiku_model="test-model",
        subagent_model="test-model",
        effort_level="max",
        secret_ref="secret://not-projected",
    )
    items = [
        {
            "file_id": f"file-{index}",
            "version_id": f"version-{index}",
            "display_name": f"source-{index}.txt",
            "format_code": "TXT",
            "source_kind": "CURRENT_MESSAGE",
            "allowed_actions": ["READ_METADATA", "MATERIALIZE"],
            "auto_materialize": True,
            "conflict_candidate": False,
            "source_received_at": "2026-08-22T02:26:30+00:00",
            "version_created_at": "2026-08-22T02:26:31+00:00",
            "materialization_size_bytes": 7,
        }
        for index in (1, 2)
    ]
    context = AgentExecutionContext(
        system_role="task file agent",
        safety_rules=["sandbox only"],
        user_question="read both files",
        project_code="project-1",
        allowed_tools=[],
        tool_restrictions=["bounded"],
        skills={},
        retrieved_context={
            "file_manifest": {
                "schema_version": 5,
                "workspace_catalog_revision_id": "workspace-catalog-python-2",
                "manifest_hash": "d" * 64,
                "observed_at": "2026-08-22T02:26:33+00:00",
                "items": items,
            }
        },
        conversation_summary="",
        publication_id="agent-publication-1",
        application_publication_id="application-publication-1",
        model_runtime_binding=binding,
        mcp_bindings=(
            McpRuntimeBinding(
                server_code="file-service",
                tool_name="file_prepare_materialization",
                required_scope="mcp:file-service:file_prepare_materialization:invoke",
                tool_schema_hash="a" * 64,
            ),
        ),
        runtime_protocol_version="1.3",
    )
    sandbox_limits = JobSandboxLimits(
        capacity_bytes=15 * 1024 * 1024,
        max_file_bytes=15 * 1024 * 1024,
        max_files=64,
        max_input_files=40,
        max_work_output_files=16,
        max_tmp_files=8,
    )
    client = FixedMcpClaudeSdkClient(
        limits=build_settings().execution,
        api_key="test-only-model-secret",
        mcp_server_url="http://tool-mcp:9103/mcp",
        file_mcp_server_url="http://file-service:9105/mcp",
        file_principal_token="test-only-file-principal",
        sandbox_manager=JobSandboxManager(
            tmp_path / "sandboxes",
            limits=sandbox_limits,
        ),
        file_bridge_factory=bridge_factory,
    )
    client.sdk_loader = lambda: sdk

    with pytest.raises(NonRetryableExecutionError) as captured:
        client.run(
            AgentRunRequest(
                job_id="job-batch-preflight",
                user_id="app-user-1",
                project_code="project-1",
                invocation_id="invocation-batch-preflight",
                context=context,
            )
        )

    assert captured.value.error_code == "file_auto_materialization_preflight_failed"
    assert bridge_state["prepared"] == [
        ("file-1", "version-1"),
        ("file-2", "version-2"),
    ]
    assert bridge_state["materialized"] == []
    assert bridge_state["closed"] is True
    assert list((tmp_path / "sandboxes").iterdir()) == []
