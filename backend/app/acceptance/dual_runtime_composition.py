from __future__ import annotations

import json
import os
from pathlib import Path
import re
import time
import uuid
from typing import Any

import yaml

from app.bootstrap import Container, build_api_container
from app.modules.identity.infrastructure.external_identity_credentials import (
    CredentialSecretBundle,
)
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
)
from app.modules.job.domain.job_status import JobStatus
from app.modules.job.infrastructure.repositories import now_iso
from app.modules.platform_config.infrastructure import PlatformConfigRepository
from app.shared.config import load_settings
from app.shared.exceptions import NotFound


ACTOR_USERNAME = "admin"
ACTOR_ID = ""
AGENTS = {
    "python-v1": "default-diagnostic-agent",
    "typescript-v1": "typescript-diagnostic-agent",
}
TERMINAL_DELIVERY_STATUSES = {"SUCCEEDED", "FAILED", "DEAD", "SKIPPED"}
TEST_SECRET_CANARY = "dual-runtime-acceptance-provider-secret-canary-v1"
REAL_API_KEY_ENV = "DUAL_RUNTIME_ACCEPTANCE_API_KEY"
REAL_MODEL = "deepseek-v4-pro[1m]"
READONLY_TOOL = "get_er_context"
ONES_TOOL = "ones_work_item_search"
ONES_MOCK_CONFIG_ENV = "ONES_MOCK_ACCEPTANCE_CONFIG"
STALE_ONES_TOKEN = "dual-runtime-acceptance-stale-ones-token"
RETRY_MARKER = "[acceptance:retry-once]"
REAL_ACTIONS = {
    "real-full",
    "create-real-cancel-job",
    "inspect-real-cancel-job",
}
_SQL_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def _configure_model_connection(
    runtime: Container,
    *,
    api_key: str = TEST_SECRET_CANARY,
    code: str = "default-deepseek-anthropic",
    model: str = "",
) -> dict[str, Any]:
    service = runtime.model_connection_service
    service.dns_resolver = lambda *_args, **_kwargs: [(2, 1, 6, "", ("8.8.8.8", 443))]
    try:
        current = service.get(code)
    except NotFound:
        current = service.repository.create_connection(
            code=code,
            name=f"Disposable dual Runtime acceptance {code}",
            protocol="anthropic_compatible",
            actor_id=ACTOR_ID,
        )
    selected_model = model or runtime.settings.claude_model
    return service.save_revision(
        actor_id=ACTOR_ID,
        code=code,
        expected_revision=int(current["revision"]),
        config={
            "protocol": "anthropic_compatible",
            "base_url": "https://api.deepseek.com/anthropic",
            "model": selected_model,
            "default_opus_model": selected_model,
            "default_sonnet_model": selected_model,
            "default_haiku_model": selected_model,
            "subagent_model": selected_model,
            "effort_level": "max",
        },
        api_key=api_key,
    )


def _publish_agent(
    runtime: Container,
    *,
    agent_code: str,
    connection_revision_id: str,
    mcp_tool_ids: tuple[str, ...] = (),
    business_instructions: str = "Return only the deterministic smoke result.",
    timeout_seconds: int = 20,
    max_turns: int = 2,
    model: str = "",
) -> dict[str, Any]:
    detail = runtime.agent_config_service.get(agent_code)
    config = dict(detail["draft"]["config"])
    config["business_role"] = "Isolated dual Runtime Compose acceptance Agent"
    config["business_instructions"] = business_instructions
    config["model_policy"] = {
        "runtime": "claude_agent_sdk",
        "model": model or runtime.settings.claude_model,
        "model_connection_revision_id": connection_revision_id,
    }
    config["execution"] = {
        "max_turns": max_turns,
        "timeout_seconds": timeout_seconds,
    }
    config["mcp_tool_ids"] = list(mcp_tool_ids)
    config["skills"] = []
    config["channels"] = {"ingress": [], "delivery": []}
    revision = runtime.agent_config_service.save_draft(
        actor_id=ACTOR_ID,
        agent_code=agent_code,
        expected_revision=int(detail["draft"]["revision"]),
        config=config,
    )
    return runtime.agent_config_service.publish(
        actor_id=ACTOR_ID,
        agent_code=agent_code,
        revision_id=str(revision["id"]),
    )


def _activate_application(
    runtime: Container,
    *,
    code: str,
    agent_publication_id: str,
    mcp_tool_ids: tuple[str, ...] = (),
    timeout_seconds: int = 20,
    max_turns: int = 2,
    max_tool_calls: int = 0,
) -> dict[str, Any]:
    application = runtime.business_application_service.create(
        actor_id=ACTOR_ID,
        code=code,
        name=code,
        description="Isolated dual Runtime Compose acceptance",
        project_code="default",
        owner_user_id=ACTOR_ID,
    )
    role = runtime.authorization_center_service.create_role(
        actor_id=ACTOR_ID,
        code=f"{code}-runtime-user",
        name=f"{code}-runtime-user",
        description="Explicit isolated Compose acceptance access",
        purpose_tags=["业务运行"],
    )["role"]
    revision = runtime.business_application_service.save_draft(
        actor_id=ACTOR_ID,
        code=code,
        expected_revision=int(application["revision"]),
        payload={
            "agent_publication_id": agent_publication_id,
            "workflow_publication_id": "",
            "session_policy": {
                "conversation_mode": "channel",
                "recent_message_limit": 20,
                "retention_days": 1,
                "continuous_conversation_enabled": False,
                "attachments_enabled": False,
            },
            "execution_policy": {
                "max_turns": max_turns,
                "timeout_seconds": timeout_seconds,
                "max_tool_calls": max_tool_calls,
            },
            "triggers": [],
            "deliveries": [],
            "mcp_tools": list(mcp_tool_ids),
        },
    )
    publication = runtime.business_application_service.publish(
        actor_id=ACTOR_ID,
        code=code,
        revision_id=str(revision["id"]),
    )
    runtime.business_application_service.activate(
        actor_id=ACTOR_ID,
        code=code,
        environment="local",
        publication_id=str(publication["id"]),
        expected_revision=0,
    )
    scopes: list[dict[str, str]] = []
    if mcp_tool_ids:
        environment = PlatformConfigRepository(runtime.database).upsert_environment(
            code="acceptance",
            display_name="Isolated acceptance environment",
        )
        scopes = [{"environment_id": str(environment["id"])}]
    runtime.authorization_center_service.replace_business_access(
        actor_id=ACTOR_ID,
        role_id=str(role["id"]),
        expected_revision=1,
        applications=[
            {
                "application_id": str(application["id"]),
                "tool_identifiers": list(mcp_tool_ids),
                "scopes": scopes,
            }
        ],
        confirmed=True,
        reason="隔离双 Runtime Compose 验收",
    )
    runtime.identity_repository.assign_role(
        user_id=ACTOR_ID,
        role_id=str(role["id"]),
        assigned_by=ACTOR_ID,
    )
    return runtime.business_application_resolver.resolve_active(code, "local")


def _prepare_real_runtime(
    runtime: Container,
    runtime_kinds: tuple[str, ...],
    *,
    api_key: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    connection = _configure_model_connection(
        runtime,
        api_key=api_key,
        model=REAL_MODEL,
    )
    mcp_tool_ids = (READONLY_TOOL,)
    suffix = uuid.uuid4().hex[:8]
    publications: dict[str, dict[str, Any]] = {}
    applications: dict[str, dict[str, Any]] = {}
    for runtime_kind in runtime_kinds:
        agent_code = AGENTS[runtime_kind]
        publication = _publish_agent(
            runtime,
            agent_code=agent_code,
            connection_revision_id=str(connection["id"]),
            mcp_tool_ids=mcp_tool_ids,
            business_instructions=(
                "This is a disposable acceptance run. Follow the user request exactly, "
                "use only the published read-only MCP tool when requested, and keep the "
                "answer concise. If the request names a Tool, the first action MUST be that "
                "Tool call. A text-only answer or a claim of Tool success without an actual "
                "Tool result is invalid."
            ),
            timeout_seconds=180,
            max_turns=6,
            model=REAL_MODEL,
        )
        publications[runtime_kind] = {**publication, "agent_code": agent_code}
        applications[runtime_kind] = _activate_application(
            runtime,
            code=f"dual-real-{runtime_kind.split('-')[0]}-{suffix}",
            agent_publication_id=str(publication["id"]),
            mcp_tool_ids=mcp_tool_ids,
            timeout_seconds=180,
            max_turns=6,
            max_tool_calls=4,
        )
    return publications, applications


def _prepare_mcp_runtime(
    runtime: Container,
    runtime_kinds: tuple[str, ...],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    tuple[str, ...],
]:
    sensitive_values = _configure_ones_mock_identity(runtime)
    connection = _configure_model_connection(runtime, code="mcp-acceptance-deepseek")
    mcp_tool_ids = (READONLY_TOOL, ONES_TOOL)
    suffix = uuid.uuid4().hex[:8]
    publications: dict[str, dict[str, Any]] = {}
    applications: dict[str, dict[str, Any]] = {}
    for runtime_kind in runtime_kinds:
        agent_code = AGENTS[runtime_kind]
        publication = _publish_agent(
            runtime,
            agent_code=agent_code,
            connection_revision_id=str(connection["id"]),
            mcp_tool_ids=mcp_tool_ids,
            business_instructions="Run only the deterministic MCP acceptance Tool.",
            timeout_seconds=60,
            max_turns=4,
        )
        publications[runtime_kind] = {**publication, "agent_code": agent_code}
        applications[runtime_kind] = _activate_application(
            runtime,
            code=f"dual-mcp-{runtime_kind.split('-')[0]}-{suffix}",
            agent_publication_id=str(publication["id"]),
            mcp_tool_ids=mcp_tool_ids,
            timeout_seconds=60,
            max_turns=4,
            max_tool_calls=8,
        )
    return publications, applications, sensitive_values


def _configure_ones_mock_identity(runtime: Container) -> tuple[str, ...]:
    config_path = Path(os.getenv(ONES_MOCK_CONFIG_ENV, ""))
    if not config_path.is_file() or config_path.stat().st_size > 64 * 1024:
        raise RuntimeError("ONES mock acceptance config is missing or too large")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("ONES mock acceptance config is invalid")
    users = raw.get("users")
    team = raw.get("team")
    if not isinstance(users, list) or not users or not isinstance(users[0], dict):
        raise RuntimeError("ONES mock acceptance user is invalid")
    if not isinstance(team, dict):
        raise RuntimeError("ONES mock acceptance Team is invalid")
    primary = users[0]

    def required(mapping: dict[str, Any], key: str) -> str:
        value = str(mapping.get(key) or "").strip()
        if not value:
            raise RuntimeError("ONES mock acceptance field is missing")
        return value

    email = required(primary, "email")
    password = required(primary, "password")
    provider_user_id = required(primary, "uuid")
    display_name = required(primary, "name")
    provider_token = required(primary, "token")
    team_id = required(team, "uuid")
    team_name = required(team, "name")
    identity = runtime.identity_repository.bind_external_identity(
        user_id=ACTOR_ID,
        provider="ones",
        tenant_code="default",
        external_subject_id=provider_user_id,
        connector_id="",
        display_name=display_name,
        metadata={
            "team_uuids": [team_id],
            "teams": [{"id": team_id, "name": team_name}],
            "default_team_id": team_id,
        },
    )
    credentials = runtime.external_identity_credential_repository
    if credentials is None:
        raise RuntimeError("ONES credential repository is unavailable")
    credentials.upsert_active(
        external_identity_id=str(identity["id"]),
        provider="ones",
        secrets=CredentialSecretBundle(
            email=email,
            password=password,
            token=STALE_ONES_TOKEN,
        ),
        verified_at=now_iso(),
    )
    return password, provider_token, STALE_ONES_TOKEN


def _create_job(
    runtime: Container,
    *,
    label: str,
    question: str,
    agent: dict[str, Any],
    application: dict[str, Any],
    routing_context: dict[str, str] | None = None,
) -> str:
    app = dict(application["application"])
    deployment = dict(application["deployment"])
    publication = dict(application["publication"])
    snapshot = dict(publication["snapshot"])
    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key=f"dual-runtime-compose-{label}-{uuid.uuid4().hex}",
            requester_id=ACTOR_ID,
            external_conversation_id=f"dual-runtime-compose-{label}",
            external_event_id=f"dual-runtime-compose-{label}-{uuid.uuid4().hex}",
            user_message=question,
            source_channel="debug_api",
            source_connector_id="connector-debug-api",
            project_code="default",
            routing_context={
                "project_code": "default",
                **(routing_context or {}),
            },
            reply_route={"type": "none", "connector_id": "", "target": {}},
            correlation_id=f"dual-runtime-compose-{label}",
            agent_code=str(agent["agent_code"]),
            fixed_agent_publication_id=str(agent["id"]),
            fixed_agent_revision=int(agent["revision"]),
            fixed_agent_config_hash=str(agent["config_hash"]),
            business_application_id=str(app["id"]),
            business_application_code=str(app["code"]),
            business_application_publication_id=str(publication["id"]),
            business_application_deployment_id=str(deployment["id"]),
            business_application_config_hash=str(publication["config_hash"]),
            business_application_runtime_status=str(application["runtime_status"]),
            business_application_route_decision={
                "resolution_outcome": "matched",
                "reason_code": "compose_acceptance",
            },
            conversation_mode="channel",
            continuous_conversation_enabled=False,
            session_policy=dict(snapshot["session_policy"]),
            application_execution_policy=dict(snapshot["execution_policy"]),
        )
    )
    return job.id


def _wait_for_job(
    runtime: Container,
    job_id: str,
    *,
    expected: JobStatus,
    timeout_seconds: int = 90,
) -> Any:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        job = runtime.agent_repository.get_job(job_id)
        if job.status == expected:
            return job
        if job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED}:
            raise RuntimeError(
                f"Job {job_id} reached {job.status.value}; expected {expected.value}"
            )
        time.sleep(0.5)
    raise TimeoutError(f"Job {job_id} did not reach {expected.value}")


def _wait_for_delivery(runtime: Container, job_id: str, timeout_seconds: int = 30) -> Any:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        event = runtime.agent_repository.get_delivery_event_for_job(job_id)
        if event and event.status.value in TERMINAL_DELIVERY_STATUSES:
            return event
        time.sleep(0.25)
    raise TimeoutError(f"Delivery for Job {job_id} did not become terminal")


def _assert_runtime_evidence(
    runtime: Container,
    *,
    job_id: str,
    runtime_kind: str,
) -> None:
    events = runtime.agent_repository.list_runtime_events(job_id)
    terminals = [item for item in events if item["event_type"] == "terminal"]
    if not terminals:
        raise RuntimeError(f"Job {job_id} has no persisted Runtime terminal")
    if any(
        item["payload"]["runtime_provenance"]["runtime_kind"] != runtime_kind for item in terminals
    ):
        raise RuntimeError(f"Job {job_id} Runtime provenance mismatch")


def _assert_mcp_evidence(
    runtime: Container,
    *,
    job_id: str,
    server_code: str,
    tool_name: str,
    expected_calls: int,
    require_refresh: bool = False,
) -> None:
    calls = [
        item
        for item in runtime.agent_repository.list_tool_calls(job_id)
        if item["tool_name"] == tool_name
    ]
    if len(calls) != expected_calls:
        raise RuntimeError(
            f"Job {job_id} has {len(calls)} {tool_name} calls; expected {expected_calls}"
        )
    if any(
        item["status"] != "SUCCEEDED"
        or item["tool_origin"] != "mcp"
        or item["server_code"] != server_code
        or item["persisted_by"] != "mcp_server"
        or not item["runtime_tool_call_id"]
        or not item["mcp_call_id"]
        for item in calls
    ):
        raise RuntimeError(f"Job {job_id} MCP Agent Tool Call evidence is incomplete")
    audits = runtime.database.execute(
        "select * from mcp_operation_audit where job_id = ? order by created_at, id",
        (job_id,),
    )
    roots = [item for item in audits if item["event_kind"] == "TOOL"]
    if len(roots) != expected_calls:
        raise RuntimeError(
            f"Job {job_id} has {len(roots)} MCP roots; expected {expected_calls}"
        )
    root_by_call = {str(item["mcp_call_id"]): item for item in roots}
    if len(root_by_call) != expected_calls:
        raise RuntimeError(f"Job {job_id} MCP root IDs are not unique")
    for call in calls:
        mcp_call_id = str(call["mcp_call_id"])
        root = root_by_call.get(mcp_call_id)
        linked = [item for item in audits if str(item["mcp_call_id"]) == mcp_call_id]
        if root is None or str(root["agent_tool_call_id"]) != str(call["id"]):
            raise RuntimeError(f"Job {job_id} MCP root did not link the exact Tool Call")
        if any(str(item["agent_tool_call_id"]) != str(call["id"]) for item in linked):
            raise RuntimeError(f"Job {job_id} MCP children crossed Tool Call roots")
        if any(
            item["event_kind"] != "TOOL" and str(item["parent_audit_id"]) != str(root["id"])
            for item in linked
        ):
            raise RuntimeError(f"Job {job_id} MCP child parent linkage is incomplete")
        event_kinds = {str(item["event_kind"]) for item in linked}
        required = {"TOOL", "AUTHORIZATION"}
        if server_code == "ones-mcp":
            required.add("PROVIDER")
        if not required.issubset(event_kinds):
            raise RuntimeError(f"Job {job_id} MCP evidence kinds are incomplete")
    if require_refresh:
        provider_attempts = {
            (int(item["attempt"]), str(item["status"]))
            for item in audits
            if item["event_kind"] == "PROVIDER"
        }
        if not {(0, "FAILED"), (1, "SUCCEEDED")}.issubset(provider_attempts):
            raise RuntimeError(f"Job {job_id} ONES refresh evidence is incomplete")
        if not any(item["event_kind"] == "CREDENTIAL" for item in audits):
            raise RuntimeError(f"Job {job_id} ONES credential refresh evidence is missing")


def _assert_mcp_online_invariants(
    runtime: Container,
    *,
    job_ids: list[str],
    sensitive_values: tuple[str, ...],
) -> None:
    placeholders = ",".join("?" for _ in job_ids)
    audits = runtime.database.execute(
        f"select * from mcp_operation_audit where job_id in ({placeholders})",
        tuple(job_ids),
    )
    if not audits:
        raise RuntimeError("MCP online invariant scan has no post-cutover evidence")
    if any(not item["agent_tool_call_id"] or not item["mcp_call_id"] for item in audits):
        raise RuntimeError("MCP online invariant scan found an empty exact link")
    evidence = json.dumps(audits, ensure_ascii=False)
    if any(value and value in evidence for value in sensitive_values):
        raise RuntimeError("MCP online invariant scan found authentication material")
    duplicate = runtime.database.execute_one(
        f"""
        select count(*) as count
          from (
            select mcp_call_id
              from mcp_operation_audit
             where job_id in ({placeholders}) and event_kind = 'TOOL'
             group by mcp_call_id
            having count(*) <> 1
          ) roots
        """,
        tuple(job_ids),
    )
    if duplicate is None or int(duplicate["count"]) != 0:
        raise RuntimeError("MCP online invariant scan found duplicate roots")


def _assert_sensitive_boundaries(runtime: Container, job_ids: list[str]) -> None:
    placeholders = ",".join("?" for _ in job_ids)
    persisted = runtime.database.execute(
        f"""
        select payload_json as value from agent_runtime_event
         where job_id in ({placeholders})
        union all
        select request_payload from agent_tool_call
         where job_id in ({placeholders})
        union all
        select response_summary from agent_tool_call
         where job_id in ({placeholders})
        union all
        select delivery_binding_json from delivery_outbox
         where job_id in ({placeholders})
        union all
        select target_summary from delivery_outbox
         where job_id in ({placeholders})
        union all
        select result from agent_job
         where id in ({placeholders})
        union all
        select error_message from agent_job
         where id in ({placeholders})
        union all
        select model_runtime_provenance_json from agent_job
         where id in ({placeholders})
        union all
        select events_json from agent_runtime_terminal_ledger
         where {" or ".join("invocation_id like ?" for _ in job_ids)}
        """,
        tuple(job_ids * 8 + [f"{job_id}.%" for job_id in job_ids]),
    )
    serialized = "\n".join(str(row["value"] or "") for row in persisted).lower()
    forbidden = (
        TEST_SECRET_CANARY,
        "authorization",
        "runtime_grant",
        "private reasoning",
        "[smoke:",
    )
    leaked = [value for value in forbidden if value in serialized]
    if leaked:
        raise RuntimeError(f"Sensitive persistence boundary failed: {leaked}")


def _real_api_key() -> str:
    value = os.getenv(REAL_API_KEY_ENV, "")
    if (
        not value.startswith("sk-")
        or not 20 <= len(value) <= 4000
        or value != value.strip()
        or any(character.isspace() for character in value)
    ):
        raise RuntimeError("real acceptance API key is missing or invalid")
    return value


def _assert_plaintext_secret_absent(runtime: Container, secret: str) -> None:
    columns = runtime.database.execute(
        """
        select table_name, column_name
          from information_schema.columns
         where table_schema = 'public'
           and data_type in ('character varying', 'character', 'text', 'json', 'jsonb')
         order by table_name, ordinal_position
        """
    )
    leaked_locations: list[str] = []
    for column in columns:
        table_name = str(column["table_name"])
        column_name = str(column["column_name"])
        if not _SQL_IDENTIFIER.fullmatch(table_name) or not _SQL_IDENTIFIER.fullmatch(column_name):
            raise RuntimeError("database metadata contains an unsafe SQL identifier")
        found = runtime.database.execute_one(
            f"select 1 as found from {table_name} "
            f"where position(? in cast({column_name} as text)) > 0 limit 1",
            (secret,),
        )
        if found is not None:
            leaked_locations.append(f"{table_name}.{column_name}")
    if leaked_locations:
        raise RuntimeError(
            "plaintext provider credential persisted in: " + ", ".join(leaked_locations)
        )


def _assert_real_tool_evidence(runtime: Container, job_id: str) -> None:
    calls = runtime.agent_repository.list_tool_calls(job_id)
    matching = [
        item
        for item in calls
        if item["tool_name"] == READONLY_TOOL and item["status"] == "SUCCEEDED"
    ]
    if not matching:
        raise RuntimeError(f"Job {job_id} did not complete the readonly MCP Tool")
    runtime_events = runtime.agent_repository.list_runtime_events(job_id)
    if not any(
        event["event_type"] == "tool_event"
        and event["payload"].get("server_code") == "tool-mcp"
        and event["payload"].get("tool_name") == READONLY_TOOL
        and event["payload"].get("status") == "SUCCEEDED"
        for event in runtime_events
    ):
        raise RuntimeError(f"Job {job_id} has no standard MCP Tool Runtime evidence")
    runtime.mcp_tool_snapshot_service.verify(job_id)


def _assert_retry_evidence(runtime: Container, job_id: str) -> None:
    job = runtime.agent_repository.get_job(job_id)
    if job.retry_count != 1:
        raise RuntimeError(f"Job {job_id} retry_count={job.retry_count}; expected 1")
    audit_types = {
        str(item["event_type"])
        for item in runtime.database.execute(
            "select event_type from audit_event where job_id = ?",
            (job_id,),
        )
    }
    required = {"job.retry.scheduled", "job.retry.released"}
    if not required.issubset(audit_types):
        raise RuntimeError(
            f"Job {job_id} retry audit evidence is incomplete: {sorted(audit_types)}"
        )


def _prepare_runtime(
    runtime: Container,
    runtime_kinds: tuple[str, ...],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    connection = _configure_model_connection(runtime)
    suffix = uuid.uuid4().hex[:8]
    publications: dict[str, dict[str, Any]] = {}
    applications: dict[str, dict[str, Any]] = {}
    for runtime_kind in runtime_kinds:
        agent_code = AGENTS[runtime_kind]
        publication = _publish_agent(
            runtime,
            agent_code=agent_code,
            connection_revision_id=str(connection["id"]),
        )
        publications[runtime_kind] = {**publication, "agent_code": agent_code}
        applications[runtime_kind] = _activate_application(
            runtime,
            code=f"dual-{runtime_kind.split('-')[0]}-{suffix}",
            agent_publication_id=str(publication["id"]),
        )
    return publications, applications


def _run_real_full(runtime: Container) -> int:
    api_key = _real_api_key()
    publications, applications = _prepare_real_runtime(
        runtime,
        tuple(AGENTS),
        api_key=api_key,
    )
    results: list[dict[str, Any]] = []
    job_ids: list[str] = []
    missing_tool_runtimes: list[str] = []
    for runtime_kind in AGENTS:
        tool_job_id = _create_job(
            runtime,
            label=f"real-tool-{runtime_kind}",
            question=(
                "这是 Tool-use 合规测试。你的第一个动作必须是调用且只调用一次已发布的 "
                "get_er_context MCP Tool，参数必须为 "
                '{"query":"enterprise agent acceptance"}。在收到 tool_result 前禁止输出'
                "文字或最终答案；收到后仅用一句中文说明只读工具调用成功。"
            ),
            agent=publications[runtime_kind],
            application=applications[runtime_kind],
        )
        job_ids.append(tool_job_id)
        tool_job = _wait_for_job(
            runtime,
            tool_job_id,
            expected=JobStatus.SUCCEEDED,
            timeout_seconds=240,
        )
        tool_delivery = _wait_for_delivery(runtime, tool_job_id, timeout_seconds=90)
        _assert_runtime_evidence(
            runtime,
            job_id=tool_job_id,
            runtime_kind=runtime_kind,
        )
        tool_status = "SUCCEEDED"
        try:
            _assert_real_tool_evidence(runtime, tool_job_id)
        except RuntimeError:
            tool_status = "MISSING"
            missing_tool_runtimes.append(runtime_kind)
        results.append(
            {
                "runtime_kind": runtime_kind,
                "scenario": "real_model_readonly_tool",
                "job_status": tool_job.status.value,
                "tool_status": tool_status,
                "delivery_status": tool_delivery.status.value,
            }
        )

        retry_job_id = _create_job(
            runtime,
            label=f"real-retry-{runtime_kind}",
            question=(f"{RETRY_MARKER} 这是隔离重试验收。不要调用工具，最终只回复 REAL_RETRY_OK。"),
            agent=publications[runtime_kind],
            application=applications[runtime_kind],
        )
        job_ids.append(retry_job_id)
        retry_job = _wait_for_job(
            runtime,
            retry_job_id,
            expected=JobStatus.SUCCEEDED,
            timeout_seconds=300,
        )
        retry_delivery = _wait_for_delivery(runtime, retry_job_id, timeout_seconds=90)
        _assert_runtime_evidence(
            runtime,
            job_id=retry_job_id,
            runtime_kind=runtime_kind,
        )
        _assert_retry_evidence(runtime, retry_job_id)
        results.append(
            {
                "runtime_kind": runtime_kind,
                "scenario": "job_retry_then_real_model",
                "job_status": retry_job.status.value,
                "retry_count": retry_job.retry_count,
                "delivery_status": retry_delivery.status.value,
            }
        )

    _assert_sensitive_boundaries(runtime, job_ids)
    _assert_plaintext_secret_absent(runtime, api_key)
    status = "failed" if missing_tool_runtimes else "passed"
    print(
        json.dumps(
            {
                "status": status,
                "missing_tool_runtimes": missing_tool_runtimes,
                "scenarios": results,
            },
            sort_keys=True,
        )
    )
    return 1 if missing_tool_runtimes else 0


def _create_real_cancel_job(runtime: Container) -> int:
    runtime_kind = os.getenv("DUAL_RUNTIME_ACCEPTANCE_RUNTIME_KIND", "").strip()
    if runtime_kind not in AGENTS:
        raise RuntimeError("real cancellation requires a supported Runtime kind")
    api_key = _real_api_key()
    publications, applications = _prepare_real_runtime(
        runtime,
        (runtime_kind,),
        api_key=api_key,
    )
    job_id = _create_job(
        runtime,
        label=f"real-cancel-{runtime_kind}",
        question=(
            "先调用 get_er_context 查询 enterprise agent acceptance，再撰写一份至少 "
            "3000 字、分 20 节的只读架构分析。在完整分析完成前不要给最终答案。"
        ),
        agent=publications[runtime_kind],
        application=applications[runtime_kind],
    )
    deadline = time.monotonic() + 180
    observed = False
    while time.monotonic() < deadline:
        job = runtime.agent_repository.get_job(job_id)
        claim = runtime.database.execute_one(
            """
            select count(*) as count
              from agent_runtime_invocation_claim
             where invocation_id like ?
            """,
            (f"{job_id}.%",),
        )
        prefix = runtime.database.execute_one(
            """
            select count(*) as count
              from agent_runtime_invocation_event
             where invocation_id like ?
            """,
            (f"{job_id}.%",),
        )
        if (
            job.status == JobStatus.RUNNING
            and claim
            and int(claim["count"]) == 1
            and prefix
            and int(prefix["count"]) >= 1
        ):
            observed = True
            break
        if job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED}:
            raise RuntimeError("real cancellation Job completed before cancel window")
        time.sleep(0.05)
    if not observed:
        raise TimeoutError("real cancellation Runtime execution was not observed")
    time.sleep(0.75)
    job = runtime.agent_repository.get_job(job_id)
    claim = runtime.database.execute_one(
        """
        select count(*) as count
          from agent_runtime_invocation_claim
         where invocation_id like ?
        """,
        (f"{job_id}.%",),
    )
    if job.status != JobStatus.RUNNING or not claim or int(claim["count"]) != 1:
        raise RuntimeError("real cancellation window closed before Worker shutdown")
    _assert_plaintext_secret_absent(runtime, api_key)
    print(
        json.dumps(
            {
                "status": "created",
                "runtime_kind": runtime_kind,
                "job_id": job_id,
                "execution_observed": True,
            },
            sort_keys=True,
        )
    )
    return 0


def _inspect_real_cancel_job(runtime: Container) -> int:
    job_id = os.getenv("DUAL_RUNTIME_ACCEPTANCE_JOB_ID", "").strip()
    runtime_kind = os.getenv("DUAL_RUNTIME_ACCEPTANCE_RUNTIME_KIND", "").strip()
    if not job_id or runtime_kind not in AGENTS:
        raise RuntimeError("real cancellation inspection input is invalid")
    job = _wait_for_job(
        runtime,
        job_id,
        expected=JobStatus.FAILED,
        timeout_seconds=180,
    )
    delivery = _wait_for_delivery(runtime, job_id, timeout_seconds=90)
    _assert_runtime_evidence(runtime, job_id=job_id, runtime_kind=runtime_kind)
    counts = runtime.database.execute_one(
        """
        select
          (select count(*) from agent_runtime_terminal_ledger
            where invocation_id like ?) as terminal_count,
          (select count(*) from agent_runtime_invocation_claim
            where invocation_id like ?) as claim_count,
          (select count(*) from agent_runtime_invocation_event
            where invocation_id like ?) as prefix_count,
          (select count(*) from delivery_outbox where job_id = ?) as delivery_count
        """,
        (f"{job_id}.%", f"{job_id}.%", f"{job_id}.%", job_id),
    )
    if counts != {
        "terminal_count": 1,
        "claim_count": 0,
        "prefix_count": 0,
        "delivery_count": 1,
    }:
        raise RuntimeError(f"real cancellation idempotency counts mismatch: {counts}")
    if job.retry_count != 0 or job.last_error_code != "runtime_cancelled":
        raise RuntimeError("real cancellation did not fail closed with runtime_cancelled")
    if str(delivery.delivery_binding.get("delivery_kind") or "") != "failure":
        raise RuntimeError("real cancellation did not create a failure Delivery")
    attempts = runtime.agent_repository.list_delivery_attempts(job_id)
    if len(attempts) != 1 or attempts[0]["status"] not in {
        "SUCCEEDED",
        "SKIPPED",
    }:
        raise RuntimeError("real cancellation failure Delivery was not dispatched once")
    _assert_sensitive_boundaries(runtime, [job_id])
    print(
        json.dumps(
            {
                "status": "passed",
                "runtime_kind": runtime_kind,
                "job_status": job.status.value,
                "failure_code": job.last_error_code,
                "delivery_kind": delivery.delivery_binding["delivery_kind"],
                "delivery_status": delivery.status.value,
                **counts,
            },
            sort_keys=True,
        )
    )
    return 0


def _create_restart_job(runtime: Container) -> int:
    runtime_kind = os.getenv("DUAL_RUNTIME_ACCEPTANCE_RUNTIME_KIND", "").strip()
    if runtime_kind not in AGENTS:
        raise RuntimeError("restart drill requires a supported Runtime kind")
    phase = os.getenv("DUAL_RUNTIME_ACCEPTANCE_PHASE", "").strip()
    if phase not in {"before", "streaming", "after-terminal"}:
        raise RuntimeError("restart drill phase is invalid")
    question = (
        "[smoke:restart-slow] isolated restart acceptance"
        if phase == "streaming"
        else "[smoke:success] isolated restart acceptance"
    )
    publications, applications = _prepare_runtime(runtime, (runtime_kind,))
    job_id = _create_job(
        runtime,
        label=f"restart-{runtime_kind}-{phase}",
        question=question,
        agent=publications[runtime_kind],
        application=applications[runtime_kind],
    )
    claim_observed = False
    terminal_observed_before_worker_commit = False
    if phase == "streaming":
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            row = runtime.database.execute_one(
                """
                select count(*) as count
                  from agent_runtime_invocation_claim
                 where invocation_id like ?
                """,
                (f"{job_id}.%",),
            )
            if row and int(row["count"]) == 1:
                claim_observed = True
                break
            job = runtime.agent_repository.get_job(job_id)
            if job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED}:
                raise RuntimeError("streaming Job reached terminal before claim was observed")
            time.sleep(0.05)
        if not claim_observed:
            raise TimeoutError("streaming Job claim was not observed")
    if phase == "after-terminal":
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            job = runtime.agent_repository.get_job(job_id)
            row = runtime.database.execute_one(
                """
                select count(*) as count
                  from agent_runtime_terminal_ledger
                 where invocation_id like ?
                """,
                (f"{job_id}.%",),
            )
            if job.status == JobStatus.RUNNING and row and int(row["count"]) == 1:
                terminal_observed_before_worker_commit = True
                break
            if job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED}:
                raise RuntimeError("Worker committed before restart window was observed")
            time.sleep(0.05)
        if not terminal_observed_before_worker_commit:
            raise TimeoutError("Runtime terminal before Worker commit was not observed")
    print(
        json.dumps(
            {
                "status": "created",
                "phase": phase,
                "runtime_kind": runtime_kind,
                "job_id": job_id,
                "claim_observed": claim_observed,
                "terminal_observed_before_worker_commit": (terminal_observed_before_worker_commit),
            },
            sort_keys=True,
        )
    )
    return 0


def _inspect_restart_job(runtime: Container) -> int:
    job_id = os.getenv("DUAL_RUNTIME_ACCEPTANCE_JOB_ID", "").strip()
    runtime_kind = os.getenv("DUAL_RUNTIME_ACCEPTANCE_RUNTIME_KIND", "").strip()
    expected_value = os.getenv("DUAL_RUNTIME_ACCEPTANCE_EXPECTED_STATUS", "").strip()
    if not job_id or runtime_kind not in AGENTS or expected_value not in {"SUCCEEDED", "FAILED"}:
        raise RuntimeError("restart drill inspection input is invalid")
    expected = JobStatus(expected_value)
    job = _wait_for_job(runtime, job_id, expected=expected, timeout_seconds=120)
    delivery = _wait_for_delivery(runtime, job_id, timeout_seconds=60)
    _assert_runtime_evidence(runtime, job_id=job_id, runtime_kind=runtime_kind)
    counts = runtime.database.execute_one(
        """
        select
          (select count(*) from agent_runtime_terminal_ledger
            where invocation_id like ?) as terminal_count,
          (select count(*) from agent_runtime_invocation_claim
            where invocation_id like ?) as claim_count,
          (select count(*) from agent_runtime_invocation_event
            where invocation_id like ?) as prefix_count,
          (select count(*) from delivery_outbox where job_id = ?) as delivery_count
        """,
        (f"{job_id}.%", f"{job_id}.%", f"{job_id}.%", job_id),
    )
    if counts != {
        "terminal_count": 1,
        "claim_count": 0,
        "prefix_count": 0,
        "delivery_count": 1,
    }:
        raise RuntimeError(f"restart drill idempotency counts mismatch: {counts}")
    terminals = [
        item
        for item in runtime.agent_repository.list_runtime_events(job_id)
        if item["event_type"] == "terminal"
    ]
    failure_code = str((terminals[-1]["payload"].get("failure") or {}).get("code") or "")
    if expected == JobStatus.FAILED and failure_code != "runtime_orphaned_invocation":
        raise RuntimeError(f"restart drill failure code mismatch: {failure_code}")
    _assert_sensitive_boundaries(runtime, [job_id])
    print(
        json.dumps(
            {
                "status": "passed",
                "runtime_kind": runtime_kind,
                "job_status": job.status.value,
                "failure_code": failure_code,
                "delivery_status": delivery.status.value,
                **counts,
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    global ACTOR_ID

    settings = load_settings()
    if settings.environment not in {"test", "testing"}:
        raise RuntimeError("dual Runtime Compose acceptance requires APP_ENV=test/testing")
    runtime = build_api_container(settings, seed=False)
    try:
        actor = runtime.identity_repository.get_user_by_username(ACTOR_USERNAME)
        if actor is None:
            raise RuntimeError(
                f"dual Runtime Compose acceptance actor {ACTOR_USERNAME!r} is missing"
            )
        ACTOR_ID = str(actor["id"])
        if runtime.settings.queue.retry_delay_seconds != 1:
            raise RuntimeError("AGENT_RETRY_DELAY_SECONDS must be 1 for acceptance")
        action = os.getenv("DUAL_RUNTIME_ACCEPTANCE_ACTION", "full").strip()
        provider_mode = os.getenv("AGENT_RUNTIME_TEST_PROVIDER_MODE", "").strip()
        if action in REAL_ACTIONS:
            if provider_mode != "disabled":
                raise RuntimeError("real dual Runtime acceptance requires provider mode disabled")
            if action == "real-full":
                return _run_real_full(runtime)
            if action == "create-real-cancel-job":
                return _create_real_cancel_job(runtime)
            return _inspect_real_cancel_job(runtime)
        if provider_mode != "deterministic":
            raise RuntimeError("dual Runtime Compose acceptance requires deterministic mode")
        if action == "create-restart-job":
            return _create_restart_job(runtime)
        if action == "inspect-restart-job":
            return _inspect_restart_job(runtime)
        if action != "full":
            raise RuntimeError("unknown dual Runtime acceptance action")
        publications, applications = _prepare_runtime(runtime, tuple(AGENTS))

        scenarios: list[tuple[str, str, str, JobStatus, int]] = []
        for runtime_kind in AGENTS:
            scenarios.extend(
                (
                    (runtime_kind, "success", "[smoke:success]", JobStatus.SUCCEEDED, 0),
                    (
                        runtime_kind,
                        "retry",
                        "[smoke:retry-once]",
                        JobStatus.SUCCEEDED,
                        1,
                    ),
                    (runtime_kind, "dead", "[smoke:dead]", JobStatus.FAILED, 0),
                )
            )
        results: list[dict[str, Any]] = []
        job_ids: list[str] = []
        for runtime_kind, outcome, marker, expected, retry_count in scenarios:
            label = f"{runtime_kind}-{outcome}"
            job_id = _create_job(
                runtime,
                label=label,
                question=f"{marker} isolated acceptance",
                agent=publications[runtime_kind],
                application=applications[runtime_kind],
            )
            job_ids.append(job_id)
            job = _wait_for_job(runtime, job_id, expected=expected)
            if job.retry_count != retry_count:
                raise RuntimeError(
                    f"Job {job_id} retry_count={job.retry_count}; expected {retry_count}"
                )
            delivery = _wait_for_delivery(runtime, job_id)
            _assert_runtime_evidence(
                runtime,
                job_id=job_id,
                runtime_kind=runtime_kind,
            )
            results.append(
                {
                    "runtime_kind": runtime_kind,
                    "outcome": outcome,
                    "job_status": job.status.value,
                    "retry_count": job.retry_count,
                    "delivery_status": delivery.status.value,
                }
            )
        mcp_publications, mcp_applications, mcp_sensitive_values = _prepare_mcp_runtime(
            runtime,
            tuple(AGENTS),
        )
        mcp_scenarios = (
            ("python-v1", "tool-mcp", READONLY_TOOL, "[smoke:mcp:tool-mcp]", 1, False),
            ("python-v1", "ones-mcp", ONES_TOOL, "[smoke:mcp:ones-mcp]", 1, True),
            (
                "typescript-v1",
                "tool-mcp",
                READONLY_TOOL,
                "[smoke:mcp:tool-mcp]",
                1,
                False,
            ),
            (
                "typescript-v1",
                "ones-mcp",
                ONES_TOOL,
                "[smoke:mcp:ones-mcp-concurrent]",
                2,
                False,
            ),
        )
        mcp_job_ids: list[str] = []
        for runtime_kind, server_code, tool_name, marker, call_count, refresh in mcp_scenarios:
            label = f"{runtime_kind}-{server_code}-{uuid.uuid4().hex[:6]}"
            job_id = _create_job(
                runtime,
                label=label,
                question=f"{marker} isolated MCP acceptance",
                agent=mcp_publications[runtime_kind],
                application=mcp_applications[runtime_kind],
            )
            job_ids.append(job_id)
            mcp_job_ids.append(job_id)
            job = _wait_for_job(runtime, job_id, expected=JobStatus.SUCCEEDED)
            delivery = _wait_for_delivery(runtime, job_id)
            _assert_runtime_evidence(runtime, job_id=job_id, runtime_kind=runtime_kind)
            _assert_mcp_evidence(
                runtime,
                job_id=job_id,
                server_code=server_code,
                tool_name=tool_name,
                expected_calls=call_count,
                require_refresh=refresh,
            )
            results.append(
                {
                    "runtime_kind": runtime_kind,
                    "outcome": f"mcp-{server_code}",
                    "job_status": job.status.value,
                    "retry_count": job.retry_count,
                    "delivery_status": delivery.status.value,
                    "mcp_tool_calls": call_count,
                }
            )
        _assert_mcp_online_invariants(
            runtime,
            job_ids=mcp_job_ids,
            sensitive_values=mcp_sensitive_values,
        )
        _assert_sensitive_boundaries(runtime, job_ids)
        print(json.dumps({"status": "passed", "scenarios": results}, sort_keys=True))
        return 0
    finally:
        runtime.database.close()


if __name__ == "__main__":
    raise SystemExit(main())
