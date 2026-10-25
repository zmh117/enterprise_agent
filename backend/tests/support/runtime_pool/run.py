"""Disposable Compose acceptance. Never reads the project's deployment secrets."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import time
import uuid
from typing import Any, Callable
from urllib.request import urlopen

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[4]
COMPOSE = Path(__file__).with_name("compose.yml")


def compose(root: Path, *args: str) -> str:
    state = json.loads((root / "state.json").read_text())
    files = ["--file", str(COMPOSE)]
    override = root / "compose.override.yml"
    if override.exists():
        files.extend(["--file", str(override)])
    result = subprocess.run(
        ["docker", "compose", "--project-name", state["project"], *files, *args],
        env={
            **os.environ,
            "RPOOL_FIXTURE_DIR": str(root),
            "RPOOL_AFTER_RESULT_PAUSE_SECONDS": str(state.get("result_pause", 0)),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Compose operation failed: " + result.stderr[-4000:])
    return result.stdout.strip()


def wait_for(check: Callable[[], Any], timeout: int = 60) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.25)
    raise TimeoutError("Acceptance condition did not converge")


def initialize() -> Path:
    root = Path(tempfile.mkdtemp(prefix="ea-runtime-pool-"))
    (root / "secrets").mkdir()
    (root / "evidence").mkdir(mode=0o777)
    (root / "evidence").chmod(0o777)
    (root / "state.json").write_text(
        json.dumps(
            {"project": "ea-rpool-" + uuid.uuid4().hex[:8], "owner": "runtime-pool-acceptance/v1"}
        )
    )
    grant = Ed25519PrivateKey.generate()
    principal = Ed25519PrivateKey.generate()
    values = {
        "master": (
            "EA_MASTER_KEY_V1:"
            + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
        ).encode(),
        "grant-private": grant.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        "grant-public": grant.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
        "principal-private": principal.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        "probe": secrets.token_urlsafe(32).encode(),
    }
    for name, content in values.items():
        target = root / "secrets" / name
        target.write_bytes(content)
        target.chmod(0o444)
    # Host key loaders require owner-only files; container secret mounts require read-only mode.
    (root / "host").mkdir()
    for name, content in values.items():
        target = root / "host" / name
        target.write_bytes(content)
        target.chmod(0o400)
    compose(root, "up", "-d", "--wait", "postgres", "rabbitmq")
    state = json.loads((root / "state.json").read_text())
    state["dsn"] = (
        "postgresql://postgres@" + compose(root, "port", "postgres", "5432") + "/runtime_pool_test"
    )
    state["rabbitmq"] = "amqp://guest:guest@" + compose(root, "port", "rabbitmq", "5672") + "/"
    (root / "state.json").write_text(json.dumps(state))
    runtime = container(root, seed=True)
    runtime.database.execute("create role agent_runtime_reader login")
    for statement in (ROOT / "backend/maintenance/agent_runtime_grants.sql").read_text().split(";"):
        if statement.strip():
            runtime.database.execute(statement)
    runtime.database.close()
    return root


def container(root: Path, *, seed: bool = False) -> Any:
    from app.bootstrap import build_test_container
    from app.shared.config import AgentRuntimeSettings, Settings
    from backend.tests.support.runtime import direct_job_permission_service_factory

    os.environ.update(
        BUILD_ID="local-dev", BUILD_SOURCE_REVISION="local-dev", BUILD_PLATFORM="linux/arm64"
    )
    state = json.loads((root / "state.json").read_text())
    if state.get("nodes"):
        state["nodes"] = {
            node: "http://" + compose(root, "port", "runtime-" + node, "8091") for node in "abc"
        }
        (root / "state.json").write_text(json.dumps(state))
    nodes = tuple((name, url) for name, url in state.get("nodes", {}).items())
    settings = Settings(
        database_dsn=state["dsn"],
        rabbitmq_url=state["rabbitmq"],
        environment="testing",
        app_config_master_key_file=str(root / "host/master"),
        model_provider_host_allowlist=tuple(state.get("provider_hosts", ["api.deepseek.com"])),
        agent_runtime=AgentRuntimeSettings(
            python_base_url=nodes[0][1] if nodes else "",
            python_nodes=nodes,
            python_allowed_hosts=("127.0.0.1",),
            allow_insecure_internal_http=True,
            model_probe_auth_token_file=str(root / "host/probe"),
        ),
    )
    runtime = build_test_container(
        settings,
        migrate=seed,
        seed=seed,
        configure_seed_secrets=not state.get("real_provider", False),
        service_name="api-server",
        permission_service_factory=direct_job_permission_service_factory,
    )
    runtime.create_agent_job_service.published_agent_runtime_enabled = True
    return runtime


def start(root: Path) -> None:
    compose(root, "up", "-d", "runtime-a", "runtime-b", "runtime-c")
    state = json.loads((root / "state.json").read_text())
    state["nodes"] = {
        node: "http://" + compose(root, "port", "runtime-" + node, "8091") for node in "abc"
    }
    (root / "state.json").write_text(json.dumps(state))

    def ready(url: str) -> bool:
        try:
            with urlopen(url + "/ready", timeout=2) as response:
                return response.status == 200
        except OSError:
            return False

    for url in state["nodes"].values():
        wait_for(lambda: ready(url))
    runtime = container(root)
    from app.acceptance.python_runtime_composition import (
        _configure_model_connection,
        _activate_debug_application,
        _ensure_debug_connector,
    )

    connection = _configure_model_connection(runtime, "user_local_admin")
    code = "default-diagnostic-agent"
    detail = runtime.agent_config_service.get(code)
    config = dict(detail["draft"]["config"])
    config.pop("tools", None)
    config.update(
        model_policy={
            "runtime": "claude_agent_sdk",
            "model": runtime.settings.claude_model,
            "model_connection_revision_id": connection["id"],
        },
        execution={"max_turns": 4, "timeout_seconds": 180},
        mcp_tool_ids=[],
        skills=[],
        channels={"ingress": [], "delivery": []},
    )
    revision = runtime.agent_config_service.save_draft(
        actor_id="user_local_admin",
        agent_code=code,
        expected_revision=detail["draft"]["revision"],
        config=config,
    )
    publication = runtime.agent_config_service.publish(
        actor_id="user_local_admin", agent_code=code, revision_id=revision["id"]
    )
    state["publication"] = publication["id"]
    _ensure_debug_connector(runtime)
    state["selection"] = _activate_debug_application(
        runtime, "user_local_admin", agent_publication_id=publication["id"]
    )
    (root / "state.json").write_text(json.dumps(state))
    runtime.database.close()
    compose(root, "up", "-d", "worker", "dispatcher")


def create_job(
    runtime: Any,
    root: Path,
    question: str = "[pool:block] [smoke:success] synthetic",
    **kwargs: Any,
) -> Any:
    state = json.loads((root / "state.json").read_text())
    job, _ = runtime.debug_job_access_service.create_job(
        user_id="user_local_admin",
        display_name="Synthetic acceptance",
        message=question,
        application_id=state["selection"]["application_id"],
        execution_scope_id=state["selection"]["execution_scope_id"],
        delivery_binding_id="",
        idempotency_key="pool-" + uuid.uuid4().hex,
        correlation_id="pool-" + uuid.uuid4().hex,
        environment="local",
        **kwargs,
    )
    return job


def journal(root: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for path in (root / "evidence").glob("*.jsonl")
        for line in path.read_text().splitlines()
    ]


def parallel(root: Path) -> None:
    runtime = container(root)
    jobs = [create_job(runtime, root) for _ in range(4)]
    ids = [job.id for job in jobs]

    def rows() -> list[dict[str, Any]]:
        return runtime.database.execute(
            "select invocation_id, job_id, state, node_id, instance_id from agent_runtime_invocation"
        )

    running = wait_for(
        lambda: (
            [row for row in rows() if row["job_id"] in ids and row["state"] == "RUNNING"]
            if sum(row["job_id"] in ids and row["state"] == "RUNNING" for row in rows()) == 3
            else False
        )
    )
    assert len({row["node_id"] for row in running}) == 3
    queued = next(job for job in jobs if job.id not in {row["job_id"] for row in running})
    time.sleep(6)
    assert runtime.agent_repository.get_job(queued.id).retry_count == 0
    assert not any(
        row["invocation_id"].startswith(queued.id) and row["kind"] == "provider_start"
        for row in journal(root)
    )
    for row in running:
        (root / "evidence" / ("release-" + row["invocation_id"])).touch()
    wait_for(
        lambda: any(
            row["invocation_id"].startswith(queued.id) and row["kind"] == "provider_start"
            for row in journal(root)
        )
    )
    (root / "evidence" / ("release-" + queued.id + ".attempt-0")).touch()
    wait_for(
        lambda: all(
            runtime.agent_repository.get_job(key).status.value == "SUCCEEDED" for key in ids
        )
    )
    events = [row for row in journal(root) if row["invocation_id"].split(".attempt-")[0] in ids]
    starts = [row for row in events if row["kind"] == "provider_start"]
    assert len(starts) == 4
    first = sorted(starts, key=lambda row: row["time"])[:3]
    ends = {row["invocation_id"]: row["time"] for row in events if row["kind"] == "provider_end"}
    overlap = min(ends[row["invocation_id"]] for row in first) - max(row["time"] for row in first)
    assert overlap > 0
    report = {
        "case": "RPOOL-02",
        "status": "PASS",
        "job_ids": ids,
        "overlap_seconds": overlap,
        "provider_starts": 4,
        "nodes": sorted({row["node_id"] for row in starts}),
        "events": events,
    }
    (root / "evidence/parallel.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({key: value for key, value in report.items() if key != "events"}))
    runtime.database.close()


def report(root: Path, case: str, **values: Any) -> None:
    payload = {"case": case, "status": "PASS", **values}
    (root / "evidence" / (case + ".json")).write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload), flush=True)


def started(runtime: Any, root: Path, job_id: str) -> dict[str, Any]:
    def observed() -> Any:
        row = runtime.database.execute_one(
            "select * from agent_runtime_invocation where job_id = ?", (job_id,)
        )
        return (
            row
            if row
            and row["state"] == "RUNNING"
            and any(
                item["invocation_id"] == row["invocation_id"] and item["kind"] == "provider_start"
                for item in journal(root)
            )
            else None
        )

    return wait_for(observed)


def terminal(runtime: Any, job_id: str, timeout: int = 90) -> Any:
    def observed() -> Any:
        job = runtime.agent_repository.get_job(job_id)
        return job if job.status.value in {"SUCCEEDED", "FAILED", "TIMEOUT"} else None

    return wait_for(observed, timeout)


def assert_count(root: Path, job_id: str, expected: int = 1) -> None:
    assert (
        sum(
            row["kind"] == "provider_start" and row["invocation_id"].split(".attempt-")[0] == job_id
            for row in journal(root)
        )
        == expected
    )


def session_order(root: Path) -> None:
    from app.modules.agent.infrastructure.runtime_pool_store import RuntimePoolStore

    runtime = container(root)
    first = create_job(runtime, root, "[pool:block] [smoke:success] prior-synthetic-input")
    started(runtime, root, first.id)
    second = create_job(
        runtime,
        root,
        "[smoke:success] second-synthetic-input",
        continue_session_id=first.session_id,
    )
    third = create_job(
        runtime,
        root,
        "[smoke:success] future-synthetic-input",
        continue_session_id=first.session_id,
    )
    time.sleep(4)
    assert runtime.agent_repository.get_job(second.id).status.value == "PENDING"
    assert (
        runtime.database.execute_one(
            "select 1 from agent_runtime_invocation where job_id = ?", (second.id,)
        )
        is None
    )
    (root / "evidence" / ("release-" + first.id + ".attempt-0")).touch()
    result = terminal(runtime, first.id)
    assert terminal(runtime, second.id).status.value == "SUCCEEDED"
    assert terminal(runtime, third.id).status.value == "SUCCEEDED"
    frozen = RuntimePoolStore(runtime.database).request(second.id + ".attempt-0")
    history = frozen["prompt"]["conversation_summary"]
    assert result.result in history
    assert "prior-synthetic-input" in history and "future-synthetic-input" not in history
    rows = runtime.database.execute(
        "select job_id,accepted_at,execution_quiesced_at from agent_runtime_invocation where job_id in (?, ?, ?) order by accepted_at",
        (first.id, second.id, third.id),
    )
    assert [row["job_id"] for row in rows] == [first.id, second.id, third.id]
    assert all(
        rows[index]["execution_quiesced_at"] <= rows[index + 1]["accepted_at"] for index in (0, 1)
    )
    report(
        root,
        "RPOOL-03",
        job_ids=[first.id, second.id, third.id],
        serialized=True,
        late_reply_included=True,
        future_input_excluded=True,
    )
    runtime.database.close()


def worker_loss(root: Path) -> None:
    runtime = container(root)
    job = create_job(runtime, root)
    original = started(runtime, root, job.id)
    version = runtime.agent_repository.get_job(job.id).worker_claim_version
    compose(root, "kill", "--signal", "SIGKILL", "worker")
    compose(root, "up", "-d", "worker")
    wait_for(lambda: runtime.agent_repository.get_job(job.id).worker_claim_version > version, 50)
    recovered = runtime.database.execute_one(
        "select * from agent_runtime_invocation where job_id = ?", (job.id,)
    )
    assert recovered is not None
    for field in (
        "invocation_id",
        "request_digest",
        "node_id",
        "instance_id",
        "execution_deadline_at",
    ):
        assert original[field] == recovered[field]
    (root / "evidence" / ("release-" + original["invocation_id"])).touch()
    assert terminal(runtime, job.id).status.value == "SUCCEEDED"
    assert_count(root, job.id)
    report(
        root,
        "RPOOL-07",
        job_id=job.id,
        provider_starts=1,
        original_version=version,
        final_version=runtime.agent_repository.get_job(job.id).worker_claim_version,
        owner_unchanged=True,
    )
    runtime.database.close()


def runtime_loss(root: Path, *, before_sdk: bool = False) -> None:
    runtime = container(root)
    job = create_job(
        runtime,
        root,
        "[pool:crash-before-sdk] synthetic" if before_sdk else "[pool:block] synthetic",
    )
    if not before_sdk:
        original = started(runtime, root, job.id)
        compose(root, "kill", "--signal", "SIGKILL", "runtime-" + original["node_id"])
        compose(root, "up", "-d", "runtime-" + original["node_id"])
    final = terminal(runtime, job.id)
    row = runtime.database.execute_one(
        "select * from agent_runtime_invocation where job_id = ?", (job.id,)
    )
    assert final.status.value == "FAILED" and final.retry_count == 0
    assert final.last_error_code == "runtime_invocation_outcome_unknown"
    assert row and row["execution_quiesced_at"] is not None
    assert_count(root, job.id, 0 if before_sdk else 1)
    report(
        root,
        "RPOOL-05" if before_sdk else "RPOOL-08",
        job_id=job.id,
        provider_starts=0 if before_sdk else 1,
        terminal_code=row["terminal_code"],
        stopped=True,
    )
    runtime.database.close()


def cancel_without_notify(root: Path) -> None:
    from app.modules.job.application.cancel_agent_job import cancel_agent_job

    runtime = container(root)
    job = create_job(runtime, root)
    original = started(runtime, root, job.id)
    compose(root, "kill", "--signal", "SIGKILL", "worker")
    stamp = time.monotonic()
    assert cancel_agent_job(runtime.database, job.id, "user_local_admin") == "cancel_requested"
    row = wait_for(
        lambda: runtime.database.execute_one(
            "select terminal_code, execution_quiesced_at from agent_runtime_invocation where invocation_id = ? and state = 'TERMINAL'",
            (original["invocation_id"],),
        ),
        15,
    )
    assert row["terminal_code"] == "runtime_cancelled" and row["execution_quiesced_at"]
    latency = time.monotonic() - stamp
    compose(root, "up", "-d", "worker")
    assert terminal(runtime, job.id).last_error_code == "runtime_cancelled"
    assert_count(root, job.id)
    report(
        root,
        "RPOOL-11",
        job_id=job.id,
        notification_sent=False,
        cancellation_seconds=latency,
        provider_starts=1,
        stopped=True,
    )
    runtime.database.close()


def connection_loss(root: Path, *, response: bool = False) -> None:
    runtime = container(root)
    marker = "[pool:drop-response]" if response else "[pool:drop-stream]"
    job = create_job(runtime, root, "[pool:block] " + marker + " synthetic")
    original = started(runtime, root, job.id)
    wait_for(lambda: runtime.agent_repository.get_job(job.id).worker_claim_version >= 2, 20)
    (root / "evidence" / ("release-" + original["invocation_id"])).touch()
    assert terminal(runtime, job.id).status.value == "SUCCEEDED"
    assert_count(root, job.id)
    report(
        root,
        "RPOOL-04" if response else "RPOOL-06",
        job_id=job.id,
        provider_starts=1,
        recovered=True,
    )
    runtime.database.close()


def delayed_stop(root: Path) -> None:
    from app.modules.job.application.cancel_agent_job import cancel_agent_job

    runtime = container(root)
    job = create_job(runtime, root, "[pool:block] [pool:ignore-cancel] synthetic")
    original = started(runtime, root, job.id)
    successor = create_job(
        runtime, root, "[smoke:success] synthetic successor", continue_session_id=job.session_id
    )
    stamp = time.monotonic()
    assert cancel_agent_job(runtime.database, job.id, "user_local_admin") == "cancel_requested"
    time.sleep(7)
    row = runtime.database.execute_one(
        "select execution_quiesced_at from agent_runtime_invocation where job_id = ?", (job.id,)
    )
    assert row and row["execution_quiesced_at"] is None
    assert runtime.agent_repository.get_job(successor.id).status.value == "PENDING"
    final = terminal(runtime, job.id)
    assert final.last_error_code == "runtime_invocation_outcome_unknown"
    assert terminal(runtime, successor.id).status.value == "SUCCEEDED"
    assert_count(root, job.id)
    report(
        root,
        "RPOOL-11-delayed-stop",
        job_id=job.id,
        successor_id=successor.id,
        elapsed_seconds=time.monotonic() - stamp,
        provider_starts=1,
        no_early_session_release=True,
        outcome=final.last_error_code,
        original_instance=original["instance_id"],
    )
    runtime.database.close()


def result_commit_loss(root: Path) -> None:
    state = json.loads((root / "state.json").read_text())
    state["result_pause"] = 20
    (root / "state.json").write_text(json.dumps(state))
    compose(root, "up", "-d", "--force-recreate", "worker")
    runtime = container(root)
    try:
        job = create_job(runtime, root, "[smoke:success] synthetic commit rollback")
        row = wait_for(
            lambda: runtime.database.execute_one(
                "select invocation_id from agent_runtime_invocation where job_id = ? and state = 'TERMINAL'",
                (job.id,),
            )
        )
        time.sleep(1)
        assert runtime.agent_repository.get_job(job.id).status.value == "RUNNING"
        compose(root, "kill", "--signal", "SIGKILL", "worker")
    finally:
        state["result_pause"] = 0
        (root / "state.json").write_text(json.dumps(state))
        compose(root, "up", "-d", "--force-recreate", "worker")
    final = terminal(runtime, job.id)
    assert (
        final.status.value == "SUCCEEDED"
        and final.retry_count == 0
        and final.worker_claim_version > 1
    )
    assert_count(root, job.id)
    count = runtime.database.execute_one(
        "select count(*) as n from agent_message where job_id = ? and role = 'assistant'", (job.id,)
    )["n"]
    deliveries = runtime.database.execute_one(
        "select count(*) as n from delivery_outbox where job_id = ?", (job.id,)
    )["n"]
    assert count == 1 and deliveries == 1
    report(
        root,
        "RPOOL-09",
        job_id=job.id,
        invocation_id=row["invocation_id"],
        provider_starts=1,
        assistant_messages=count,
        deliveries=deliveries,
    )
    runtime.database.close()


def database_loss(root: Path) -> None:
    runtime = container(root)
    job = create_job(runtime, root, "[pool:block] [pool:ignore-cancel] synthetic database loss")
    original = started(runtime, root, job.id)
    compose(root, "pause", "postgres")
    try:
        time.sleep(39)
    finally:
        compose(root, "unpause", "postgres")
    final = terminal(runtime, job.id)
    assert final.last_error_code == "runtime_invocation_outcome_unknown" and final.retry_count == 0
    row = runtime.database.execute_one(
        "select execution_quiesced_at from agent_runtime_invocation where job_id = ?", (job.id,)
    )
    assert row and row["execution_quiesced_at"]
    assert_count(root, job.id)
    report(
        root,
        "RPOOL-12",
        job_id=job.id,
        database_pause_seconds=39,
        provider_starts=1,
        outcome=final.last_error_code,
        stopped=True,
        original_instance=original["instance_id"],
    )
    runtime.database.close()


def probe_and_drain(root: Path) -> None:
    from dataclasses import replace
    from app.modules.agent.infrastructure.runtime_http_client import (
        RuntimeClientSettings,
        probe_runtime_readiness,
    )
    from app.modules.agent.infrastructure.runtime_pool_store import RuntimePoolStore
    from app.modules.model_connection.infrastructure.runtime_probe import (
        RuntimeModelProbeClient,
        RuntimeModelProbeSettings,
    )

    runtime = container(root)
    job = create_job(runtime, root)
    original = started(runtime, root, job.id)
    state = json.loads((root / "state.json").read_text())
    node, url = original["node_id"], state["nodes"][original["node_id"]]
    request = RuntimePoolStore(runtime.database).request(original["invocation_id"])
    probe_settings = RuntimeModelProbeSettings(
        base_url=url,
        allowed_hosts=("127.0.0.1",),
        auth_token_file=str(root / "host/probe"),
        nodes=((node, url),),
    )
    probe = RuntimeModelProbeClient(probe_settings)

    def probe_call(client: Any) -> Any:
        return client.probe(
            revision_id=request["model_connection"]["revision_id"],
            config_hash=request["model_connection"]["config_hash"],
            timeout_seconds=5,
        )

    try:
        probe_call(probe)
        raise AssertionError("probe entered an occupied execution slot")
    except Exception as exc:
        assert getattr(exc, "error_code", "") == "runtime_pool_busy", type(exc).__name__
    all_nodes = tuple(state["nodes"].items())
    assert probe_call(RuntimeModelProbeClient(replace(probe_settings, nodes=all_nodes)))["success"]
    compose(root, "exec", "-T", "runtime-" + node, "touch", "/tmp/python-agent-runtime/draining")
    try:
        status = probe_runtime_readiness(
            RuntimeClientSettings(
                base_url=url, nodes=all_nodes, allowed_runtime_hosts=("127.0.0.1",)
            )
        )
        assert status["pool_status"] == "DEGRADED"
        other = create_job(runtime, root, "[smoke:success] synthetic while draining")
        assert terminal(runtime, other.id).status.value == "SUCCEEDED"
        assert (
            runtime.database.execute_one(
                "select node_id from agent_runtime_invocation where job_id = ?", (other.id,)
            )["node_id"]
            != node
        )
        (root / "evidence" / ("release-" + original["invocation_id"])).touch()
        assert terminal(runtime, job.id).status.value == "SUCCEEDED"
    finally:
        compose(root, "exec", "-T", "runtime-" + node, "rm", "/tmp/python-agent-runtime/draining")
    assert_count(root, job.id)
    report(
        root,
        "RPOOL-13",
        job_id=job.id,
        probe_busy_rejected=True,
        idle_node_probe_succeeded=True,
        control_during_execution=True,
    )
    report(
        root,
        "RPOOL-14",
        job_id=job.id,
        drained_node=node,
        new_job_id=other.id,
        existing_execution_completed=True,
        pool_degraded=True,
    )
    runtime.database.close()


def retry_order(root: Path) -> None:
    runtime = container(root)
    first = create_job(runtime, root, "[smoke:retry-once] synthetic retry")
    second = create_job(
        runtime,
        root,
        "[smoke:success] synthetic retry successor",
        continue_session_id=first.session_id,
    )
    wait_for(lambda: runtime.agent_repository.get_job(first.id).status.value == "RETRY_WAIT")
    assert runtime.agent_repository.get_job(second.id).status.value == "PENDING"
    assert terminal(runtime, first.id).retry_count == 1
    assert terminal(runtime, second.id).status.value == "SUCCEEDED"
    rows = runtime.database.execute(
        "select attempt, accepted_at, execution_quiesced_at from agent_runtime_invocation where job_id = ? order by attempt",
        (first.id,),
    )
    assert len(rows) == 2 and rows[0]["execution_quiesced_at"] <= rows[1]["accepted_at"]
    assert_count(root, first.id, 2)
    report(
        root,
        "RPOOL-18",
        job_ids=[first.id, second.id],
        business_retry_count=1,
        provider_starts=2,
        no_session_overtake=True,
    )
    runtime.database.close()


def broker_loss(root: Path) -> None:
    runtime = container(root)
    job = create_job(runtime, root)
    original = started(runtime, root, job.id)
    compose(root, "pause", "rabbitmq")
    try:
        time.sleep(16)
    finally:
        compose(root, "unpause", "rabbitmq")
    (root / "evidence" / ("release-" + original["invocation_id"])).touch()
    assert terminal(runtime, job.id).status.value == "SUCCEEDED"
    time.sleep(6)
    assert_count(root, job.id)
    report(
        root,
        "RPOOL-17-broker",
        job_id=job.id,
        heartbeat_seconds=5,
        broker_pause_seconds=16,
        provider_starts=1,
        duplicate_redelivery_safe=True,
    )
    runtime.database.close()


def unavailable_pool(root: Path) -> None:
    runtime = container(root)
    compose(root, "stop", "--timeout", "3", "worker", "dispatcher")
    job = create_job(runtime, root, "[smoke:success] synthetic admission expiry")
    compose(root, "stop", "--timeout", "3", "runtime-a", "runtime-b", "runtime-c")
    try:
        compose(root, "up", "-d", "worker", "dispatcher")
        row = wait_for(
            lambda: runtime.database.execute_one(
                "select wait_reason from job_dispatch_outbox where job_id = ? and wait_reason = 'runtime_unavailable'",
                (job.id,),
            ),
            30,
        )
        assert row
        version = runtime.agent_repository.get_job(job.id).worker_claim_version
        time.sleep(7)
        current = runtime.agent_repository.get_job(job.id)
        assert current.retry_count == 0 and current.worker_claim_version - version < 10
        runtime.database.execute(
            "update agent_job set admission_deadline_at = '2000-01-01T00:00:00+00:00' where id = ?",
            (job.id,),
        )
        runtime.database.execute(
            "update agent_runtime_invocation set admission_deadline_at = '2000-01-01T00:00:00+00:00' where job_id = ?",
            (job.id,),
        )
        final = terminal(runtime, job.id)
        assert (
            final.status.value == "TIMEOUT"
            and final.last_error_code == "runtime_admission_timeout"
            and final.retry_count == 0
        )
        assert_count(root, job.id, 0)
        report(
            root,
            "RPOOL-17-unavailable",
            job_id=job.id,
            provider_starts=0,
            outcome=final.last_error_code,
            bounded_deferral=True,
        )
    finally:
        compose(root, "up", "-d", "runtime-a", "runtime-b", "runtime-c")
        runtime.database.close()


def admission_race(root: Path) -> None:  # noqa: PLR0915 - ordered fault-injection scenario
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace
    from threading import Barrier
    from urllib.error import HTTPError
    from urllib.request import Request
    from app.modules.agent.domain.runtime import AgentRunRequest
    from app.modules.agent.infrastructure.runtime_http_client import (
        AgentRuntimeHttpClient,
        RuntimeClientSettings,
        RuntimeGrantIssuer,
    )
    from app.modules.agent.infrastructure.runtime_pool_store import RuntimePoolStore
    from app.modules.job.infrastructure.execution_control import JobExecutionControl

    runtime = container(root)
    compose(root, "stop", "--timeout", "3", "worker", "dispatcher")
    try:
        job = create_job(runtime, root)
        claimed = runtime.agent_repository.claim_job(job.id, "acceptance-observer")
        assert claimed is not None
        context = runtime.agent_executor.context_builder.build(claimed)
        context = replace(
            context,
            job_tool_snapshot_hash=runtime.mcp_tool_snapshot_service.verify(job.id)[
                "snapshot_hash"
            ],
        )
        run_request = AgentRunRequest(
            job_id=job.id,
            user_id=job.internal_user_id,
            project_code=job.project_code,
            context=context,
            invocation_id=job.id + ".attempt-0",
            worker_id="acceptance-observer",
            worker_claim_version=claimed.worker_claim_version,
        )
        state = json.loads((root / "state.json").read_text())
        settings = RuntimeClientSettings(
            base_url=state["nodes"]["a"],
            nodes=tuple(state["nodes"].items()),
            allowed_runtime_hosts=("127.0.0.1",),
        )
        issuer = RuntimeGrantIssuer.from_file(str(root / "host/grant-private"))
        client = AgentRuntimeHttpClient(
            settings=settings, grant_issuer=issuer, database=runtime.database
        )
        frozen = client._frozen_request(run_request)
        gate = Barrier(2)

        def send(node: str) -> dict[str, Any]:
            base = state["nodes"][node]
            with urlopen(base + "/version", timeout=3) as response:
                version = json.load(response)
            headers = {
                "Authorization": "Bearer " + issuer.issue(frozen),
                "Content-Type": "application/json",
                "X-Runtime-Node-Id": node,
                "X-Runtime-Instance-Id": version["instance_id"],
            }
            gate.wait(timeout=10)
            try:
                with urlopen(
                    Request(
                        base + "/internal/v1/executions",
                        data=json.dumps(frozen).encode(),
                        headers=headers,
                        method="POST",
                    ),
                    timeout=10,
                ) as response:
                    first = json.loads(response.readline())
                    return {"node": node, "status": response.status, "sequence": first["sequence"]}
            except HTTPError as exc:
                return {"node": node, "status": exc.code, "code": json.load(exc)["code"]}

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(send, ("a", "b")))
        assert sorted(item["status"] for item in results) == [200, 409]
        assert (
            next(item for item in results if item["status"] == 409)["code"]
            == "runtime_invocation_owner_mismatch"
        )
        original = started(runtime, root, job.id)
        (root / "evidence" / ("release-" + original["invocation_id"])).touch()
        wait_for(
            lambda: runtime.database.execute_one(
                "select 1 from agent_runtime_invocation where job_id = ? and state = 'TERMINAL'",
                (job.id,),
            )
        )
        other = "b" if original["node_id"] == "a" else "a"
        JobExecutionControl(runtime.database).defer(
            job.id, "acceptance-observer", claimed.worker_claim_version, reason="runtime_recovery"
        )
        runtime.agent_executor.runtime_client = AgentRuntimeHttpClient(
            settings=replace(
                settings, base_url=state["nodes"][other], nodes=((other, state["nodes"][other]),)
            ),
            grant_issuer=issuer,
            database=runtime.database,
        )
        assert runtime.agent_executor.execute(
            job.id, worker_id="replacement-observer", fail_on_error=False
        )
        assert RuntimePoolStore(runtime.database).request(original["invocation_id"]) == frozen
        assert_count(root, job.id)
        report(
            root,
            "RPOOL-01",
            job_id=job.id,
            concurrent_http_results=results,
            provider_starts=1,
            owner=original["node_id"],
        )
        report(
            root,
            "RPOOL-09-cross-node",
            job_id=job.id,
            original_node=original["node_id"],
            replay_node=other,
            provider_starts=1,
            minimal_recovery_without_principal=True,
        )
        verify_body_retention(root, runtime, frozen, issuer, state["nodes"][other], other)
    finally:
        compose(root, "up", "-d", "worker", "dispatcher")
        runtime.database.close()


def verify_body_retention(
    root: Path, runtime: Any, frozen: dict[str, Any], issuer: Any, base: str, node: str
) -> None:
    from urllib.error import HTTPError
    from urllib.request import Request
    from app.modules.agent.infrastructure.runtime_pool_store import RuntimePoolStore

    with urlopen(base + "/version", timeout=3) as response:
        version = json.load(response)
    headers = {
        "Authorization": "Bearer " + issuer.issue(frozen),
        "Content-Type": "application/json",
        "X-Runtime-Node-Id": node,
        "X-Runtime-Instance-Id": version["instance_id"],
    }
    execute_url = base + "/internal/v1/executions"
    # Exercise full-request replay before pruning to detect stale in-memory bodies.
    with urlopen(
        Request(execute_url, data=json.dumps(frozen).encode(), headers=headers, method="POST"),
        timeout=10,
    ) as response:
        assert response.status == 200
        assert (
            json.loads(response.read().decode().strip().splitlines()[-1])["event_type"]
            == "terminal"
        )
    pool = RuntimePoolStore(runtime.database)
    assert pool.prune_body(frozen["invocation_id"])
    minimal = {key: frozen[key] for key in ("invocation_id", "request_digest")}
    for url, body in (
        (execute_url, frozen),
        (execute_url + "/" + frozen["invocation_id"] + "/recover", minimal),
    ):
        try:
            with urlopen(
                Request(url, data=json.dumps(body).encode(), headers=headers, method="POST"),
                timeout=10,
            ):
                raise AssertionError("Pruned terminal must not replay from memory")
        except HTTPError as exc:
            assert exc.code == 410 and json.load(exc)["code"] == "runtime_recovery_expired"
    assert pool.get(frozen["invocation_id"]) is not None
    assert_count(root, frozen["job_id"])
    report(
        root,
        "RPOOL-16",
        job_id=frozen["job_id"],
        provider_starts=1,
        identity_retained=True,
        full_request_replay_after_prune=410,
        minimal_recovery_after_prune=410,
    )


def cleanup(root: Path) -> None:
    state = json.loads((root / "state.json").read_text())
    if state.get("owner") != "runtime-pool-acceptance/v1" or not state["project"].startswith(
        "ea-rpool-"
    ):
        raise ValueError("Cleanup requires this fixture's ownership marker")
    compose(root, "down", "--volumes", "--remove-orphans", "--timeout", "3")
    for name in ("secrets", "host"):
        if (root / name).exists():
            shutil.rmtree(root / name)
    print(
        json.dumps(
            {
                "project": state["project"],
                "containers_removed": True,
                "generated_keys_removed": True,
            }
        )
    )


def main() -> None:
    actions: dict[str, Callable[[Path], None]] = {
        "admission-race": admission_race,
        "start": start,
        "parallel": parallel,
        "session": session_order,
        "worker-loss": worker_loss,
        "runtime-loss": runtime_loss,
        "pre-sdk-crash": lambda root: runtime_loss(root, before_sdk=True),
        "cancel": cancel_without_notify,
        "drop-response": lambda root: connection_loss(root, response=True),
        "drop-stream": connection_loss,
        "delayed-stop": delayed_stop,
        "result-rollback": result_commit_loss,
        "database-loss": database_loss,
        "probe-drain": probe_and_drain,
        "retry": retry_order,
        "broker-loss": broker_loss,
        "unavailable": unavailable_pool,
        "cleanup": cleanup,
    }
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("init", *actions))
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    if args.action == "init":
        print(initialize())
    else:
        if args.root is None:
            parser.error("--root is required for an existing disposable fixture")
        actions[args.action](args.root)


if __name__ == "__main__":
    main()
