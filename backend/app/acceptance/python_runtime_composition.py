from __future__ import annotations

import json
import os
from pathlib import Path
import time
import uuid
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import yaml

from app.bootstrap import Container, build_api_container
from app.modules.identity.infrastructure.external_identity_credentials import (
    CredentialSecretBundle,
)
from app.modules.job.domain.job_status import JobStatus
from app.modules.job.infrastructure.repositories import now_iso
from app.modules.platform_config.infrastructure import PlatformConfigRepository
from app.shared.config import load_settings
from app.shared.exceptions import NotFound


ACTOR_USERNAME = "admin"
AGENT_CODE = "default-diagnostic-agent"
RUNTIME_KIND = "python-v1"
ONES_TOOL = "ones_work_item_search"
FILE_TOOL = "task_workspace_get"
FILE_READ_TOOLS = (
    "task_workspace_get",
    "task_workspace_list_files",
    "task_workspace_search_files",
    "file_get_metadata",
    "file_prepare_materialization",
)
ONES_MOCK_CONFIG_ENV = "ONES_MOCK_ACCEPTANCE_CONFIG"
TEST_SECRET_CANARY = "python-runtime-acceptance-provider-secret-canary-v1"
STALE_ONES_TOKEN = "python-runtime-acceptance-stale-ones-token"
TERMINAL_DELIVERY_STATUSES = {"SUCCEEDED", "FAILED", "DEAD", "SKIPPED"}
DEBUG_API_BASE_URL_ENV = "PYTHON_RUNTIME_ACCEPTANCE_API_BASE_URL"


def _configure_model_connection(runtime: Container, actor_id: str) -> dict[str, Any]:
    service = runtime.model_connection_service
    service.dns_resolver = lambda *_args, **_kwargs: [(2, 1, 6, "", ("8.8.8.8", 443))]
    code = f"python-runtime-acceptance-{uuid.uuid4().hex[:8]}"
    try:
        current = service.get(code)
    except NotFound:
        current = service.repository.create_connection(
            code=code,
            name="Disposable Python Runtime Compose acceptance",
            protocol="anthropic_compatible",
            actor_id=actor_id,
        )
    model = runtime.settings.claude_model
    return service.save_revision(
        actor_id=actor_id,
        code=code,
        expected_revision=int(current["revision"]),
        config={
            "protocol": "anthropic_compatible",
            "base_url": "https://api.deepseek.com/anthropic",
            "model": model,
            "default_opus_model": model,
            "default_sonnet_model": model,
            "default_haiku_model": model,
            "subagent_model": model,
            "effort_level": "max",
        },
        api_key=TEST_SECRET_CANARY,
    )


def _ensure_debug_connector(runtime: Container) -> None:
    runtime.database.execute(
        """
        insert into integration_connector
          (id, connector_type, name, base_url, enabled, metadata,
           allow_ingress, allow_delivery, secret_ref, endpoint_ref,
           host_allowlist, created_at, updated_at)
        values
          ('connector-debug-api', 'debug_api', 'debug-api', '', 1, '{}',
           1, 0, '', '', '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        on conflict(id) do nothing
        """
    )


def _publish_agent(
    runtime: Container,
    actor_id: str,
    *,
    connection_revision_id: str,
    mcp_tool_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    detail = runtime.agent_config_service.get(AGENT_CODE)
    config = dict(detail["draft"]["config"])
    config["business_role"] = "Isolated Python Runtime Compose acceptance Agent"
    config["business_instructions"] = "Run only the deterministic acceptance scenario."
    config["model_policy"] = {
        "runtime": "claude_agent_sdk",
        "model": runtime.settings.claude_model,
        "model_connection_revision_id": connection_revision_id,
    }
    config["execution"] = {"max_turns": 4, "timeout_seconds": 60}
    config["mcp_tool_ids"] = list(mcp_tool_ids)
    config["skills"] = []
    config["channels"] = {"ingress": [], "delivery": []}
    revision = runtime.agent_config_service.save_draft(
        actor_id=actor_id,
        agent_code=AGENT_CODE,
        expected_revision=int(detail["draft"]["revision"]),
        config=config,
    )
    publication = runtime.agent_config_service.publish(
        actor_id=actor_id,
        agent_code=AGENT_CODE,
        revision_id=str(revision["id"]),
    )
    if str(publication.get("runtime_kind") or "") != RUNTIME_KIND:
        raise RuntimeError("Acceptance Agent publication is not Python Runtime")
    return publication


def _activate_debug_application(
    runtime: Container,
    actor_id: str,
    *,
    agent_publication_id: str,
    mcp_tool_ids: tuple[str, ...] = (),
    task_file_features: dict[str, bool] | None = None,
) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:8]
    code = f"python-runtime-acceptance-{suffix}"
    frozen_file_features = dict(task_file_features or {})
    file_workspace_enabled = bool(frozen_file_features.get("workspace_enabled"))
    application = runtime.business_application_service.create(
        actor_id=actor_id,
        code=code,
        name=code,
        description="Isolated Python Runtime Compose acceptance",
        project_code="default",
        owner_user_id=actor_id,
    )
    revision = runtime.business_application_service.save_draft(
        actor_id=actor_id,
        code=code,
        expected_revision=int(application["revision"]),
        payload={
            "agent_publication_id": agent_publication_id,
            "workflow_publication_id": "",
            "session_policy": {
                "conversation_mode": "channel",
                "recent_message_limit": 20,
                "retention_days": 1,
                "continuous_conversation_enabled": file_workspace_enabled,
                "attachments_enabled": file_workspace_enabled,
            },
            "execution_policy": {
                "max_turns": 4,
                "timeout_seconds": 60,
                "max_tool_calls": 8 if mcp_tool_ids else 0,
            },
            "triggers": [],
            "deliveries": [],
            "mcp_tools": list(mcp_tool_ids),
            "task_workspace_retention_period": "DAY",
            "task_file_features": frozen_file_features,
        },
    )
    publication = runtime.business_application_service.publish(
        actor_id=actor_id,
        code=code,
        revision_id=str(revision["id"]),
    )
    runtime.business_application_service.activate(
        actor_id=actor_id,
        code=code,
        environment="local",
        publication_id=str(publication["id"]),
        expected_revision=0,
    )

    platform = PlatformConfigRepository(runtime.database)
    environment = platform.upsert_environment(
        code="local",
        display_name="Isolated acceptance environment",
    )
    base = platform.upsert_base(
        environment_code="local",
        code="acceptance",
        display_name="Isolated acceptance base",
        engine="postgresql",
    )
    role = runtime.authorization_center_service.create_role(
        actor_id=actor_id,
        code=f"{code}-runtime-user",
        name=f"{code}-runtime-user",
        description="Explicit isolated Compose acceptance access",
        purpose_tags=["业务运行"],
    )["role"]
    runtime.authorization_center_service.replace_admin_capabilities(
        actor_id=actor_id,
        role_id=str(role["id"]),
        expected_revision=1,
        bindings=[{"capability_code": "agent.debug.execute", "resource_code": "*"}],
        confirmed=True,
        reason="隔离 Python Runtime Compose 验收",
    )
    runtime.authorization_center_service.replace_business_access(
        actor_id=actor_id,
        role_id=str(role["id"]),
        expected_revision=1,
        applications=[
            {
                "application_id": str(application["id"]),
                "tool_identifiers": list(mcp_tool_ids),
                "scopes": [
                    {
                        "environment_id": str(environment["id"]),
                        "base_id": str(base["id"]),
                    }
                ],
            }
        ],
        confirmed=True,
        reason="隔离 Python Runtime Compose 验收",
    )
    runtime.identity_repository.assign_role(
        user_id=actor_id,
        role_id=str(role["id"]),
        assigned_by=actor_id,
    )
    options = runtime.debug_job_access_service.available_options(
        user_id=actor_id,
        environment="local",
    )
    selected = next(
        item for item in options["applications"] if str(item["id"]) == str(application["id"])
    )
    scopes = list(selected["execution_scopes"])
    if len(scopes) != 1:
        raise RuntimeError("Acceptance application execution scope is ambiguous")
    return {
        "application_id": str(application["id"]),
        "execution_scope_id": str(scopes[0]["id"]),
    }


def _configure_ones_mock_identity(
    runtime: Container,
    actor_id: str,
) -> tuple[str, ...]:
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
        user_id=actor_id,
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


def _create_debug_job(
    *,
    selection: dict[str, str],
    label: str,
    question: str,
) -> str:
    base_url = os.getenv(DEBUG_API_BASE_URL_ENV, "http://api-server:8000").rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname != "api-server" or parsed.path:
        raise RuntimeError("Python Runtime acceptance Debug API URL is not deployment-fixed")
    payload = json.dumps(
        {
            "message": question,
            "application_id": selection["application_id"],
            "execution_scope_id": selection["execution_scope_id"],
            "idempotency_key": f"{label}-{uuid.uuid4().hex}",
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = Request(
        f"{base_url}/api/agent/jobs",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Admin-User-Id": ACTOR_USERNAME,
            "X-Correlation-Id": f"python-runtime-compose-{label}",
        },
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        body = response.read(64 * 1024 + 1)
    if len(body) > 64 * 1024:
        raise RuntimeError("Python Runtime acceptance Debug API response is too large")
    decoded = json.loads(body)
    if not isinstance(decoded, dict) or decoded.get("accepted") is not True:
        raise RuntimeError("Python Runtime acceptance Debug API rejected the Job")
    job_id = str(decoded.get("job_id") or "")
    if not job_id:
        raise RuntimeError("Python Runtime acceptance Debug API omitted the Job ID")
    return job_id


def _wait_for_job(
    runtime: Container,
    job_id: str,
    *,
    expected: JobStatus,
    timeout_seconds: int = 120,
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
        time.sleep(0.25)
    raise TimeoutError(f"Job {job_id} did not reach {expected.value}")


def _wait_for_delivery(runtime: Container, job_id: str, timeout_seconds: int = 60) -> Any:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        event = runtime.agent_repository.get_delivery_event_for_job(job_id)
        if event and event.status.value in TERMINAL_DELIVERY_STATUSES:
            return event
        time.sleep(0.25)
    raise TimeoutError(f"Delivery for Job {job_id} did not become terminal")


def _assert_chain_evidence(runtime: Container, job_id: str) -> None:
    job = runtime.agent_repository.get_job(job_id)
    dispatch = runtime.agent_repository.get_dispatch_event_for_job(job_id)
    if dispatch is None or dispatch.status.value != "PUBLISHED":
        raise RuntimeError(f"Job {job_id} dispatch outbox was not published")
    events = runtime.agent_repository.list_runtime_events(job_id)
    terminals = [item for item in events if item["event_type"] == "terminal"]
    if len(terminals) != job.retry_count + 1:
        raise RuntimeError(f"Job {job_id} has {len(terminals)} Runtime terminals")
    if any(
        dict(item["payload"].get("runtime_provenance") or {}).get("runtime_kind") != RUNTIME_KIND
        for item in terminals
    ):
        raise RuntimeError(f"Job {job_id} Runtime provenance mismatch")
    expected_invocations = {f"{job_id}.attempt-{attempt}" for attempt in range(job.retry_count + 1)}
    if {str(item["invocation_id"]) for item in terminals} != expected_invocations:
        raise RuntimeError(f"Job {job_id} Runtime invocation evidence is incomplete")
    audit_types = {
        str(item["event_type"])
        for item in runtime.database.execute(
            "select event_type from audit_event where job_id = ?",
            (job_id,),
        )
    }
    delivery_audit = (
        "result.delivery.requested" if job.status == JobStatus.SUCCEEDED else "job.dead.persisted"
    )
    if "worker.claimed" not in audit_types or delivery_audit not in audit_types:
        raise RuntimeError(f"Job {job_id} Worker or Delivery audit evidence is incomplete")


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
        raise RuntimeError(f"Job {job_id} MCP audit root count mismatch")
    root_by_call = {str(item["mcp_call_id"]): item for item in roots}
    for call in calls:
        root = root_by_call.get(str(call["mcp_call_id"]))
        if root is None or str(root["agent_tool_call_id"]) != str(call["id"]):
            raise RuntimeError(f"Job {job_id} MCP exact linkage is incomplete")
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
    if not {"job.retry.scheduled", "job.retry.released"}.issubset(audit_types):
        raise RuntimeError(f"Job {job_id} retry audit evidence is incomplete")


def _assert_sensitive_boundaries(
    runtime: Container,
    job_ids: list[str],
    sensitive_values: tuple[str, ...],
) -> None:
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
        select model_runtime_provenance_json from agent_job
         where id in ({placeholders})
        union all
        select events_json from agent_runtime_terminal_ledger
         where {" or ".join("invocation_id like ?" for _ in job_ids)}
        """,
        tuple(job_ids * 5 + [f"{job_id}.%" for job_id in job_ids]),
    )
    serialized = "\n".join(str(row["value"] or "") for row in persisted)
    forbidden = (*sensitive_values, TEST_SECRET_CANARY, "runtime_grant_private")
    if any(value and value in serialized for value in forbidden):
        raise RuntimeError("Acceptance evidence contains authentication material")


def main() -> int:
    settings = load_settings()
    if settings.environment not in {"test", "testing"}:
        raise RuntimeError("Python Runtime Compose acceptance requires APP_ENV=test/testing")
    if os.getenv("AGENT_RUNTIME_TEST_PROVIDER_MODE", "").strip() != "deterministic":
        raise RuntimeError("Python Runtime Compose acceptance requires deterministic provider mode")
    if settings.queue.retry_delay_seconds != 1 or settings.queue.max_retry_count != 1:
        raise RuntimeError("Acceptance retry policy must be exactly one retry after one second")

    runtime = build_api_container(settings, seed=False)
    try:
        actor = runtime.identity_repository.get_user_by_username(ACTOR_USERNAME)
        if actor is None:
            raise RuntimeError("Python Runtime Compose acceptance actor is missing")
        actor_id = str(actor["id"])
        _ensure_debug_connector(runtime)
        connection = _configure_model_connection(runtime, actor_id)

        base_publication = _publish_agent(
            runtime,
            actor_id,
            connection_revision_id=str(connection["id"]),
        )
        base_selection = _activate_debug_application(
            runtime,
            actor_id,
            agent_publication_id=str(base_publication["id"]),
        )
        scenarios = (
            ("success", "[smoke:success] isolated acceptance", JobStatus.SUCCEEDED, 0),
            ("retry", "[smoke:retry-once] isolated acceptance", JobStatus.SUCCEEDED, 1),
            ("dead", "[smoke:dead] isolated acceptance", JobStatus.FAILED, 0),
        )
        results: list[dict[str, Any]] = []
        job_ids: list[str] = []
        for label, question, expected, retry_count in scenarios:
            job_id = _create_debug_job(
                selection=base_selection,
                label=label,
                question=question,
            )
            job_ids.append(job_id)
            job = _wait_for_job(runtime, job_id, expected=expected)
            if job.retry_count != retry_count:
                raise RuntimeError(f"Job {job_id} retry count mismatch")
            delivery = _wait_for_delivery(runtime, job_id)
            _assert_chain_evidence(runtime, job_id)
            if label == "retry":
                _assert_retry_evidence(runtime, job_id)
            results.append(
                {
                    "scenario": label,
                    "job_id": job_id,
                    "job_status": job.status.value,
                    "retry_count": job.retry_count,
                    "delivery_status": delivery.status.value,
                }
            )

        sensitive_values = _configure_ones_mock_identity(runtime, actor_id)
        mcp_tools = (ONES_TOOL,)
        mcp_publication = _publish_agent(
            runtime,
            actor_id,
            connection_revision_id=str(connection["id"]),
            mcp_tool_ids=mcp_tools,
        )
        mcp_selection = _activate_debug_application(
            runtime,
            actor_id,
            agent_publication_id=str(mcp_publication["id"]),
            mcp_tool_ids=mcp_tools,
        )
        mcp_scenarios = (
            (
                "ones-mcp",
                ONES_TOOL,
                "[smoke:mcp:ones-mcp-concurrent]",
                2,
                True,
            ),
        )
        for server_code, tool_name, marker, expected_calls, require_refresh in mcp_scenarios:
            job_id = _create_debug_job(
                selection=mcp_selection,
                label=server_code,
                question=f"{marker} isolated MCP acceptance",
            )
            job_ids.append(job_id)
            job = _wait_for_job(runtime, job_id, expected=JobStatus.SUCCEEDED)
            delivery = _wait_for_delivery(runtime, job_id)
            _assert_chain_evidence(runtime, job_id)
            _assert_mcp_evidence(
                runtime,
                job_id=job_id,
                server_code=server_code,
                tool_name=tool_name,
                expected_calls=expected_calls,
                require_refresh=require_refresh,
            )
            results.append(
                {
                    "scenario": server_code,
                    "job_id": job_id,
                    "job_status": job.status.value,
                    "mcp_tool_calls": expected_calls,
                    "delivery_status": delivery.status.value,
                }
            )

        file_features = {
            "workspace_enabled": True,
            "file_mcp_enabled": True,
            "runtime_file_edit_enabled": False,
            "default_file_delivery_enabled": False,
        }
        file_publication = _publish_agent(
            runtime,
            actor_id,
            connection_revision_id=str(connection["id"]),
            mcp_tool_ids=FILE_READ_TOOLS,
        )
        file_selection = _activate_debug_application(
            runtime,
            actor_id,
            agent_publication_id=str(file_publication["id"]),
            mcp_tool_ids=FILE_READ_TOOLS,
            task_file_features=file_features,
        )
        file_job_id = _create_debug_job(
            selection=file_selection,
            label="file-service",
            question=("[smoke:mcp:file-service] 请创建 TXT 文件并检查隔离任务工作区"),
        )
        job_ids.append(file_job_id)
        file_job = _wait_for_job(runtime, file_job_id, expected=JobStatus.SUCCEEDED)
        file_delivery = _wait_for_delivery(runtime, file_job_id)
        if not file_job.task_workspace_id or file_job.agent_runtime_protocol_version != "1.4":
            raise RuntimeError("File Service acceptance Job did not freeze its workspace")
        _assert_chain_evidence(runtime, file_job_id)
        _assert_mcp_evidence(
            runtime,
            job_id=file_job_id,
            server_code="file-service",
            tool_name=FILE_TOOL,
            expected_calls=1,
        )
        results.append(
            {
                "scenario": "file-service",
                "job_id": file_job_id,
                "job_status": file_job.status.value,
                "mcp_tool_calls": 1,
                "delivery_status": file_delivery.status.value,
            }
        )

        _assert_sensitive_boundaries(runtime, job_ids, sensitive_values)
        print(
            json.dumps(
                {
                    "status": "passed",
                    "runtime_kind": RUNTIME_KIND,
                    "scenario_count": len(results),
                    "scenarios": results,
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        runtime.database.close()


if __name__ == "__main__":
    raise SystemExit(main())
