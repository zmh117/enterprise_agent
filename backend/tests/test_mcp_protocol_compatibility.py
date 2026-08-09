from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from services.mcp_common import McpTokenIssuer


ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=1)
            raise AssertionError(f"MCP v2 server exited early: {stdout}\n{stderr}")
        try:
            with httpx.Client(timeout=0.5, trust_env=False) as client:
                if client.get(url).status_code == 200:
                    return
        except httpx.HTTPError:
            time.sleep(0.05)
    raise AssertionError("MCP v2 server did not become healthy")


@pytest.mark.integration
def test_mcp_v1_client_negotiates_with_v2_server(tmp_path: Path) -> None:
    v2_python = os.environ.get("MCP_V2_PYTHON", "").strip()
    if not v2_python:
        pytest.skip("set MCP_V2_PYTHON to an isolated environment containing mcp==2.0.0")
    key = b"protocol-test-mcp-key-at-least-32-bytes"
    key_path = tmp_path / "mcp-token.key"
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    token = McpTokenIssuer(key).issue(
        audience="ones-mcp",
        app_user_id="user-protocol-test",
        job_id="job-protocol-test",
        application_publication_id="publication-protocol-test",
        scopes=["ones.work_items.search"],
        job_timeout_seconds=60,
    )
    port = _free_port()
    environment = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "MCP_TOKEN_SIGNING_KEY_FILE": str(key_path),
        "ONES_MCP_HOST": "127.0.0.1",
        "ONES_MCP_PORT": str(port),
    }
    process = subprocess.Popen(
        [v2_python, "-m", "backend.tests.mcp_v2_protocol_server"],
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_health(f"http://127.0.0.1:{port}/health", process)

        async def run_client() -> tuple[tuple[str, ...], dict[str, object]]:
            async with httpx.AsyncClient(
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
                trust_env=False,
            ) as http_client:
                async with streamable_http_client(
                    f"http://127.0.0.1:{port}/mcp",
                    http_client=http_client,
                ) as (read_stream, write_stream, _):
                    async with ClientSession(read_stream, write_stream) as session:
                        result = await session.initialize()
                        assert result.serverInfo.version == "0.1.0"
                        tools = await session.list_tools()
                        return (
                            tuple(tool.name for tool in tools.tools),
                            dict(tools.tools[0].inputSchema),
                        )

        names, input_schema = asyncio.run(run_client())
        assert names == ("ones_work_item_search",)
        properties = input_schema["properties"]
        assert set(properties) == {"keyword", "issue_type", "limit"}
        assert not {
            "context",
            "principal",
            "job",
            "user_id",
            "team_id",
            "credential_ref",
            "resource_revision_id",
        } & set(properties)
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.integration
def test_data_mcp_v2_tool_registry_has_no_identity_connection_or_executor_inputs() -> None:
    v2_python = os.environ.get("MCP_V2_PYTHON", "").strip()
    if not v2_python:
        pytest.skip("set MCP_V2_PYTHON to an isolated environment containing mcp==2.0.0")
    completed = subprocess.run(
        [v2_python, "-m", "backend.tests.mcp_v2_schema_probe"],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        text=True,
        capture_output=True,
        timeout=15,
        check=True,
    )
    schemas = __import__("json").loads(completed.stdout)
    assert set(schemas) == {
        "data_schema_directory",
        "data_describe_table",
        "data_sample_rows",
        "redis_get",
        "redis_scan_prefix",
        "loki_search",
    }
    forbidden = {
        "context",
        "principal",
        "job",
        "user_id",
        "team_id",
        "resource_code",
        "resource_revision_id",
        "credential_ref",
        "host",
        "port",
        "username",
        "password",
        "sql",
        "logql",
        "command",
    }
    for schema in schemas.values():
        assert not forbidden & set(schema["properties"])
